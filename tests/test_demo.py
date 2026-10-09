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
"""Demo bootstrap (`ontogeny serve --demo`) + same-origin SPA serving.

These cover the "one command" promise: seed -> copy package -> publish -> sync
-> serve, with the UI mounted on the same port as the API.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import httpx
import pytest_asyncio

from ontogeny.core import load_package, validate
from ontogeny.demo import (
    DEFAULT_PACKAGE,
    DemoPaths,
    copy_package,
    prepare_demo,
    reset_demo,
    seed_source_db,
)

OBJECT_TYPES = ("product", "material", "bom", "work-center",
                "production-order", "operation", "quality-inspection")


class TestSeedSource:
    """The built-in fallback dataset for packages that ship no seed/*.sql."""

    def test_creates_database_with_rows(self, tmp_path):
        db = tmp_path / "erp.db"
        seed_source_db(db)
        assert db.is_file()
        con = sqlite3.connect(str(db))
        try:
            assert con.execute("SELECT COUNT(*) FROM equipment").fetchone()[0] == 2
            assert con.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0] == 3
            assert con.execute("SELECT COUNT(*) FROM parts").fetchone()[0] == 2
            assert con.execute("SELECT COUNT(*) FROM work_order_parts").fetchone()[0] == 1
        finally:
            con.close()

    def test_idempotent_unless_forced(self, tmp_path):
        db = tmp_path / "erp.db"
        seed_source_db(db)
        con = sqlite3.connect(str(db))
        con.execute("INSERT INTO parts VALUES ('X','extra','1','1')")
        con.commit()
        con.close()
        seed_source_db(db)  # no-op
        con = sqlite3.connect(str(db))
        assert con.execute("SELECT COUNT(*) FROM parts").fetchone()[0] == 3
        con.close()
        seed_source_db(db, force=True)
        con = sqlite3.connect(str(db))
        assert con.execute("SELECT COUNT(*) FROM parts").fetchone()[0] == 2
        con.close()


class TestCopyPackage:
    def test_store_points_at_the_demo_sqlite_source(self, golden_pkg_path, tmp_path):
        dest = copy_package(golden_pkg_path, tmp_path / "pkg")
        import yaml

        # the domain's store is already demo-shaped: a local sqlite source the
        # bootstrap's ERP_DSN points at
        doc = yaml.safe_load((dest / "stores" / "mes.yaml").read_text(encoding="utf-8"))
        assert doc["spec"]["type"] == "sqlite"
        assert doc["spec"]["connection"] == "${ERP_DSN}"
        assert doc["spec"]["access"] == "read-write"
        # the copy still validates as a package
        assert validate(load_package(dest)).ok

    def test_source_example_left_untouched(self, golden_pkg_path, tmp_path):
        source_store = (golden_pkg_path / "stores" / "mes.yaml").read_text(encoding="utf-8")
        copy_package(golden_pkg_path, tmp_path / "pkg")
        assert (golden_pkg_path / "stores" / "mes.yaml").read_text(encoding="utf-8") == source_store

    def test_reuse_unless_forced(self, golden_pkg_path, tmp_path):
        dest = tmp_path / "pkg"
        copy_package(golden_pkg_path, dest)
        (dest / "marker.txt").write_text("keep me", encoding="utf-8")
        copy_package(golden_pkg_path, dest)  # no force -> reused
        assert (dest / "marker.txt").is_file()
        copy_package(golden_pkg_path, dest, force=True)
        assert not (dest / "marker.txt").exists()


class TestPrepareDemo:
    def test_layout_and_env(self, golden_pkg_path, tmp_path):
        paths = prepare_demo(tmp_path / "demo", package=golden_pkg_path)
        assert isinstance(paths, DemoPaths)
        assert (paths.root / "erp.db").is_file()
        assert (paths.package_root / "ontology.yaml").is_file()
        env = paths.as_env()
        assert env["ONTOGENY_DB_DSN"].startswith("sqlite+aiosqlite:///")
        assert env["ONTOGENY_PACKAGE_ROOT"] == str(paths.package_root)
        assert env["ERP_DSN"].startswith("sqlite+aiosqlite:///")
        assert env["WMS_WEBHOOK"].startswith("https://")

    def test_reseed_rebuilds_artifacts(self, golden_pkg_path, tmp_path):
        paths = prepare_demo(tmp_path / "demo", package=golden_pkg_path)
        (paths.package_root / "marker.txt").write_text("x", encoding="utf-8")
        prepare_demo(tmp_path / "demo", package=golden_pkg_path)
        assert (paths.package_root / "marker.txt").is_file()  # reused
        prepare_demo(tmp_path / "demo", package=golden_pkg_path, reseed=True)
        assert not (paths.package_root / "marker.txt").exists()

    def test_direct_mode_serves_the_source_and_skips_copies(self, golden_pkg_path, tmp_path):
        """`serve --demo` over a first-class domain serves it IN PLACE: no pkg/
        or pkg.pristine copies are made, so console saves (model edits and the
        canvas layout.yaml) land in the domain directory itself."""
        src = tmp_path / "domains" / "acme"
        shutil.copytree(golden_pkg_path, src)
        paths = prepare_demo(tmp_path / "demo", package=src, direct=True)
        assert Path(paths.package_root) == src.resolve()
        assert not (tmp_path / "demo" / "pkg").exists()
        assert not (tmp_path / "demo" / "pkg.pristine").exists()
        assert (paths.root / "erp.db").is_file()  # data seeding is unchanged

        # a builder save (layout sidecar) lands in the SOURCE domain directory
        async def _save():
            import httpx

            from ontogeny.api import build_app
            from ontogeny.config import Settings
            from ontogeny.service import ServiceContext

            settings = Settings(dev_auth=True, db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'oo.db'}")
            sc = ServiceContext(settings, str(paths.package_root))
            await sc.initialize()
            sc.write_layout({"type:product": {"x": 111, "y": 60}})
            app = build_app(sc)
            transport = httpx.ASGITransport(app=app)
            import json as _json
            async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                         headers={"X-Ontogeny-Principal": _json.dumps({"id": "ci-admin", "is_admin": True})}) as c:
                r = await c.get("/api/v1/admin/builder/resources")
                assert r.status_code == 200
                assert r.json()["layout"]["type:product"] == {"x": 111, "y": 60}

        import asyncio

        asyncio.run(_save())
        assert (src / "layout.yaml").is_file()

    def test_copy_mode_is_untouched_for_non_domain_packages(self, golden_pkg_path, tmp_path):
        """Outside a domains/ root the old copy+pristine behavior applies
        (tests and ad-hoc demos rely on the package being a throwaway)."""
        src = tmp_path / "not-a-domain"
        shutil.copytree(golden_pkg_path, src)
        paths = prepare_demo(tmp_path / "demo", package=src)
        assert (tmp_path / "demo" / "pkg").is_dir()
        assert (tmp_path / "demo" / "pkg.pristine").is_dir()
        assert Path(paths.package_root) == (tmp_path / "demo" / "pkg").resolve()

    def test_reset_removes_everything(self, golden_pkg_path, tmp_path):
        root = tmp_path / "demo"
        prepare_demo(root, package=golden_pkg_path)
        reset_demo(root)
        assert not root.exists()

    def test_default_package_points_at_the_domain_example(self):
        """`serve --demo` must showcase the product-manufacturing domain."""
        assert Path(DEFAULT_PACKAGE).parts == ("domains", "product-manufacturing")
        assert (Path(__file__).resolve().parent.parent / DEFAULT_PACKAGE / "ontology.yaml").is_file()


class TestDemoIsRunnable:
    """The full demo bootstrap, driven through the real ServiceContext."""

    @pytest_asyncio.fixture()
    async def sc(self, golden_pkg_path, tmp_path):
        from ontogeny.api import build_app
        from ontogeny.config import Settings
        from ontogeny.service import ServiceContext

        paths = prepare_demo(tmp_path / "demo", package=golden_pkg_path)
        env = paths.as_env()
        settings = Settings(dev_auth=True, db_dsn=env["ONTOGENY_DB_DSN"], env=env, llm_base_url=None)
        ctx = ServiceContext(settings, env["ONTOGENY_PACKAGE_ROOT"])
        await ctx.initialize()
        app = build_app(ctx)
        transport = httpx.ASGITransport(app=app)
        # admin/evolve planes are gated: default identity for headerless calls
        import json as _json
        async with httpx.AsyncClient(transport=transport, base_url="http://demo",
                                     headers={"X-Ontogeny-Principal": _json.dumps({"id": "ci-admin", "is_admin": True})}) as client:
            yield client, ctx

    async def test_syncs_seeded_data(self, sc):
        client, _ = sc
        for t in OBJECT_TYPES:
            r = await client.post(f"/api/v1/admin/sync/{t}")
            assert r.status_code == 200
            assert r.json()["inserted"] > 0

        r = await client.post("/api/v1/objects/production-order/query",
                              json={"filter": {"status": "RELEASED"}})
        assert r.json()["total"] == 2

    async def test_release_production_order_against_sqlite_source(self, sc):
        client, _ = sc
        await client.post("/api/v1/admin/sync/production-order")
        r = await client.post(
            "/api/v1/actions/release-production-order/execute",
            json={"parameters": {}, "target_id": "PO-1002"},
            headers={"X-Ontogeny-Principal": '{"id":"demo","Role":["planner"],"site":"plant-north"}'},
        )
        assert r.status_code == 200
        assert r.json()["after"]["status"] == "RELEASED"

    async def test_rsl_loop_reaches_live_schema(self, sc):
        """Signals from demo traffic promote a schema change (M5 acceptance)."""
        client, _ = sc
        # the eval suite queries orders, operations and work centres: all of
        # them must be materialized for a proposal to eval green
        for t in OBJECT_TYPES:
            await client.post(f"/api/v1/admin/sync/{t}")
        for _ in range(6):
            await client.post(
                "/api/v1/objects/production-order/query",
                json={"filter": {"field": "shift", "op": "eq", "value": "DAY"}},
            )
        agg = await client.post("/api/v1/evolve/aggregate")
        assert any(s["kind"] == "unmapped_filter_field" for s in agg.json()["created"])
        diag = await client.post("/api/v1/evolve/diagnose")
        pid = diag.json()["proposals"][0]["id"]
        assert (await client.post(f"/api/v1/evolve/proposals/{pid}/eval")).json()["passed"] is True
        promoted = await client.post(f"/api/v1/evolve/proposals/{pid}/promote")
        assert promoted.json()["status"] == "promoted"
        meta = await client.get("/api/v1/meta/ontology")
        assert "shift" in meta.json()["objects"]["production-order"]["properties"]


class TestSpaServing:
    """SPA static mount: assets + client-side routes, never shadowing /api."""

    @pytest_asyncio.fixture()
    async def client(self, golden_pkg_path, tmp_path):
        from ontogeny.api import build_app
        from ontogeny.config import Settings
        from ontogeny.service import ServiceContext

        ui = tmp_path / "dist"
        (ui / "assets").mkdir(parents=True)
        (ui / "index.html").write_text("<html><body>OO SPA SHELL</body></html>", encoding="utf-8")
        (ui / "assets" / "app.js").write_text("console.log('ontogeny')", encoding="utf-8")

        settings = Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path/'m.db'}",
                            env={"ERP_DSN": f"sqlite+aiosqlite:///{tmp_path/'erp.db'}"})
        ctx = ServiceContext(settings, str(golden_pkg_path), ui_dir=str(ui))
        await ctx.initialize()
        transport = httpx.ASGITransport(app=build_app(ctx))
        async with httpx.AsyncClient(transport=transport, base_url="http://demo") as c:
            yield c

    async def test_root_serves_index(self, client):
        r = await client.get("/")
        assert r.status_code == 200 and "OO SPA SHELL" in r.text

    async def test_client_route_falls_back_to_index(self, client):
        for path in ("/ontology", "/objects/production-order/PO-1001", "/evolve/3"):
            r = await client.get(path)
            assert r.status_code == 200 and "OO SPA SHELL" in r.text, path

    async def test_assets_are_served(self, client):
        r = await client.get("/assets/app.js")
        assert r.status_code == 200 and "console.log" in r.text

    async def test_missing_asset_is_404_json(self, client):
        r = await client.get("/assets/nope.js")
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"

    async def test_api_is_never_shadowed(self, client):
        r = await client.get("/api/v1/meta/ontology")
        assert r.status_code == 200 and r.json()["package"] == "product-manufacturing"
        r = await client.get("/api/v1/does-not-exist")
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
        assert "OO SPA SHELL" not in r.text

    async def test_path_traversal_is_refused(self, client):
        r = await client.get("/assets/../index.html")
        assert r.status_code in (200, 404)  # normalized by the client/ASGI layer
        r = await client.get("/assets/%2e%2e/index.html")
        assert r.status_code == 404


class TestUiResolution:
    def test_missing_dist_resolves_to_none(self, tmp_path):
        from ontogeny.api.app import resolve_ui_dir

        assert resolve_ui_dir(tmp_path) is None

    def test_existing_dist_resolves(self, tmp_path):
        from ontogeny.api.app import resolve_ui_dir

        (tmp_path / "index.html").write_text("x", encoding="utf-8")
        assert resolve_ui_dir(tmp_path) == tmp_path
