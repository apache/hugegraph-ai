# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import asyncio
import os

import pytest
from sqlalchemy import func, inspect, select, text
from test_agent_approval import PLANNER
from test_agent_approval import client as _approval_client

from ontogeny.action.models import OutboxRow, RevisionRow
from ontogeny.db import init_schema, make_engine, make_sessionmaker

approval_client = _approval_client
ORDER = {"product_id": "P-101", "qty": 5}


async def execute(sc, action, principal, params, key):
    async with sc.sessionmaker() as session:
        rev = await sc.runtime.execute(session, action, principal, params, idempotency_key=key)
        await session.commit()
        return rev.id, rev.object_id


async def test_same_key_is_scoped_to_action_and_principal_and_replays(approval_client):
    _, sc = approval_client
    first = await execute(sc, "create-production-order", PLANNER, ORDER, "request-1")
    replay = await execute(sc, "create-production-order", PLANNER, ORDER, "request-1")
    other_principal = PLANNER | {"id": "another-planner"}
    second = await execute(sc, "create-production-order", other_principal, ORDER, "request-1")
    third = await execute(sc, "introduce-product", PLANNER, {"name": "New product"}, "request-1")
    assert replay == first
    assert len({first[0], second[0], third[0]}) == 3
    async with sc.sessionmaker() as session:
        rows = (await session.execute(select(RevisionRow).where(RevisionRow.idempotency_key == "request-1"))).scalars()
        assert len(list(rows)) == 3
        assert (
            await session.execute(
                select(func.count())
                .select_from(OutboxRow)
                .where(OutboxRow.revision_id.in_([first[0], second[0], third[0]]))
            )
        ).scalar_one() == 3


async def test_empty_key_is_not_an_idempotency_scope(approval_client):
    _, sc = approval_client
    first = await execute(sc, "create-production-order", PLANNER, ORDER, "")
    second = await execute(sc, "create-production-order", PLANNER, ORDER, "")
    assert first != second
    async with sc.sessionmaker() as session:
        rows = (await session.execute(select(RevisionRow).where(RevisionRow.id.in_([first[0], second[0]])))).scalars()
        assert all(row.idempotency_key is None for row in rows)


async def test_old_global_index_is_replaced_without_losing_revisions(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'old.db'}")
    try:
        await init_schema(engine)
        async with engine.begin() as conn:
            await conn.execute(text("DROP INDEX uq_revision_idem_scope"))
            await conn.execute(
                text(
                    "CREATE UNIQUE INDEX uq_revision_idem ON ontogeny_revision (idempotency_key) "
                    "WHERE idempotency_key IS NOT NULL"
                )
            )
        maker = make_sessionmaker(engine)
        async with maker() as session:
            session.add(
                RevisionRow(
                    action="a",
                    object_type="thing",
                    object_id="1",
                    principal="alice",
                    params={},
                    outcome="executed",
                    idempotency_key="old-key",
                )
            )
            await session.commit()
        await init_schema(engine)
        await init_schema(engine)  # migration is safe to run more than once
        async with engine.connect() as conn:
            indexes = await conn.run_sync(lambda sync: inspect(sync).get_indexes("ontogeny_revision"))
        by_name = {index["name"]: index for index in indexes}
        assert "uq_revision_idem" not in by_name
        assert by_name["uq_revision_idem_scope"]["column_names"] == ["action", "principal", "idempotency_key"]
        async with maker() as session:
            session.add(
                RevisionRow(
                    action="a",
                    object_type="thing",
                    object_id="2",
                    principal="bob",
                    params={},
                    outcome="executed",
                    idempotency_key="old-key",
                )
            )
            await session.commit()
            assert (await session.execute(select(func.count()).select_from(RevisionRow))).scalar_one() == 2
    finally:
        await engine.dispose()


@pytest.mark.skipif(not os.environ.get("ONTOGENY_PG_DSN"), reason="PostgreSQL integration requires ONTOGENY_PG_DSN")
async def test_postgres_old_index_is_replaced_without_losing_revisions(approval_client):
    _, sc = approval_client
    assert sc.engine.dialect.name == "postgresql"
    async with sc.engine.begin() as conn:
        await conn.execute(text("DROP INDEX uq_revision_idem_scope"))
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX uq_revision_idem ON ontogeny_revision (idempotency_key) "
                "WHERE idempotency_key IS NOT NULL"
            )
        )
    async with sc.sessionmaker() as session:
        session.add(
            RevisionRow(
                action="a",
                object_type="thing",
                object_id="1",
                principal="alice",
                params={},
                outcome="executed",
                idempotency_key="old-key",
            )
        )
        await session.commit()
    await init_schema(sc.engine)
    await init_schema(sc.engine)
    async with sc.engine.connect() as conn:
        indexes = await conn.run_sync(lambda sync: inspect(sync).get_indexes("ontogeny_revision"))
    by_name = {index["name"]: index for index in indexes}
    assert "uq_revision_idem" not in by_name
    assert by_name["uq_revision_idem_scope"]["column_names"] == ["action", "principal", "idempotency_key"]
    async with sc.sessionmaker() as session:
        session.add(
            RevisionRow(
                action="a",
                object_type="thing",
                object_id="2",
                principal="bob",
                params={},
                outcome="executed",
                idempotency_key="old-key",
            )
        )
        await session.commit()
        count = (await session.execute(select(func.count()).select_from(RevisionRow))).scalar_one()
        assert count == 2


@pytest.mark.skipif(not os.environ.get("ONTOGENY_PG_DSN"), reason="PostgreSQL concurrency requires ONTOGENY_PG_DSN")
async def test_postgres_same_scope_concurrent_replay_executes_once(approval_client):
    _, sc = approval_client
    assert sc.engine.dialect.name == "postgresql"
    gate = asyncio.Event()

    async def call():
        await gate.wait()
        return await execute(sc, "create-production-order", PLANNER, ORDER, "concurrent-request")

    tasks = [asyncio.create_task(call()) for _ in range(8)]
    gate.set()
    results = await asyncio.gather(*tasks)
    assert len(set(results)) == 1
    async with sc.sessionmaker() as session:
        rows = await session.execute(select(RevisionRow).where(RevisionRow.idempotency_key == "concurrent-request"))
        revisions = rows.scalars().all()
        assert len(revisions) == 1
        assert (
            await session.execute(
                select(func.count()).select_from(OutboxRow).where(OutboxRow.revision_id == revisions[0].id)
            )
        ).scalar_one() == 1
