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
import json
import os
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from ontogeny.action.models import OutboxConsumerRow, OutboxReceiptRow, OutboxRow
from ontogeny.action.outbox import OutboxDispatcher
from ontogeny.config import Settings
from ontogeny.db import init_schema, make_engine, make_sessionmaker
from ontogeny.functions.derivation import DerivationPendingRow, DerivationWorker


def event(oid):
    return OutboxRow(
        object_type="product",
        object_id=oid,
        op="event",
        payload={
            "kind": "webhook",
            "url": "https://sink.example/hook",
        },
    )


async def test_legacy_migration_preserves_history_and_explicit_replay(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    try:
        # Simulate a database created before receipt tracking existed.
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE ontogeny_outbox_cursor (consumer VARCHAR(100) PRIMARY KEY, "
                    "last_id BIGINT NOT NULL, failures INTEGER NOT NULL, updated_at DATETIME NOT NULL)"
                )
            )
            await conn.execute(text("INSERT INTO ontogeny_outbox_cursor VALUES ('webhook', 1, 0, CURRENT_TIMESTAMP)"))
        await init_schema(engine)
        maker = make_sessionmaker(engine)
        async with maker() as s:
            first, second = event("old"), event("pending")
            s.add_all([first, second])
            await s.flush()
            first_id, second_id = first.id, second.id
            await s.commit()
        assert first_id == 1
        calls = []
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)))
        dispatcher = OutboxDispatcher(maker, Settings(webhook_allowlist=("sink.example",)), http_client=http)
        await dispatcher.dispatch_pending()
        assert [json.loads(r.content)["object_id"] for r in calls] == ["pending"]
        async with maker() as s:
            receipts = (
                await s.scalars(select(OutboxReceiptRow.event_id).where(OutboxReceiptRow.consumer == "webhook"))
            ).all()
            assert set(receipts) == {first_id, second_id}
        assert await dispatcher.replay("webhook", from_id=first_id, through_id=first_id) == 1
        await dispatcher.dispatch_pending()
        assert [json.loads(r.content)["object_id"] for r in calls] == ["pending", "old"]
        await http.aclose()
    finally:
        await engine.dispose()


async def test_failed_consumer_retries_without_redelivering_other_consumers(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    try:
        await init_schema(engine)
        maker = make_sessionmaker(engine)
        async with maker() as s:
            row = event("one")
            s.add(row)
            await s.commit()
        calls, attempts = [], []
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200)))

        async def projection(row):
            attempts.append(row.id)
            return len(attempts) > 1

        worker = DerivationWorker(SimpleNamespace(objects={}), None, None, maker)
        worker._trigger_map = lambda: {"product": {"product"}}
        dispatcher = OutboxDispatcher(
            maker,
            Settings(webhook_allowlist=("sink.example",)),
            http_client=http,
            projection_hook=projection,
            derivation_hook=worker.handle_event,
        )
        await dispatcher.dispatch_pending()
        async with maker() as s:
            receipts = (await s.scalars(select(OutboxReceiptRow))).all()
            assert {r.consumer for r in receipts} == {"webhook", "sse", "derivation"}
            assert (await s.get(DerivationPendingRow, {"object_type": "product", "object_id": "one"})) is not None
        await dispatcher.dispatch_pending()
        assert len(calls) == 1 and len(attempts) == 2
        await http.aclose()
    finally:
        await engine.dispose()


async def test_cancelled_transaction_rolls_back_receipt_and_derivation_queue(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    try:
        await init_schema(engine)
        maker = make_sessionmaker(engine)
        async with maker() as s:
            s.add(event("one"))
            await s.commit()
        worker = DerivationWorker(SimpleNamespace(objects={}), None, None, maker)
        worker._trigger_map = lambda: {"product": {"product"}}

        async def cancelled(row, session):
            await worker.handle_event(row, session)
            raise asyncio.CancelledError()

        dispatcher = OutboxDispatcher(maker, Settings(), derivation_hook=cancelled)
        with pytest.raises(asyncio.CancelledError):
            await dispatcher.dispatch_pending()
        async with maker() as s:
            assert (await s.scalars(select(OutboxReceiptRow))).all() == []
            assert (await s.scalars(select(DerivationPendingRow))).all() == []
        dispatcher.derivation_hook = worker.handle_event
        await dispatcher.dispatch_pending()
        async with maker() as s:
            assert (await s.get(DerivationPendingRow, {"object_type": "product", "object_id": "one"})) is not None
            assert {r.consumer for r in (await s.scalars(select(OutboxReceiptRow))).all()} == {
                "webhook",
                "projection",
                "derivation",
                "sse",
            }
    finally:
        await engine.dispose()


@pytest.mark.skipif(not os.environ.get("ONTOGENY_PG_DSN"), reason="PostgreSQL integration requires ONTOGENY_PG_DSN")
async def test_postgres_late_commit_is_delivered_to_each_consumer():
    dsn = os.environ["ONTOGENY_PG_DSN"]
    schema = f"outbox_test_{uuid.uuid4().hex}"
    admin = create_async_engine(dsn)
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(dsn, connect_args={"server_settings": {"search_path": schema}})
    try:
        await init_schema(engine)
        maker = make_sessionmaker(engine)
        deliveries, projection = [], []
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: deliveries.append(r) or httpx.Response(200)))

        async def project(row):
            projection.append(row.object_id)
            return True

        worker = DerivationWorker(SimpleNamespace(objects={}), None, None, maker)
        worker._trigger_map = lambda: {"product": {"product"}}
        dispatcher = OutboxDispatcher(
            maker,
            Settings(webhook_allowlist=("sink.example",)),
            http_client=http,
            projection_hook=project,
            derivation_hook=worker.handle_event,
        )
        queue = dispatcher.sse.subscribe()
        async with maker() as a, maker() as b:
            earlier, later = event("earlier"), event("later")
            a.add(earlier)
            await a.flush()
            b.add(later)
            await b.commit()
            assert earlier.id < later.id
            await dispatcher.dispatch_pending()
            assert [json.loads(r.content)["object_id"] for r in deliveries] == ["later"]
            await a.commit()
            await dispatcher.dispatch_pending()
            await dispatcher.dispatch_pending()

        assert [json.loads(r.content)["object_id"] for r in deliveries] == ["later", "earlier"]
        assert projection == ["later", "earlier"]
        assert [queue.get_nowait()["object_id"] for _ in range(2)] == ["later", "earlier"]
        async with maker() as s:
            pending_ids = set((await s.scalars(select(DerivationPendingRow.object_id))).all())
            receipts = (await s.scalars(select(OutboxReceiptRow))).all()
        assert pending_ids == {"earlier", "later"}
        assert len(receipts) == 8

        # During a legacy upgrade a low-ID insert can still be uncommitted.
        # The migration snapshots visible history only, so this row must not
        # be mistaken for an already delivered historic event.
        async with maker() as s:
            for model in (OutboxReceiptRow, OutboxConsumerRow, DerivationPendingRow, OutboxRow):
                await s.execute(delete(model))
            await s.commit()
        deliveries.clear()
        projection.clear()
        async with maker() as a, maker() as b:
            earlier, later = event("legacy-late"), event("legacy-history")
            a.add(earlier)
            await a.flush()
            b.add(later)
            await b.commit()
            async with maker() as s:
                s.add_all(
                    [
                        OutboxConsumerRow(consumer=name, last_id=later.id)
                        for name in ("webhook", "projection", "derivation", "sse")
                    ]
                )
                await s.commit()
            await dispatcher.dispatch_pending()
            assert deliveries == [] and projection == []
            await a.commit()
            await dispatcher.dispatch_pending()
        assert [json.loads(r.content)["object_id"] for r in deliveries] == ["legacy-late"]
        assert projection == ["legacy-late"]
        assert queue.get_nowait()["object_id"] == "legacy-late"
        async with maker() as s:
            assert set((await s.scalars(select(DerivationPendingRow.object_id))).all()) == {"legacy-late"}
        await http.aclose()
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
