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

"""Data plane: DDL, versioned repository, sync engine semantics."""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest
import pytest_asyncio
import yaml
from sqlalchemy import select

from ontogeny.config import Settings
from ontogeny.core import load_package
from ontogeny.db import init_schema, make_engine, make_sessionmaker
from ontogeny.registry import RegistryService
from ontogeny.stores import ObjectRepository, SyncEngine
from ontogeny.stores.sources import make_source
from ontogeny.stores.sync import QuarantineRow, SyncStateRow

NOW = "2026-09-18T08:00:00+00:00"

SRC_ROWS_EQUIPMENT = [
    ("EQ-01", "Scanner A (193i)", "lithography", "fab-site-a", "ACTIVE", "2024-03-01T08:00:00+00:00", NOW),
    ("EQ-02", "Etcher 1 (ICP)", "etch", "fab-site-a", "ACTIVE", "2024-05-10T08:00:00+00:00", NOW),
    ("EQ-03", "CVD Chamber 1", "deposition", "fab-site-a", "ACTIVE", "2024-05-10T08:00:00+00:00", NOW),
]

SRC_ROWS_WAFER_LOTS = [
    ("LOT-1", "TO-A0", 5, None, "fab-site-a", "2026-09-10T08:00:00+00:00", NOW, NOW),
    ("LOT-2", "TO-A0", 8, None, "fab-site-b", "2026-09-11T08:00:00+00:00", NOW, NOW),
]

SRC_ROWS_TAPEOUT_VERSIONS = [
    ("TO-A0", "X1", "FAB", "First cut", "1850000.00", "2026-06-10T08:00:00+00:00", NOW, NOW),
]

SRC_ROWS_PROCESS_STEPS = [
    ("PS-1", "LOT-1", 10, "Etch", "EQ-02", "QUEUED", None, NOW),
]


def _make_source_db(path) -> None:
    """A private fab source in the shape the golden package's stores declare."""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE equipment (
            equipment_id TEXT PRIMARY KEY, name TEXT, process TEXT, site TEXT,
            status TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE wafer_lots (
            lot_id TEXT PRIMARY KEY, version_id TEXT NOT NULL, qty_wafers INTEGER,
            status TEXT, site TEXT, started_at TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE tapeout_versions (
            version_id TEXT PRIMARY KEY, project TEXT NOT NULL, status TEXT, notes TEXT,
            mask_cost TEXT, taped_out_at TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE process_steps (
            step_id TEXT PRIMARY KEY, lot_id TEXT NOT NULL, seq INTEGER,
            name TEXT NOT NULL, equipment TEXT, status TEXT, completed_at TEXT, updated_at TEXT
        );
        CREATE TABLE equipment_lots (equipment_id TEXT, lot_id TEXT);
        """
    )
    con.executemany("INSERT INTO equipment VALUES (?,?,?,?,?,?,?)", SRC_ROWS_EQUIPMENT)
    con.executemany("INSERT INTO wafer_lots VALUES (?,?,?,?,?,?,?,?)", SRC_ROWS_WAFER_LOTS)
    con.executemany("INSERT INTO tapeout_versions VALUES (?,?,?,?,?,?,?,?)", SRC_ROWS_TAPEOUT_VERSIONS)
    con.executemany("INSERT INTO process_steps VALUES (?,?,?,?,?,?,?,?)", SRC_ROWS_PROCESS_STEPS)
    con.commit()
    con.close()


def _package_copy(golden_pkg_path, root) -> object:
    """The golden package on a temp dir, with two test-only shapes:

    - equipment reverts to snapshot sync (the seeded package watermarks every
      object, and absent-means-archive is a snapshot-strategy semantic);
    - a many-to-many equipment-lots link joins the two via a relation
      table, the join-table shape the domain otherwise expresses through the
      bridging `design-module` object.
    """
    import shutil

    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(golden_pkg_path, root)

    eq_file = root / "objects" / "equipment.yaml"
    doc = yaml.safe_load(eq_file.read_text(encoding="utf-8"))
    doc["spec"]["backing"].pop("sync", None)
    eq_file.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    (root / "links" / "equipment-lots.yaml").write_text(
        "apiVersion: ontogeny/v1\n"
        "kind: LinkType\n"
        "metadata:\n"
        "  name: equipment-lots\n"
        "spec:\n"
        "  source: equipment\n"
        "  target: wafer-lot\n"
        "  cardinality: MANY_TO_MANY\n"
        "  join:\n"
        "    kind: join-table\n"
        "    store: fab\n"
        "    relation:\n"
        "      schema: fab\n"
        "      table: equipment_lots\n"
        "    keys:\n"
        "      source:\n"
        "        equipment_id: equipment_id\n"
        "      target:\n"
        "        lot_id: lot_id\n",
        encoding="utf-8",
    )
    return root


@pytest_asyncio.fixture()
async def env(golden_pkg_path, tmp_path):
    src = tmp_path / "erp.db"
    _make_source_db(str(src))
    settings = Settings(env={"ERP_DSN": f"sqlite+aiosqlite:///{src}"})
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    maker = make_sessionmaker(engine)
    pkg = load_package(_package_copy(golden_pkg_path, tmp_path / "pkg"))
    async with maker() as s:
        compiled = await RegistryService().publish(s, pkg)
        await s.commit()
    repo = ObjectRepository(compiled)
    async with maker() as s:
        await repo.ensure(s)
        await s.commit()
    sync = SyncEngine(
        compiled,
        settings,
        repo,
        lambda store: make_source(store, settings.resolve_env_ref(store.spec.connection)),
    )
    yield {"maker": maker, "compiled": compiled, "repo": repo, "sync": sync, "src": str(src), "settings": settings}
    await engine.dispose()


class TestSync:
    async def test_snapshot_loads_all_objects(self, env):
        async with env["maker"]() as s:
            summary = await env["sync"].sync(s, "equipment")
            await env["sync"].sync(s, "wafer-lot")
            await env["sync"].sync(s, "tapeout-version")
            await s.commit()
        assert summary == {"inserted": 3, "updated": 0, "noop": 0, "archived": 0, "quarantined": 0}

        repo = env["repo"]
        async with env["maker"]() as s:
            rows, total = await repo.query(s, "equipment")
            assert total == 3
            assert rows[0]["name"] in {"Scanner A (193i)", "Etcher 1 (ICP)", "CVD Chamber 1"}

            lots, _ = await repo.query(s, "wafer-lot", filt={"field": "site", "op": "eq", "value": "fab-site-a"})
            assert [r["lot_id"] for r in lots] == ["LOT-1"]
            assert isinstance(lots[0]["started_at"], dt.datetime)

    async def test_enum_domain_violation_quarantined(self, env):
        con = sqlite3.connect(env["src"])
        con.execute(
            "INSERT INTO equipment VALUES ('EQ-9','Bad','etch','fab-site-a','EXPLODED','2020-01-01',?)",
            (NOW,),
        )
        con.commit()
        con.close()
        async with env["maker"]() as s:
            summary = await env["sync"].sync(s, "equipment")
            await s.commit()
            quarantined = (await s.execute(select(QuarantineRow))).scalars().all()
        assert summary["quarantined"] == 1
        assert summary["inserted"] == 3  # good rows still land; bad row isolated
        assert quarantined[0].code == "TYPE_MISMATCH"

    async def test_ownership_blocks_sync_overwrite(self, env):
        async with env["maker"]() as s:
            await env["sync"].sync(s, "wafer-lot")
            await s.commit()
        # source backdates a hold (ontology-owned status: not
        # overwritable by sync); source-owned columns are left untouched
        con = sqlite3.connect(env["src"])
        con.execute(
            "UPDATE wafer_lots SET status='ON_HOLD', updated_at='2026-09-18T09:00:00+00:00' WHERE lot_id='LOT-1'"
        )
        con.commit()
        con.close()
        async with env["maker"]() as s:
            await env["sync"].sync(s, "wafer-lot")
            await s.commit()
            row = await env["repo"].get(s, "wafer-lot", "LOT-1")
        assert row["status"] is None  # ontology-owned: sync never overwrites
        assert row["version_id"] == "TO-A0"  # source-owned still intact

    async def test_source_owned_updates_do_flow(self, env):
        async with env["maker"]() as s:
            await env["sync"].sync(s, "equipment")
            await s.commit()
        con = sqlite3.connect(env["src"])
        con.execute("UPDATE equipment SET name='Scanner A (193i) DXb' WHERE equipment_id='EQ-01'")
        con.commit()
        con.close()
        async with env["maker"]() as s:
            summary = await env["sync"].sync(s, "equipment")
            await s.commit()
            row = await env["repo"].get(s, "equipment", "EQ-01")
        assert summary["updated"] == 1
        assert row["name"] == "Scanner A (193i) DXb" and row["_rev"] == 2

    async def test_absent_means_archive(self, env):
        async with env["maker"]() as s:
            await env["sync"].sync(s, "equipment")
            await s.commit()
        con = sqlite3.connect(env["src"])
        con.execute("DELETE FROM equipment WHERE equipment_id='EQ-03'")
        con.commit()
        con.close()
        async with env["maker"]() as s:
            summary = await env["sync"].sync(s, "equipment")
            await s.commit()
            _rows, total = await env["repo"].query(s, "equipment")
        assert summary["archived"] == 1 and total == 2

    async def test_watermark_incremental(self, env):
        async with env["maker"]() as s:
            await env["sync"].sync(s, "wafer-lot")
            await s.commit()
        con = sqlite3.connect(env["src"])
        # status is ontology-owned -> source change must NOT flow (ownership!)
        con.execute(
            "UPDATE wafer_lots SET status='COMPLETE', updated_at='2026-09-18T10:00:00+00:00' WHERE lot_id='LOT-2'"
        )
        con.execute(
            "INSERT INTO wafer_lots VALUES ('LOT-3','TO-A0',12,NULL,'fab-site-a',"
            "'2026-09-18T10:30:00+00:00','2026-09-18T10:30:00+00:00','2026-09-18T10:30:00+00:00')"
        )
        con.commit()
        con.close()
        async with env["maker"]() as s:
            summary = await env["sync"].sync(s, "wafer-lot")
            await s.commit()
            state = (await s.execute(select(SyncStateRow))).scalar_one()
        # LOT-3 inserts; LOT-2 and the replayed checkpoint-boundary LOT-1 are no-ops.
        assert summary == {"inserted": 1, "updated": 0, "noop": 2, "archived": 0, "quarantined": 0}
        assert state.watermark is not None

    async def test_sync_writes_outbox(self, env):
        from ontogeny.action.models import OutboxRow

        async with env["maker"]() as s:
            await env["sync"].sync(s, "equipment")
            await s.commit()
            events = (await s.execute(select(OutboxRow))).scalars().all()
        assert len(events) == 3 and all(e.op == "upsert" for e in events)


class TestRepository:
    async def test_versioning_and_history(self, env):
        repo = env["repo"]
        async with env["maker"]() as s:
            await env["sync"].sync(s, "equipment")
            await s.commit()
        ts = dt.datetime.now(dt.UTC)
        async with env["maker"]() as s:
            new = await repo.action_update(s, "equipment", "EQ-01", {"name": "Serviced"}, ts)
            await s.commit()
            hist = await repo.history(s, "equipment", "EQ-01")
        assert new["_rev"] == 2
        assert [h["_rev"] for h in hist] == [1, 2]
        assert hist[0]["_valid_to"] is not None

    async def test_optimistic_lock_conflict(self, env):
        repo = env["repo"]
        async with env["maker"]() as s:
            await env["sync"].sync(s, "equipment")
            await s.commit()
        ts = dt.datetime.now(dt.UTC)
        from ontogeny.errors import ConflictError

        async with env["maker"]() as s:
            with pytest.raises(ConflictError):
                await repo.action_update(s, "equipment", "EQ-01", {"name": "A"}, ts, expected_revision=99)

    async def test_time_travel_get(self, env):
        repo = env["repo"]
        async with env["maker"]() as s:
            await env["sync"].sync(s, "equipment")
            await s.commit()
        t0 = dt.datetime.now(dt.UTC)  # after sync: version 1 is current
        import asyncio

        await asyncio.sleep(0.002)  # ensure strictly increasing version timestamps
        t1 = dt.datetime.now(dt.UTC)
        async with env["maker"]() as s:
            await repo.action_update(s, "equipment", "EQ-01", {"name": "Renamed"}, t1)
            await s.commit()
        async with env["maker"]() as s:
            before = await repo.get(s, "equipment", "EQ-01", at=t0)
            after = await repo.get(s, "equipment", "EQ-01", at=t1)
        assert before["name"] == "Scanner A (193i)"
        assert after["name"] == "Renamed"

    async def test_join_table_links(self, env):
        repo = env["repo"]
        ts = dt.datetime.now(dt.UTC)
        async with env["maker"]() as s:
            await repo.link_add(s, "equipment-lots", "EQ-01", "LOT-1", ts)
            await repo.link_add(s, "equipment-lots", "EQ-01", "LOT-9", ts)  # not exists yet, link table allows
            await repo.link_remove(s, "equipment-lots", "EQ-01", "LOT-9", ts)
            await s.commit()
            members = await repo.link_members(s, "equipment-lots", src_id="EQ-01")
        assert members == [("EQ-01", "LOT-1")]

    async def test_join_table_readd_after_remove(self, env):
        """link_add -> link_remove -> link_add used to die on the (src, dst)-only
        primary key colliding with the soft-closed row."""
        repo = env["repo"]
        t0 = dt.datetime.now(dt.UTC)
        t1 = t0 + dt.timedelta(microseconds=10)
        t2 = t0 + dt.timedelta(microseconds=20)
        async with env["maker"]() as s:
            await repo.link_add(s, "equipment-lots", "EQ-01", "LOT-2", t0)
            await repo.link_remove(s, "equipment-lots", "EQ-01", "LOT-2", t1)
            await repo.link_add(s, "equipment-lots", "EQ-01", "LOT-2", t2)
            await s.commit()
            members = await repo.link_members(s, "equipment-lots", src_id="EQ-01")
        assert ("EQ-01", "LOT-2") in members

    async def test_fk_link_traversal(self, env):
        repo = env["repo"]
        async with env["maker"]() as s:
            await env["sync"].sync(s, "process-step")
            await s.commit()
            steps_from_equipment = await repo.fk_linked_ids(s, "step-equipment", "EQ-02", from_source=True)
            equipment_from_step = await repo.fk_linked_ids(s, "step-equipment", "PS-1", from_source=False)
        assert steps_from_equipment == ["PS-1"]
        assert equipment_from_step == ["EQ-02"]
