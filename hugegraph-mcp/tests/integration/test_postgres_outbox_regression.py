# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid

import pytest

from hugegraph_mcp.events import ResourceEvent
from hugegraph_mcp.stores.base import Actor, PlanOutcome
from hugegraph_mcp.stores.postgres import PostgresPlanStore
from hugegraph_mcp.write_plan import GraphTarget, OperationPlan, PlanStatus, WritePlan

PG_DSN = os.getenv("HUGEGRAPH_MCP_TEST_PG_DSN", "postgresql://postgres:mcp_test_pass@127.0.0.1:15432/hugegraph_mcp")


def _make_plan(plan_id: str, *, principal: str) -> WritePlan:
    now = int(time.time())
    return WritePlan(
        plan_id=plan_id,
        tool_name="manage_schema_tool",
        graph_target=GraphTarget(graph_url="http://127.0.0.1:18080", graph_name="hugegraph", graphspace="DEFAULT"),
        principal=principal,
        created_at=now,
        expires_at=now + 300,
        status=PlanStatus.ISSUED,
        schema_fingerprint=f"fp_{plan_id}",
        operations=(
            OperationPlan(
                operation_id="op_1",
                kind="property_key_create",
                target={"name": f"pk_{plan_id}"},
                expected_state={},
                desired_state={"data_type": "INT"},
            ),
        ),
        payload_digest=f"digest_{plan_id}",
    )


@pytest.mark.integration
def test_outbox_fetch_since_does_not_skip_committed_event_behind_open_unrelated_tx():
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    run_id = uuid.uuid4().hex[:8]
    deployment = f"outbox_reg_{run_id}"
    plan_id = f"wp_outbox_reg_{run_id}"
    actor = Actor(
        issuer="bearer", tenant="t_reg", subject=f"user_{run_id}", scopes=frozenset({"mcp:read", "mcp:write"})
    )

    async def scenario() -> None:
        writer_store = PostgresPlanStore(PG_DSN, deployment_id=deployment)
        reader_store = PostgresPlanStore(PG_DSN, deployment_id=deployment)
        unrelated_conn = await psycopg.AsyncConnection.connect(PG_DSN)
        try:
            await writer_store.prepare()
            await reader_store.prepare()

            # Advance baseline cursor past any pre-existing outbox rows.
            baseline_seq = 0
            while True:
                batch = await reader_store.fetch_outbox_since(baseline_seq, limit=1000)
                if not batch:
                    break
                baseline_seq = batch[-1][0]

            # Connection 1: open an unrelated transaction and pin xmin by allocating an xid.
            async with unrelated_conn.transaction():
                await unrelated_conn.execute("SELECT txid_current()")

                # Connection 2: commit a plan finish + outbox event with a newer txid than Connection 1.
                await writer_store.create(_make_plan(plan_id, principal=actor.principal_key), actor)
                lease = await writer_store.claim(plan_id, actor, f"pod_{run_id}", ttl_s=30)
                evt = ResourceEvent.create(
                    deployment=deployment,
                    graphspace="DEFAULT",
                    graph="hugegraph",
                    uri=f"hugegraph://{deployment}/DEFAULT/hugegraph/schema",
                    kind="updated",
                    resource_version=int(time.time() * 1000),
                )
                await writer_store.finish(
                    lease,
                    actor,
                    expected_version=lease.plan_version,
                    outcome=PlanOutcome(status=PlanStatus.APPLIED, summary={"applied": 1}),
                    events=(evt,),
                )

                # Connection 3: poll BEFORE Connection 1 releases its unrelated transaction.
                polled = await reader_store.fetch_outbox_since(baseline_seq, limit=100)
                polled_ids = [ev.event_id for _seq, ev in polled]
                assert evt.event_id in polled_ids
        finally:
            await unrelated_conn.close()
            await writer_store.close()
            await reader_store.close()

    asyncio.run(scenario())


@pytest.mark.integration
def test_later_writer_cannot_publish_ahead_of_uncommitted_outbox_row():
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def run():
        store = PostgresPlanStore(PG_DSN)
        try:
            await store.prepare()
            deployment = uuid.uuid4().hex
            events = [
                ResourceEvent.create(
                    deployment=deployment,
                    graphspace="DEFAULT",
                    graph="g",
                    uri=f"hugegraph://{deployment}/DEFAULT/g/schema",
                    kind="updated",
                    resource_version=version,
                )
                for version in (1, 2)
            ]
            async with (
                await psycopg.AsyncConnection.connect(PG_DSN) as first,
                await psycopg.AsyncConnection.connect(PG_DSN) as second,
            ):
                await store._insert_outbox_events(first, [events[0]])
                # A second writer must wait for the first transaction to commit.
                await second.execute("SET LOCAL lock_timeout = '250ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    await store._insert_outbox_events(second, [events[1]])
                await second.rollback()
                await first.commit()
                await store._insert_outbox_events(second, [events[1]])
                await second.commit()
                cur = await first.execute(
                    "SELECT event_id FROM event_outbox WHERE deployment = %s ORDER BY seq", (deployment,)
                )
                assert [str(row[0]) for row in await cur.fetchall()] == [event.event_id for event in events]
        finally:
            await store.close()

    asyncio.run(run())
