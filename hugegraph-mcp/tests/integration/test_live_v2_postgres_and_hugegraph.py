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
import json
import os
import sys
import time
import uuid

import pytest
from starlette.testclient import TestClient

from hugegraph_mcp import server
from hugegraph_mcp.auth_middleware import StaticSecretBearerVerifier
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.events import InMemoryEventBus, OutboxEventRelay, ResourceEvent
from hugegraph_mcp.notifications import SubscriptionManager
from hugegraph_mcp.resources import read_schema_resource, read_summary_resource
from hugegraph_mcp.stores.base import Actor, LeaseConflictError, PlanNotFoundError, PlanOutcome
from hugegraph_mcp.stores.postgres import PostgresPlanStore
from hugegraph_mcp.write_plan import (
    ApplyReceipt,
    ApplyStatus,
    GraphTarget,
    OperationPlan,
    PlanStatus,
    WritePlan,
)

PG_DSN = os.getenv("HUGEGRAPH_MCP_TEST_PG_DSN", "postgresql://postgres:mcp_test_pass@127.0.0.1:15432/hugegraph_mcp")
HG_URL = os.getenv("HUGEGRAPH_URL", "http://127.0.0.1:18080")


def _live_plan(plan_id: str) -> WritePlan:
    now = int(time.time())
    return WritePlan(
        plan_id=plan_id,
        tool_name="manage_schema_tool",
        graph_target=GraphTarget(graph_url=HG_URL, graph_name="hugegraph", graphspace="DEFAULT"),
        principal="t_live:alice",
        created_at=now,
        expires_at=now + 300,
        status=PlanStatus.ISSUED,
        schema_fingerprint="fp_live",
        operations=(
            OperationPlan(
                operation_id="op_1",
                kind="property_key_create",
                target={"name": "age"},
                expected_state={},
                desired_state={"data_type": "INT"},
            ),
        ),
        payload_digest=f"digest_{plan_id}",
    )


@pytest.mark.integration
def test_live_postgres_plan_store_concurrency_outbox_and_rollback():
    pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    store = PostgresPlanStore(PG_DSN)
    alice = Actor(issuer="bearer", tenant="t_live", subject="alice", scopes=frozenset({"mcp:read", "mcp:write"}))
    bob = Actor(issuer="bearer", tenant="t_live", subject="bob", scopes=frozenset({"mcp:read", "mcp:write"}))

    pid_race = f"wp_live_race_{uuid.uuid4().hex[:8]}"
    pid_uncertain = f"wp_live_unc_{uuid.uuid4().hex[:8]}"

    async def scenario():
        try:
            await store.prepare()
            await store.check_ready()

            # 1. Create & cross-actor isolation
            await store.create(_live_plan(pid_race), alice)
            with pytest.raises(PlanNotFoundError):
                await store.read(pid_race, bob)

            # 2. Concurrent claim race: strictly one winner
            results = await asyncio.gather(
                store.claim(pid_race, alice, "pod-a", ttl_s=30),
                store.claim(pid_race, alice, "pod-b", ttl_s=30),
                return_exceptions=True,
            )
            wins = [r for r in results if not isinstance(r, BaseException)]
            losses = [r for r in results if isinstance(r, LeaseConflictError)]
            assert len(wins) == 1
            assert len(losses) == 1
            lease = wins[0]

            # 3. Record operation & finish with outbox event
            receipt = ApplyReceipt(
                plan_id=pid_race,
                operation_id="op_1",
                status=ApplyStatus.APPLIED,
                observed_state={"created": "age"},
            )
            updated = await store.record_operation(
                lease, alice, "op_1", expected_version=lease.plan_version, receipt=receipt
            )
            evt = ResourceEvent.create(
                deployment="live-test",
                graphspace="DEFAULT",
                graph="hugegraph",
                uri="hugegraph://live-test/DEFAULT/hugegraph/schema",
                kind="updated",
                resource_version=updated.version + 1,
            )
            finished = await store.finish(
                lease,
                alice,
                expected_version=updated.version,
                outcome=PlanOutcome(status=PlanStatus.APPLIED, summary={"applied": 1}),
                events=(evt,),
            )
            assert finished.status == PlanStatus.APPLIED

            # 4. Terminal APPLIED cannot become UNKNOWN
            with pytest.raises(LeaseConflictError):
                await store.mark_uncertain(pid_race, alice, expected_version=finished.version, reason="nope")

            # 5. OutboxEventRelay consumes committed event & delivers once
            bus = InMemoryEventBus()
            relay = OutboxEventRelay(store, bus)
            mgr = SubscriptionManager()
            delivered: list[str] = []

            async def notify(uri: str) -> None:
                delivered.append(uri)

            mgr.subscribe("sess_1", evt.uri, notify)
            await relay.poll_once()
            for e in bus.recent_events():
                await mgr.dispatch(e)
            assert evt.uri in delivered

            # 6. Non-terminal EXECUTING can transition to UNKNOWN
            await store.create(_live_plan(pid_uncertain), alice)
            lease_u = await store.claim(pid_uncertain, alice, "pod-c", ttl_s=30)
            unc = await store.mark_uncertain(
                pid_uncertain, alice, expected_version=lease_u.plan_version, reason="lease_lost"
            )
            assert unc.status == PlanStatus.UNKNOWN
        finally:
            await store.close()

    asyncio.run(scenario())


@pytest.mark.integration
def test_live_http_app_with_postgres_and_hugegraph(monkeypatch):
    pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    monkeypatch.setenv("HUGEGRAPH_URL", HG_URL)
    monkeypatch.setenv("HUGEGRAPH_USER", "admin")
    monkeypatch.setenv("HUGEGRAPH_PASSWORD", "admin")
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "hugegraph")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "DEFAULT")
    monkeypatch.setenv("HUGEGRAPH_MCP_DEPLOYMENT", "live")
    monkeypatch.setenv("HUGEGRAPH_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_STORE", "postgres")
    monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_STORE_DSN", PG_DSN)
    monkeypatch.setenv("HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT", "2")

    cfg = MCPConfig.from_env()
    app = server.create_http_app(
        cfg,
        require_auth=True,
        verifier=StaticSecretBearerVerifier("live-secret", default_subject="live-agent"),
    )

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["checks"]["plan_store"] == "ok"

        # Real HugeGraph 1.7.0 schema & summary resources via live MCP runtime
        schema_json = json.loads(asyncio.run(read_schema_resource("live", "DEFAULT", "hugegraph")))
        assert schema_json["graph"] == "hugegraph"
        assert len(schema_json["schema_fingerprint"]) == 64

        summary_json = json.loads(asyncio.run(read_summary_resource("live", "DEFAULT", "hugegraph")))
        assert summary_json["status"] == "ok"


@pytest.mark.integration
def test_live_postgres_sync_bridge_write_executor_and_reconcile(monkeypatch):
    pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    from hugegraph_mcp.plan_store import plan_store_from_config
    from hugegraph_mcp.reconciler import ReconcileReaderRegistry, WriteReconciler
    from hugegraph_mcp.write_executor import WriteExecutor, WriteExecutorRegistry
    from hugegraph_mcp.write_plan import ApplyReceipt, ApplyStatus

    monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_STORE", "postgres")
    monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_STORE_DSN", PG_DSN)
    monkeypatch.setenv("HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT", "2")

    cfg = MCPConfig.from_env()
    sync_store = plan_store_from_config(cfg)
    sync_store.prepare()

    pid_exec = f"wp_live_exec_{uuid.uuid4().hex[:8]}"
    plan_exec = _live_plan(pid_exec)
    sync_store.save_plan(plan_exec)

    exec_registry = WriteExecutorRegistry()
    exec_registry.register(
        "property_key_create",
        lambda p, op, attempt: ApplyReceipt(
            plan_id=p.plan_id,
            operation_id=op.operation_id,
            status=ApplyStatus.APPLIED,
            attempt=attempt,
            committed_at=int(time.time()),
        ),
    )
    res = WriteExecutor(store=sync_store, registry=exec_registry).confirm(pid_exec)
    assert res["ok"] is True
    assert res["data"]["status"] == "APPLIED"
    status_res = WriteExecutor(store=sync_store, registry=exec_registry).status(pid_exec)
    assert status_res["ok"] is True
    assert status_res["data"]["operations"][0]["attempt"] == 1

    # Reconcile an UNKNOWN plan on real PostgreSQL
    pid_rec = f"wp_live_rec_{uuid.uuid4().hex[:8]}"
    plan_rec = _live_plan(pid_rec)
    sync_store.save_plan(plan_rec)
    sync_store.transition_plan(pid_rec, expected=PlanStatus.ISSUED, target=PlanStatus.EXECUTING)
    sync_store.transition_plan(pid_rec, expected=PlanStatus.EXECUTING, target=PlanStatus.UNKNOWN, reason="crash")

    readers = ReconcileReaderRegistry()
    readers.register("property_key_create", lambda _p, _op: {"name": "live_age"})
    rec_res = WriteReconciler(store=sync_store, readers=readers).reconcile(pid_rec)
    assert rec_res["ok"] is True
    assert rec_res["data"]["status"] == "RETRYABLE_NOT_APPLIED"
