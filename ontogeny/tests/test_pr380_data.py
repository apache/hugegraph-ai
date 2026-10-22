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
"""PR #380 data/robustness-pack regression tests: projection backfill
pagination, builder store sidecars, demo env respect, admin lockout
self-heal, bounded reads, sandbox stdout isolation."""

from __future__ import annotations

import pytest


class TestProjectionKeysetBackfill:
    async def test_backfill_pages_past_batch_size(self, client):
        """A 25-row table with batch forced to 10 must fully land in the graph."""
        import datetime as dt

        from ontogeny.projection.worker import ProjectionWorker

        c, sc = client
        await c.post("/api/v1/admin/sync/work-center")
        # 4 seeded + 21 fresh rows = 25 > any single page
        for i in range(21):
            async with sc.sessionmaker() as s:
                await sc.repo.action_insert(
                    s,
                    "work-center",
                    {
                        "work_center_id": f"WC-X{i:02d}",
                        "name": f"Extra {i}",
                        "process": "assembly",
                        "site": "plant-north",
                        "capacity_per_shift": 10,
                        "shifts_per_day": 1,
                        "status": "ACTIVE",
                    },
                    dt.datetime.now(dt.timezone.utc),
                )
                await s.commit()

        prj = next(iter(sc.compiled.projections.values()))
        upserted: list[int] = []

        class FakeClient:
            async def upsert_vertices(self, label, pk, items):
                upserted.append(len(items))

            async def upsert_edges(self, *a, **k):
                return None

        worker = ProjectionWorker.__new__(ProjectionWorker)
        worker.projection = prj
        worker.compiled = sc.compiled
        worker.client = FakeClient()
        worker._link_pairs = ProjectionWorker._link_pairs.__get__(worker)
        # 强制小批量：monkeypatch 掉常量

        original_query = sc.repo.query

        async def small_query(session, object_type, **kw):
            kw["limit"] = min(kw.get("limit", 10), 10)
            return await original_query(session, object_type, **kw)

        sc.repo.query = small_query
        try:
            async with sc.sessionmaker() as s:
                expected = len(await sc.repo.alive_ids(s, "work-center"))
                counts = await worker.rebuild(sc.repo, s)
        finally:
            sc.repo.query = original_query
        assert counts["vertices"] == expected, "backfill must page through every row"
        assert all(n <= 10 for n in upserted), "each page respects the batch bound"


class TestBuilderStoreSidecars:
    async def test_inline_store_spec_materializes_store_yaml(self, client):
        c, sc = client
        obj = {
            "apiVersion": "ontogeny/v1",
            "kind": "ObjectType",
            "metadata": {"name": "widget", "display": "Widget"},
            "spec": {
                "primaryKey": ["widget_id"],
                "properties": {
                    "widget_id": {"type": "string", "display": "ID", "required": True},
                    "name": {"type": "string", "display": "Name"},
                },
                "backing": {
                    "store": "widget-src",
                    "mode": "materialized",
                    "source": {"table": "widgets"},
                    "store_spec": {"kind": "sqlite", "connection": "sqlite:///widgets.db"},
                },
            },
        }
        r = await c.post("/api/v1/admin/builder/save", json={"resources": [obj]})
        assert r.status_code == 200, r.text
        import pathlib

        store_yaml = pathlib.Path(sc.package_root) / "stores" / "widget-src.yaml"
        assert store_yaml.is_file(), "the inline store sidecar must be written"
        assert "sqlite" in store_yaml.read_text(encoding="utf-8")


class TestDemoEnvRespect:
    def test_as_env_does_not_clobber_operator_values(self, tmp_path, monkeypatch):
        from ontogeny.demo.bootstrap import prepare_demo

        monkeypatch.setenv("ONTOGENY_DB_DSN", "sqlite+aiosqlite:////data/operator.db")
        paths = prepare_demo(tmp_path / "demo", package="domains/product-manufacturing")
        env = paths.as_env()
        import os

        assert os.environ["ONTOGENY_DB_DSN"].endswith("/operator.db")
        # the exact cli behaviour under test:
        for key, val in env.items():
            os.environ.setdefault(key, val)
        assert os.environ["ONTOGENY_DB_DSN"].endswith("/operator.db"), "operator-preset env must survive a --demo boot"


class TestAdminLockout:
    async def test_cannot_demote_last_admin(self, client):
        from ontogeny.errors import ConflictError

        _c, sc = client
        with pytest.raises(ConflictError):
            await sc.auth.update_user("admin", {"is_admin": False})
        with pytest.raises(ConflictError):
            await sc.auth.update_user("admin", {"status": "disabled"})

    async def test_second_admin_can_be_demoted(self, client):
        _c, sc = client
        await sc.auth.create_user(username="admin2", password="password123", roles=["admin"], is_admin=True)
        out = await sc.auth.update_user("admin2", {"is_admin": False})
        assert out["is_admin"] is False

    async def test_ensure_admin_self_heals_disabled_bootstrap(self, client):
        _c, sc = client
        # 直接把 root 停用（绕过守卫模拟历史脏数据），ensure_admin 应复活它而非崩溃
        from sqlalchemy import update

        from ontogeny.auth.models import UserRow

        async with sc.sessionmaker() as s:
            await s.execute(update(UserRow).values(status="disabled"))
            await s.commit()
        user = await sc.auth.ensure_admin()
        assert user is not None and user["is_admin"] is True and user["status"] == "active"


class TestBoundedReads:
    async def test_query_limit_rejected_over_bound(self, client):
        c, _ = client
        r = await c.post("/api/v1/objects/work-center/query", json={"limit": 100000})
        assert r.status_code == 422

    async def test_traverse_depth_rejected_over_bound(self, client):
        c, _ = client
        r = await c.post(
            "/api/v1/graph/traverse",
            json={
                "start_type": "production-order",
                "start_ids": ["PO-1001"],
                "path": [],
                "max_depth": 10,
            },
        )
        assert r.status_code == 422

    async def test_readonly_tool_limit_clamped(self, client):
        c, sc = client
        await c.post("/api/v1/admin/sync/work-center")
        out = await sc.agents.read_only_tool("search_work_center", None, {"limit": 999999})
        assert out["outcome"] == "ok" and len(out["detail"]["objects"]) <= 1000


class TestSandboxStdoutIsolation:
    async def test_print_does_not_break_protocol(self, tmp_path, golden_pkg_path):
        import shutil

        pkg = tmp_path / "pkg"
        shutil.copytree(golden_pkg_path, pkg)
        (pkg / "functions" / "chatty.py").write_text(
            "def say(what):\n    print('user-side noise:', what)\n    return {'said': what}\n",
            encoding="utf-8",
        )
        import yaml as _yaml

        doc = _yaml.safe_load((pkg / "functions" / "capacity-check.yaml").read_text(encoding="utf-8"))
        doc["metadata"]["name"] = "chatty"
        doc["spec"]["entry"] = "chatty.py:say"
        doc["spec"]["parameters"] = {"what": {"type": "string", "display": "What", "required": True}}
        doc["spec"]["capabilities"] = []
        doc["spec"].pop("returns", None)
        (pkg / "functions" / "chatty.yaml").write_text(
            _yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

        from ontogeny.config import Settings
        from ontogeny.core import load_package
        from ontogeny.db import init_schema, make_engine, make_sessionmaker
        from ontogeny.functions.sandbox import FunctionSandbox
        from ontogeny.registry.store import RegistryService

        Settings(env={"ERP_DSN": "sqlite+aiosqlite:///:memory:"})
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        await init_schema(engine)
        maker = make_sessionmaker(engine)
        async with maker() as s:
            compiled = await RegistryService().publish(s, load_package(str(pkg)))
            await s.commit()
        fn = compiled.functions["chatty"]
        from ontogeny.stores import ObjectRepository

        sandbox = FunctionSandbox(compiled, ObjectRepository(compiled), timeout_s=15)
        async with maker() as s:
            value = await sandbox.run(s, fn, {"what": "hello"})
        assert value == {"said": "hello"}
