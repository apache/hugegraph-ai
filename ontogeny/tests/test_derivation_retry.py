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

from dataclasses import replace
from pathlib import Path

from sqlalchemy import select
from test_function_ecosystem import sc as sc

from ontogeny.action.models import OutboxConsumerRow, OutboxRow
from ontogeny.functions.derivation import DerivationPendingRow, DerivationWorker
from ontogeny.stores.repo import ObjectRepository

# TO-A1 has no running lots (open_lot_count 0); TO-A0 owns LOT-2419, the one
# lot still RUNNING, so its materialized open_lot_count is 1
OWNER = "tapeout-version"
COUNTED = "TO-A0"
OTHER = "TO-A1"


async def pending(sc):
    async with sc.sessionmaker() as s:
        return {r.object_id: r.generation for r in (await s.scalars(select(DerivationPendingRow))).all()}


async def test_timeout_is_durable_after_cursor_advance_and_worker_recreation(sc, monkeypatch):
    original = sc.functions.map_rows

    async def timeout(*args, **kwargs):
        raise TimeoutError("transient")

    monkeypatch.setattr(sc.functions, "map_rows", timeout)
    await sc.outbox.dispatch_pending()
    assert COUNTED in await pending(sc)
    async with sc.sessionmaker() as s:
        cursor = await s.get(OutboxConsumerRow, "derivation")
        before = cursor.last_id

    monkeypatch.setattr(sc.functions, "map_rows", original)
    worker = DerivationWorker(sc.compiled, sc.repo, sc.functions, sc.sessionmaker)
    assert (await worker.drain())[f"{OWNER}.open_lot_count"] > 0
    assert not await pending(sc)
    async with sc.sessionmaker() as s:
        assert (await s.get(OutboxConsumerRow, "derivation")).last_id == before
        assert (await sc.repo.get(s, OWNER, COUNTED))["open_lot_count"] == 1


async def test_bad_values_and_wrong_batch_length_remain_for_retry(sc, monkeypatch):
    await sc.outbox.dispatch_pending()
    for oid in (OTHER, COUNTED):
        await sc.derivation.handle_event(OutboxRow(object_type=OWNER, object_id=oid, op="upsert"))

    async def partial(session, fn, rows, params, **kwargs):
        return ["bad" if r["version_id"] == OTHER else 7 for r in rows]

    monkeypatch.setattr(sc.functions, "map_rows", partial)
    await sc.derivation.drain()
    assert set(await pending(sc)) == {OTHER}

    async def short(session, fn, rows, params, **kwargs):
        return []

    monkeypatch.setattr(sc.functions, "map_rows", short)
    await sc.derivation.drain()
    assert set(await pending(sc)) == {OTHER}

    async def recover(session, fn, rows, params, **kwargs):
        return [9 for _ in rows]

    monkeypatch.setattr(sc.functions, "map_rows", recover)
    await sc.derivation.drain()
    assert not await pending(sc)


async def test_poisoned_row_does_not_block_other_rows(sc):
    await sc.outbox.dispatch_pending()
    for oid in (OTHER, COUNTED):
        await sc.derivation.handle_event(OutboxRow(object_type=OWNER, object_id=oid, op="upsert"))

    # Exercise the real function subprocess and durable queue: the batched
    # call fails, but a valid object must still be materialized and removed.
    source = Path(sc.compiled.package_root) / "functions" / "lot_count.py"
    source.write_text(
        "def open_lot_count(obj):\n"
        "    if obj['version_id'] == 'TO-A1':\n"
        "        raise ValueError('bad object')\n"
        "    return 7\n",
        encoding="utf-8",
    )
    await sc.derivation.drain()
    assert set(await pending(sc)) == {OTHER}
    async with sc.sessionmaker() as session:
        assert (await sc.repo.get(session, OWNER, COUNTED))["open_lot_count"] == 7

    source.write_text("def open_lot_count(obj):\n    return 9\n", encoding="utf-8")
    await sc.derivation.drain()
    assert not await pending(sc)
    async with sc.sessionmaker() as session:
        assert (await sc.repo.get(session, OWNER, OTHER))["open_lot_count"] == 9


async def test_new_event_during_compute_is_not_acknowledged_or_overwritten(sc, monkeypatch):
    await sc.outbox.dispatch_pending()
    event = OutboxRow(object_type=OWNER, object_id=COUNTED, op="upsert")
    await sc.derivation.handle_event(event)
    old_generation = (await pending(sc))[COUNTED]

    async def requeue(session, fn, rows, params, **kwargs):
        await sc.derivation.handle_event(event)
        return [123 for _ in rows]

    monkeypatch.setattr(sc.functions, "map_rows", requeue)
    await sc.derivation.drain()
    assert (await pending(sc))[COUNTED] != old_generation
    async with sc.sessionmaker() as s:
        assert (await sc.repo.get(s, OWNER, COUNTED))["open_lot_count"] == 1

    async def recover(session, fn, rows, params, **kwargs):
        return [5 for _ in rows]

    monkeypatch.setattr(sc.functions, "map_rows", recover)
    await sc.derivation.drain()
    assert not await pending(sc)
    async with sc.sessionmaker() as s:
        assert (await sc.repo.get(s, OWNER, COUNTED))["open_lot_count"] == 5


async def test_multiple_properties_keep_failed_ids_until_every_property_succeeds(sc, monkeypatch):
    await sc.outbox.dispatch_pending()
    owner = sc.compiled.objects[OWNER].model_copy(deep=True)
    owner.spec.properties["other_count"] = owner.spec.properties["open_lot_count"].model_copy(deep=True)
    compiled = replace(
        sc.compiled, content_hash="derivation-multiple-test", objects={**sc.compiled.objects, OWNER: owner}
    )
    repo = ObjectRepository(compiled)
    async with sc.sessionmaker() as s:
        await repo.ensure(s)
        await s.commit()
    worker = DerivationWorker(compiled, repo, sc.functions, sc.sessionmaker)
    for oid in (OTHER, COUNTED):
        await worker.handle_event(OutboxRow(object_type=OWNER, object_id=oid, op="upsert"))

    calls = 0

    async def second_property_fails(session, fn, rows, params, **kwargs):
        nonlocal calls
        calls += 1
        return ["bad" if calls == 2 and row["version_id"] == OTHER else 3 for row in rows]

    monkeypatch.setattr(sc.functions, "map_rows", second_property_fails)
    await worker.drain()
    assert set(await pending(sc)) == {OTHER}
    await worker.drain()
    assert not await pending(sc)
    async with sc.sessionmaker() as s:
        row = await repo.get(s, OWNER, OTHER)
        assert row["open_lot_count"] == row["other_count"] == 3


async def test_nullable_result_clears_value_but_required_null_remains_pending(sc, monkeypatch):
    await sc.outbox.dispatch_pending()
    event = OutboxRow(object_type=OWNER, object_id=COUNTED, op="upsert")

    async def null_value(session, fn, rows, params, **kwargs):
        return [None for _ in rows]

    monkeypatch.setattr(sc.functions, "map_rows", null_value)
    await sc.derivation.handle_event(event)
    await sc.derivation.drain()
    assert not await pending(sc)
    async with sc.sessionmaker() as s:
        assert (await sc.repo.get(s, OWNER, COUNTED))["open_lot_count"] is None
    sc.compiled.objects[OWNER].spec.properties["open_lot_count"].required = True
    await sc.derivation.handle_event(event)
    await sc.derivation.drain()
    assert set(await pending(sc)) == {COUNTED}


async def test_queue_write_rolls_back_with_outbox_transaction(sc):
    await sc.outbox.dispatch_pending()
    async with sc.sessionmaker() as s:
        await sc.derivation.handle_event(OutboxRow(object_type=OWNER, object_id=COUNTED, op="upsert"), s)
        await s.rollback()
    assert not await pending(sc)
