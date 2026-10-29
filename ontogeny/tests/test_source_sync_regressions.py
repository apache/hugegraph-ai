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
# specific language governing permissions and
# limitations under the License.

"""Real SQLite regressions for tied watermarks and snapshot quarantine."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import select
from test_stores import NOW  # pytest fixture re-export
from test_stores import env as env

from ontogeny.action.models import OutboxRow
from ontogeny.core.models import SourceRef, StoreResource
from ontogeny.stores.sources import SqlSource
from ontogeny.stores.sync import QuarantineRow, SyncStateRow


def source_for(path):
    dsn = f"sqlite+aiosqlite:///{path}"
    store = StoreResource.model_validate(
        {
            "apiVersion": "ontogeny/v1",
            "kind": "Store",
            "metadata": {"name": "regression"},
            "spec": {"type": "sqlite", "connection": dsn},
        }
    )
    return SqlSource(store, dsn)


@pytest.mark.parametrize("primary_key", ["PRIMARY KEY (group_id, id)", "CHECK (id >= 0)"])
async def test_watermark_ties_cross_every_batch_without_omissions(tmp_path, primary_key):
    path = tmp_path / "source.db"
    # Composite keys and a source without a PK both drain equal watermarks.
    with sqlite3.connect(path) as db:
        db.execute(f"CREATE TABLE source (group_id TEXT, id INTEGER, wm INTEGER, {primary_key})")
        db.executemany(
            "INSERT INTO source VALUES (?, ?, ?)",
            [("B" if i % 2 else "A", i, 10 if i < 9 else 11) for i in reversed(range(13))],
        )
    source = source_for(path)
    try:
        for size in (1, 2, 3, 4, 9):
            rows = [
                row async for row in source.fetch(SourceRef(table="source"), watermark_col="wm", after=9, batch=size)
            ]
            assert len(rows) == 13
            assert {row["id"] for row in rows} == set(range(13))
            assert [row["wm"] for row in rows] == sorted(row["wm"] for row in rows)
            # Source PKs break ties, instead of depending on insertion order.
            assert [(row["wm"], row["group_id"], row["id"]) for row in rows] == sorted(
                (row["wm"], row["group_id"], row["id"]) for row in rows
            )
        replayed = [row async for row in source.fetch(SourceRef(table="source"), watermark_col="wm", after=11, batch=2)]
        assert {row["id"] for row in replayed} == {9, 10, 11, 12}
    finally:
        await source.dispose()


async def test_sync_checkpoints_only_after_entire_equal_watermark_group(env):
    with sqlite3.connect(env["src"]) as db:
        db.executemany(
            "INSERT INTO production_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(f"PO-TIE-{i:04d}", "P-100", 5, "PLANNED", "NORMAL", "2026-12-01", NOW, None, NOW) for i in range(1100)],
        )
    async with env["maker"]() as session:
        summary = await env["sync"].sync(session, "production-order")
        await session.commit()
        state = (await session.execute(select(SyncStateRow))).scalar_one()
        assert state.watermark == NOW
        assert len(await env["repo"].alive_ids(session, "production-order")) == 1102
    assert summary["inserted"] == 1102
    async with env["maker"]() as session:
        repeated = await env["sync"].sync(session, "production-order")
        await session.commit()
    # The scalar checkpoint deliberately replays its boundary; unchanged
    # objects remain at their original revision via idempotent upserts.
    assert repeated == {"inserted": 0, "updated": 0, "noop": 1102, "archived": 0, "quarantined": 0}
    with sqlite3.connect(env["src"]) as db:
        db.execute(
            "INSERT INTO production_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("PO-LATE", "P-100", 5, "PLANNED", "NORMAL", "2026-12-01", NOW, None, NOW),
        )
    async with env["maker"]() as session:
        late = await env["sync"].sync(session, "production-order")
        await session.commit()
        assert await env["repo"].get(session, "production-order", "PO-LATE") is not None
        unchanged = await env["repo"].get(session, "production-order", "PO-1")
        assert unchanged["_rev"] == 1
    assert late["inserted"] == 1 and late["noop"] == 1102


@pytest.mark.parametrize("mapped_key", [False, True])
async def test_snapshot_bad_update_preserves_last_good_object_but_archives_absent_row(env, mapped_key):
    if mapped_key:
        with sqlite3.connect(env["src"]) as db:
            db.execute("ALTER TABLE work_centers ADD COLUMN source_key TEXT")
            db.execute("UPDATE work_centers SET source_key=work_center_id")
        env["compiled"].objects["work-center"].spec.backing.mapping["work_center_id"] = "source_key"
    async with env["maker"]() as session:
        await env["sync"].sync(session, "work-center")
        await session.commit()
        original = await env["repo"].get(session, "work-center", "WC-01")
    with sqlite3.connect(env["src"]) as db:
        db.execute("UPDATE work_centers SET status='INVALID', name='must not land' WHERE work_center_id='WC-01'")
        db.execute("DELETE FROM work_centers WHERE work_center_id='WC-03'")
    async with env["maker"]() as session:
        summary = await env["sync"].sync(session, "work-center")
        await session.commit()
        preserved = await env["repo"].get(session, "work-center", "WC-01")
        alive = await env["repo"].alive_ids(session, "work-center")
        quarantined = (await session.execute(select(QuarantineRow))).scalars().all()
        archives = (await session.execute(select(OutboxRow).where(OutboxRow.op == "archive"))).scalars().all()
    assert summary["quarantined"] == 1
    assert summary["archived"] == 1
    assert preserved == original
    assert alive == {"WC-01", "WC-02"}
    assert [row.source_pk for row in quarantined] == ["WC-01"]
    assert [row.object_id for row in archives] == ["WC-03"]


async def test_snapshot_presence_uses_canonical_integer_key_when_other_fields_are_invalid(env):
    from ontogeny.core.models import ObjectTypeResource

    env["compiled"].objects["numeric-source"] = ObjectTypeResource.model_validate(
        {
            "apiVersion": "ontogeny/v1",
            "kind": "ObjectType",
            "metadata": {"name": "numeric-source"},
            "spec": {
                "primaryKey": ["id"],
                "properties": {"id": {"type": "integer", "required": True}, "count": {"type": "integer"}},
                "backing": {
                    "store": "mes",
                    "source": {"table": "numeric_input"},
                    "mapping": {"id": "source_key"},
                    "sync": {"strategy": "snapshot"},
                },
            },
        }
    )
    with sqlite3.connect(env["src"]) as db:
        db.execute("CREATE TABLE numeric_input (source_key TEXT PRIMARY KEY, count TEXT)")
        db.executemany("INSERT INTO numeric_input VALUES (?, ?)", [("001", "7"), ("002", "8")])
    async with env["maker"]() as session:
        await env["repo"].ensure(session)
        first = await env["sync"].sync(session, "numeric-source")
        await session.commit()
    assert first["inserted"] == 2 and first["archived"] == 0
    with sqlite3.connect(env["src"]) as db:
        db.execute("UPDATE numeric_input SET count='invalid' WHERE source_key='001'")
    async with env["maker"]() as session:
        summary = await env["sync"].sync(session, "numeric-source")
        await session.commit()
        preserved = await env["repo"].get(session, "numeric-source", "1")
        alive = await env["repo"].alive_ids(session, "numeric-source")
    assert summary["quarantined"] == 1 and summary["archived"] == 0
    assert preserved["count"] == 7 and preserved["_rev"] == 1
    assert alive == {1, 2}
