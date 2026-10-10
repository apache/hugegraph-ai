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
"""Schema-evolution regressions found while running a second package.

Two failures that only appear in a long-lived process:
1. the DDL cache was keyed by table name alone, so a second ontology (or a
   republished one) that reuses a table name with different columns silently
   got the wrong Table object;
2. the evolution loop could merge a new property (T0) but the object table was
   never altered, leaving the promoted schema unqueryable.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest_asyncio
from sqlalchemy import inspect

from ontogeny.config import Settings
from ontogeny.core import load_package
from ontogeny.demo import prepare_demo
from ontogeny.service import ServiceContext
from ontogeny.stores.ddl import object_table

REPO = Path(__file__).resolve().parent.parent

# A minimal second package whose `work-center` maps the same source table the
# golden one does, but declares a different ontology-owned column set -- exactly
# the collision shape the DDL cache used to get wrong.
INLINE_PKG_OBJECTS = """
apiVersion: ontogeny/v1
kind: ObjectType
metadata:
  name: work-center
  display: Work centre (lean variant)
spec:
  primaryKey:
  - work_center_id
  properties:
    work_center_id:
      type: string
      display: Work centre ID
      required: true
    name:
      type: string
      display: Name
      required: true
    region:
      type: string
      display: Region
    headcount:
      type: integer
      display: Headcount
  backing:
    store: mes
    mode: materialized
    source:
      schema: mes
      table: work_centers
    mapping: {}
"""

INLINE_PKG_SEED = """
CREATE TABLE work_centers (
    work_center_id TEXT PRIMARY KEY, name TEXT NOT NULL, region TEXT,
    headcount INTEGER, updated_at TEXT
);
INSERT INTO work_centers VALUES
 ('WC-01','Welding Cell','plant-south',12,'2026-09-18T08:00:00+00:00');
"""


def _write_inline_package(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "objects").mkdir(exist_ok=True)
    (root / "stores").mkdir(exist_ok=True)
    (root / "seed").mkdir(exist_ok=True)
    (root / "ontology.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: Ontology\nmetadata:\n  name: work-center-lean\n"
        "  display: Lean work-centre package\nspec:\n  imports: []\n",
        encoding="utf-8",
    )
    (root / "stores" / "mes.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: Store\nmetadata:\n  name: mes\nspec:\n"
        "  type: sqlite\n  connection: ${ERP_DSN}\n  access: read-write\n",
        encoding="utf-8",
    )
    (root / "objects" / "work-center.yaml").write_text(INLINE_PKG_OBJECTS, encoding="utf-8")
    (root / "seed" / "01_source.sql").write_text(INLINE_PKG_SEED, encoding="utf-8")
    return root


class TestNoCrossPackageDdlCollision:
    def test_same_table_name_different_columns_stay_independent(self, tmp_path, golden_pkg_path):
        golden = load_package(golden_pkg_path)
        lean = load_package(_write_inline_package(tmp_path / "lean"))
        from ontogeny.registry import compile_package

        a = compile_package(golden)
        b = compile_package(lean)
        assert a.content_hash != b.content_hash

        ta = object_table(a, "work-center")
        tb = object_table(b, "work-center")
        assert ta.name == tb.name == "ontogeny_obj_work_center"
        # the golden package has `capacity_per_shift`; the lean one has headcount
        assert "capacity_per_shift" in ta.columns
        assert "headcount" in tb.columns
        assert "capacity_per_shift" not in tb.columns

    @pytest_asyncio.fixture()
    async def both_packages(self, tmp_path, golden_pkg_path):
        """Boot the golden package, then the lean one, in the same process."""
        ctxs = []
        lean = _write_inline_package(tmp_path / "lean-pkg")
        for i, pkg in enumerate((golden_pkg_path, lean)):
            paths = prepare_demo(tmp_path / f"demo{i}", package=pkg)
            env = paths.as_env()
            ctx = ServiceContext(Settings(db_dsn=env["ONTOGENY_DB_DSN"], env=env), env["ONTOGENY_PACKAGE_ROOT"])
            await ctx.initialize()
            for object_type in ctx.compiled.objects:
                await ctx.sync(object_type)
            ctxs.append(ctx)
        yield ctxs
        for ctx in ctxs:
            await ctx.engine.dispose()

    async def test_second_package_writes_its_own_columns(self, both_packages):
        golden, lean = both_packages
        async with lean.sessionmaker() as s:
            row = await lean.repo.get(s, "work-center", "WC-01")
        assert row["headcount"] == 12
        async with golden.sessionmaker() as s:
            row = await golden.repo.get(s, "work-center", "WC-01")
        assert row["capacity_per_shift"] == 400  # golden-only column still writable


class TestAdditiveMigration:
    async def test_promoted_property_becomes_queryable(self, tmp_path, golden_pkg_path):
        """T0 auto-merge adds a property -> the column must appear and be usable."""
        from ontogeny.evolve import Promoter, ProposalRow

        paths = prepare_demo(tmp_path / "demo", package=golden_pkg_path)
        env = paths.as_env()
        sc = ServiceContext(Settings(db_dsn=env["ONTOGENY_DB_DSN"], env=env), env["ONTOGENY_PACKAGE_ROOT"])
        await sc.initialize()
        for object_type in sc.compiled.objects:
            await sc.sync(object_type)

        async with sc.sessionmaker() as s:
            proposal = ProposalRow(
                gap_kind="add-optional-property", rationale="planners filter by shift pattern",
                diff=[{"mutation": "add-optional-property", "object": "production-order",
                       "prop": "shift-pattern", "type": "string"}],
            )
            s.add(proposal)
            await s.flush()
            result = await Promoter(sc.settings, sc.registry).promote(
                s, proposal, sc.package_root, eval_report={"passed": True})
            await s.commit()
        assert result["status"] == "promoted"

        await sc.reload()  # hot-swap the snapshot, as the API does after promotion

        async with sc.sessionmaker() as conn_session:
            conn = await conn_session.connection()
            columns = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("ontogeny_obj_production_order")})
        assert "shift_pattern" in columns, "promoted property must be added to the object table"

        # and it is queryable through the normal path
        async with sc.sessionmaker() as s:
            rows, total = await sc.repo.query(s, "production-order", limit=5)
        assert total >= 1
        assert "shift_pattern" in rows[0] and rows[0]["shift_pattern"] is None

        # a write through an action now sees the new column too
        async with sc.sessionmaker() as s:
            await sc.repo.action_update(s, "production-order", "PO-1002",
                                        {"shift-pattern": "DAY-DAY"}, dt.datetime.now(dt.timezone.utc))
            await s.commit()
            row = await sc.repo.get(s, "production-order", "PO-1002")
        assert row["shift_pattern"] == "DAY-DAY"

        await sc.engine.dispose()

    async def test_no_migration_needed_for_unchanged_tables(self, tmp_path, golden_pkg_path):
        """Re-booting the same package must not attempt ALTER on every column."""
        paths = prepare_demo(tmp_path / "demo2", package=golden_pkg_path)
        env = paths.as_env()
        settings = Settings(db_dsn=env["ONTOGENY_DB_DSN"], env=env)
        first = ServiceContext(settings, env["ONTOGENY_PACKAGE_ROOT"])
        await first.initialize()
        await first.sync("production-order")
        await first.engine.dispose()

        second = ServiceContext(settings, env["ONTOGENY_PACKAGE_ROOT"])
        await second.initialize()  # ensure_tables runs again, idempotently
        async with second.sessionmaker() as s:
            row = await second.repo.get(s, "production-order", "PO-1002")
        assert row["status"] == "PLANNED"
        await second.engine.dispose()


class TestTimestampTimezoneFidelity:
    """Regression: SQLite dropped the offset, so timestamps came back naive and
    every derived/comparison expression involving them silently evaluated to None."""

    async def _service(self, tmp_path, golden_pkg_path):
        paths = prepare_demo(tmp_path / "tz", package=golden_pkg_path)
        env = paths.as_env()
        sc = ServiceContext(Settings(db_dsn=env["ONTOGENY_DB_DSN"], env=env), env["ONTOGENY_PACKAGE_ROOT"])
        await sc.initialize()
        await sc.sync("production-order")
        return sc

    async def test_timestamps_read_back_as_utc_aware(self, tmp_path, golden_pkg_path):
        sc = await self._service(tmp_path, golden_pkg_path)
        try:
            async with sc.sessionmaker() as s:
                row = await sc.repo.get(s, "production-order", "PO-1002")
            assert isinstance(row["created_at"], dt.datetime), "timestamps must round-trip as datetimes"
            assert row["created_at"].tzinfo is not None, "timestamps must stay timezone-aware"
            assert row["created_at"].utcoffset() == dt.timedelta(0)
        finally:
            await sc.engine.dispose()

    async def test_derived_timestamp_expression_is_computed(self, tmp_path, golden_pkg_path):
        sc = await self._service(tmp_path, golden_pkg_path)
        try:
            # PO-1001 was created 2026-09-22T08:00Z and released 2026-09-23T08:00Z:
            # release_lag_h = (released_at - created_at) / 3600000 must be computed
            async with sc.sessionmaker() as s:
                obj = await sc.query.get(s, "production-order", "PO-1001",
                                         {"id": "t", "Role": ["planner"]})
            assert obj["release_lag_h"] is not None, "derived release_lag_h must not be blank"
            assert isinstance(obj["release_lag_h"], float)
            # the seed's fixed timestamps put the lag at exactly one day; just
            # prove it is a plausible hour delta rather than a crash fallback
            assert 0 < obj["release_lag_h"] < 48
        finally:
            await sc.engine.dispose()
