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
            "INSERT INTO wafer_lots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(f"LOT-TIE-{i:04d}", "TO-A0", 5, None, "fab-site-a", None, NOW, NOW) for i in range(1100)],
        )
    async with env["maker"]() as session:
        summary = await env["sync"].sync(session, "wafer-lot")
        await session.commit()
        state = (await session.execute(select(SyncStateRow))).scalar_one()
        assert state.watermark == NOW
        assert len(await env["repo"].alive_ids(session, "wafer-lot")) == 1102
    assert summary["inserted"] == 1102
    async with env["maker"]() as session:
        repeated = await env["sync"].sync(session, "wafer-lot")
        await session.commit()
    # The scalar checkpoint deliberately replays its boundary; unchanged
    # objects remain at their original revision via idempotent upserts.
    assert repeated == {"inserted": 0, "updated": 0, "noop": 1102, "archived": 0, "quarantined": 0}
    with sqlite3.connect(env["src"]) as db:
        db.execute(
            "INSERT INTO wafer_lots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("LOT-LATE", "TO-A0", 5, None, "fab-site-a", None, NOW, NOW),
        )
    async with env["maker"]() as session:
        late = await env["sync"].sync(session, "wafer-lot")
        await session.commit()
        assert await env["repo"].get(session, "wafer-lot", "LOT-LATE") is not None
        unchanged = await env["repo"].get(session, "wafer-lot", "LOT-1")
        assert unchanged["_rev"] == 1
    assert late["inserted"] == 1 and late["noop"] == 1102


@pytest.mark.parametrize("mapped_key", [False, True])
async def test_snapshot_bad_update_preserves_last_good_object_but_archives_absent_row(env, mapped_key):
    if mapped_key:
        with sqlite3.connect(env["src"]) as db:
            db.execute("ALTER TABLE equipment ADD COLUMN source_key TEXT")
            db.execute("UPDATE equipment SET source_key=equipment_id")
        env["compiled"].objects["equipment"].spec.backing.mapping["equipment_id"] = "source_key"
    async with env["maker"]() as session:
        await env["sync"].sync(session, "equipment")
        await session.commit()
        original = await env["repo"].get(session, "equipment", "EQ-01")
    with sqlite3.connect(env["src"]) as db:
        db.execute("UPDATE equipment SET status='INVALID', name='must not land' WHERE equipment_id='EQ-01'")
        db.execute("DELETE FROM equipment WHERE equipment_id='EQ-03'")
    async with env["maker"]() as session:
        summary = await env["sync"].sync(session, "equipment")
        await session.commit()
        preserved = await env["repo"].get(session, "equipment", "EQ-01")
        alive = await env["repo"].alive_ids(session, "equipment")
        quarantined = (await session.execute(select(QuarantineRow))).scalars().all()
        archives = (await session.execute(select(OutboxRow).where(OutboxRow.op == "archive"))).scalars().all()
    assert summary["quarantined"] == 1
    assert summary["archived"] == 1
    assert preserved == original
    assert alive == {"EQ-01", "EQ-02"}
    assert [row.source_pk for row in quarantined] == ["EQ-01"]
    assert [row.object_id for row in archives] == ["EQ-03"]


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
                    "store": "fab",
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
