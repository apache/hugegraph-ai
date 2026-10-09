# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
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

SRC_ROWS_WORK_CENTERS = [
    ("WC-01", "CNC Machining Cell", "machining", "plant-north", 400, 2, "ACTIVE", "2023-11-01T08:00:00+00:00", NOW),
    ("WC-02", "Final Assembly Line", "assembly", "plant-north", 300, 2, "ACTIVE", "2023-11-01T08:00:00+00:00", NOW),
    ("WC-03", "Quality Inspection Bench", "quality", "plant-north", 200, 1, "IDLE", "2023-11-01T08:00:00+00:00", NOW),
]

SRC_ROWS_PRODUCTION_ORDERS = [
    ("PO-1", "P-100", 5, "PLANNED", "NORMAL", "2026-12-01", NOW, None, NOW),
    ("PO-2", "P-100", 8, "RELEASED", "HIGH", "2026-11-15", NOW, NOW, NOW),
]

SRC_ROWS_MATERIALS = [
    ("M-1", "Steel Plate S45C", "sheet", "210.00", 48, 20, 14, "2024-01-20T08:00:00+00:00", NOW),
    ("M-2", "Precision Bearing", "pcs", "320.00", 9, 40, 30, "2024-02-01T08:00:00+00:00", NOW),
]

SRC_ROWS_OPERATIONS = [
    ("OP-1", "PO-1", 10, "Plate Cutting", "WC-01", "QUEUED", 120, None, NOW),
    ("OP-2", "PO-2", 10, "Kitting", "WC-02", "RUNNING", 30, None, NOW),
]


def _make_source_db(path) -> None:
    """A private MES source in the shape the golden package's stores declare."""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE work_centers (
            work_center_id TEXT PRIMARY KEY, name TEXT, process TEXT, site TEXT,
            capacity_per_shift INTEGER, shifts_per_day INTEGER, status TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE production_orders (
            order_id TEXT PRIMARY KEY, product_id TEXT NOT NULL, qty INTEGER,
            status TEXT, priority TEXT, due_date TEXT, created_at TEXT,
            released_at TEXT, updated_at TEXT
        );
        CREATE TABLE materials (
            material_id TEXT PRIMARY KEY, name TEXT NOT NULL, unit TEXT,
            unit_cost TEXT, stock_qty INTEGER, safety_stock INTEGER,
            lead_time_days INTEGER, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE operations (
            operation_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, seq INTEGER,
            name TEXT NOT NULL, work_center_id TEXT, status TEXT,
            standard_minutes INTEGER, completed_at TEXT, updated_at TEXT
        );
        CREATE TABLE work_center_materials (wc_id TEXT, material_id TEXT);
        """
    )
    con.executemany("INSERT INTO work_centers VALUES (?,?,?,?,?,?,?,?,?)", SRC_ROWS_WORK_CENTERS)
    con.executemany("INSERT INTO production_orders VALUES (?,?,?,?,?,?,?,?,?)", SRC_ROWS_PRODUCTION_ORDERS)
    con.executemany("INSERT INTO materials VALUES (?,?,?,?,?,?,?,?,?)", SRC_ROWS_MATERIALS)
    con.executemany("INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?)", SRC_ROWS_OPERATIONS)
    con.commit()
    con.close()


def _package_copy(golden_pkg_path, root) -> object:
    """The golden package on a temp dir, with two test-only shapes:

    - work-center reverts to snapshot sync (the seeded package watermarks every
      object, and absent-means-archive is a snapshot-strategy semantic);
    - a many-to-many work-center-materials link joins the two via a relation
      table, the join-table shape the domain otherwise expresses through the
      bridging `bom` object.
    """
    import shutil

    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(golden_pkg_path, root)

    wc_file = root / "objects" / "work-center.yaml"
    doc = yaml.safe_load(wc_file.read_text(encoding="utf-8"))
    doc["spec"]["backing"].pop("sync", None)
    wc_file.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    (root / "links" / "work-center-materials.yaml").write_text(
        "apiVersion: ontogeny/v1\n"
        "kind: LinkType\n"
        "metadata:\n"
        "  name: work-center-materials\n"
        "spec:\n"
        "  source: work-center\n"
        "  target: material\n"
        "  cardinality: MANY_TO_MANY\n"
        "  join:\n"
        "    kind: join-table\n"
        "    store: mes\n"
        "    relation:\n"
        "      schema: mes\n"
        "      table: work_center_materials\n"
        "    keys:\n"
        "      source:\n"
        "        work_center_id: wc_id\n"
        "      target:\n"
        "        material_id: material_id\n",
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
        compiled, settings, repo,
        lambda store: make_source(store, settings.resolve_env_ref(store.spec.connection)),
    )
    yield {"maker": maker, "compiled": compiled, "repo": repo, "sync": sync, "src": str(src), "settings": settings}
    await engine.dispose()


class TestSync:
    async def test_snapshot_loads_all_objects(self, env):
        async with env["maker"]() as s:
            summary = await env["sync"].sync(s, "work-center")
            await env["sync"].sync(s, "production-order")
            await env["sync"].sync(s, "material")
            await s.commit()
        assert summary == {"inserted": 3, "updated": 0, "noop": 0, "archived": 0, "quarantined": 0}

        repo = env["repo"]
        async with env["maker"]() as s:
            rows, total = await repo.query(s, "work-center")
            assert total == 3
            assert rows[0]["name"] in {"CNC Machining Cell", "Final Assembly Line", "Quality Inspection Bench"}

            po, _ = await repo.query(s, "production-order", filt={"field": "status", "op": "eq", "value": "PLANNED"})
            assert [r["order_id"] for r in po] == ["PO-1"]
            assert isinstance(po[0]["due_date"], dt.date)

    async def test_enum_domain_violation_quarantined(self, env):
        con = sqlite3.connect(env["src"])
        con.execute(
            "INSERT INTO work_centers VALUES ('WC-9','Bad','machining','plant-north',1,1,'EXPLODED','2020-01-01',?)",
            (NOW,),
        )
        con.commit()
        con.close()
        async with env["maker"]() as s:
            summary = await env["sync"].sync(s, "work-center")
            await s.commit()
            quarantined = (await s.execute(select(QuarantineRow))).scalars().all()
        assert summary["quarantined"] == 1
        assert summary["inserted"] == 3  # good rows still land; bad row isolated
        assert quarantined[0].code == "TYPE_MISMATCH"

    async def test_ownership_blocks_sync_overwrite(self, env):
        async with env["maker"]() as s:
            await env["sync"].sync(s, "production-order")
            await s.commit()
        # source backdates a release (ontology-owned released_at: not
        # overwritable by sync); source-owned columns are left untouched
        con = sqlite3.connect(env["src"])
        con.execute(
            "UPDATE production_orders SET released_at='2026-09-18T09:00:00+00:00',"
            " updated_at='2026-09-18T09:00:00+00:00' WHERE order_id='PO-1'"
        )
        con.commit()
        con.close()
        async with env["maker"]() as s:
            await env["sync"].sync(s, "production-order")
            await s.commit()
            row = await env["repo"].get(s, "production-order", "PO-1")
        assert row["released_at"] is None        # ontology-owned: sync never overwrites
        assert row["product_id"] == "P-100"      # source-owned still intact

    async def test_source_owned_updates_do_flow(self, env):
        async with env["maker"]() as s:
            await env["sync"].sync(s, "work-center")
            await s.commit()
        con = sqlite3.connect(env["src"])
        con.execute("UPDATE work_centers SET name='CNC Machining Cell II' WHERE work_center_id='WC-01'")
        con.commit()
        con.close()
        async with env["maker"]() as s:
            summary = await env["sync"].sync(s, "work-center")
            await s.commit()
            row = await env["repo"].get(s, "work-center", "WC-01")
        assert summary["updated"] == 1
        assert row["name"] == "CNC Machining Cell II" and row["_rev"] == 2

    async def test_absent_means_archive(self, env):
        async with env["maker"]() as s:
            await env["sync"].sync(s, "work-center")
            await s.commit()
        con = sqlite3.connect(env["src"])
        con.execute("DELETE FROM work_centers WHERE work_center_id='WC-03'")
        con.commit()
        con.close()
        async with env["maker"]() as s:
            summary = await env["sync"].sync(s, "work-center")
            await s.commit()
            rows, total = await env["repo"].query(s, "work-center")
        assert summary["archived"] == 1 and total == 2

    async def test_watermark_incremental(self, env):
        async with env["maker"]() as s:
            await env["sync"].sync(s, "production-order")
            await s.commit()
        con = sqlite3.connect(env["src"])
        # status is ontology-owned -> source change must NOT flow (ownership!)
        con.execute(
            "UPDATE production_orders SET status='CANCELLED', updated_at='2026-09-18T10:00:00+00:00'"
            " WHERE order_id='PO-2'"
        )
        con.execute(
            "INSERT INTO production_orders VALUES ('PO-3','P-200',12,'PLANNED','LOW','2026-12-20',"
            "'2026-09-18T10:30:00+00:00',NULL,'2026-09-18T10:30:00+00:00')"
        )
        con.commit()
        con.close()
        async with env["maker"]() as s:
            summary = await env["sync"].sync(s, "production-order")
            await s.commit()
            state = (await s.execute(select(SyncStateRow))).scalar_one()
        # the new row PO-3 inserts; PO-2 becomes a no-op
        assert summary == {"inserted": 1, "updated": 0, "noop": 1, "archived": 0, "quarantined": 0}
        assert state.watermark is not None

    async def test_sync_writes_outbox(self, env):
        from ontogeny.action.models import OutboxRow

        async with env["maker"]() as s:
            await env["sync"].sync(s, "work-center")
            await s.commit()
            events = (await s.execute(select(OutboxRow))).scalars().all()
        assert len(events) == 3 and all(e.op == "upsert" for e in events)


class TestRepository:
    async def test_versioning_and_history(self, env):
        repo = env["repo"]
        async with env["maker"]() as s:
            await env["sync"].sync(s, "work-center")
            await s.commit()
        ts = dt.datetime.now(dt.timezone.utc)
        async with env["maker"]() as s:
            new = await repo.action_update(s, "work-center", "WC-01", {"name": "Serviced"}, ts)
            await s.commit()
            hist = await repo.history(s, "work-center", "WC-01")
        assert new["_rev"] == 2
        assert [h["_rev"] for h in hist] == [1, 2]
        assert hist[0]["_valid_to"] is not None

    async def test_optimistic_lock_conflict(self, env):
        repo = env["repo"]
        async with env["maker"]() as s:
            await env["sync"].sync(s, "work-center")
            await s.commit()
        ts = dt.datetime.now(dt.timezone.utc)
        from ontogeny.errors import ConflictError

        async with env["maker"]() as s:
            with pytest.raises(ConflictError):
                await repo.action_update(s, "work-center", "WC-01", {"name": "A"}, ts, expected_revision=99)

    async def test_time_travel_get(self, env):
        repo = env["repo"]
        async with env["maker"]() as s:
            await env["sync"].sync(s, "work-center")
            await s.commit()
        t0 = dt.datetime.now(dt.timezone.utc)  # after sync: version 1 is current
        import asyncio

        await asyncio.sleep(0.002)  # ensure strictly increasing version timestamps
        t1 = dt.datetime.now(dt.timezone.utc)
        async with env["maker"]() as s:
            await repo.action_update(s, "work-center", "WC-01", {"name": "Renamed"}, t1)
            await s.commit()
        async with env["maker"]() as s:
            before = await repo.get(s, "work-center", "WC-01", at=t0)
            after = await repo.get(s, "work-center", "WC-01", at=t1)
        assert before["name"] == "CNC Machining Cell"
        assert after["name"] == "Renamed"

    async def test_join_table_links(self, env):
        repo = env["repo"]
        ts = dt.datetime.now(dt.timezone.utc)
        async with env["maker"]() as s:
            await repo.link_add(s, "work-center-materials", "WC-01", "M-1", ts)
            await repo.link_add(s, "work-center-materials", "WC-01", "M-9", ts)  # not exists yet, link table allows
            await repo.link_remove(s, "work-center-materials", "WC-01", "M-9", ts)
            await s.commit()
            members = await repo.link_members(s, "work-center-materials", src_id="WC-01")
        assert members == [("WC-01", "M-1")]

    async def test_join_table_readd_after_remove(self, env):
        """link_add -> link_remove -> link_add used to die on the (src, dst)-only
        primary key colliding with the soft-closed row."""
        repo = env["repo"]
        t0 = dt.datetime.now(dt.timezone.utc)
        t1 = t0 + dt.timedelta(microseconds=10)
        t2 = t0 + dt.timedelta(microseconds=20)
        async with env["maker"]() as s:
            await repo.link_add(s, "work-center-materials", "WC-01", "M-2", t0)
            await repo.link_remove(s, "work-center-materials", "WC-01", "M-2", t1)
            await repo.link_add(s, "work-center-materials", "WC-01", "M-2", t2)
            await s.commit()
            members = await repo.link_members(s, "work-center-materials", src_id="WC-01")
        assert ("WC-01", "M-2") in members

    async def test_fk_link_traversal(self, env):
        repo = env["repo"]
        async with env["maker"]() as s:
            await env["sync"].sync(s, "operation")
            await s.commit()
            ops_from_work_center = await repo.fk_linked_ids(s, "operation-work-center", "WC-01", from_source=True)
            wc_from_op = await repo.fk_linked_ids(s, "operation-work-center", "OP-1", from_source=False)
        assert ops_from_work_center == ["OP-1"]
        assert wc_from_op == ["WC-01"]
