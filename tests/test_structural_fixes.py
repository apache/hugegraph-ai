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
"""Regression tests for the structural pass: sandbox env allowlist, MCP
read-only convergence, and the migrate planner."""
from __future__ import annotations



# ---------------------------------------------------------------------------
# sandbox env: an allowlist, not inheritance
# ---------------------------------------------------------------------------


class TestSandboxEnv:
    def test_secrets_are_not_inherited(self, monkeypatch):
        from ontogeny.functions.sandbox import sandbox_env

        monkeypatch.setenv("ONTOGENY_DB_DSN", "postgresql://u:secret@db/ontogeny")
        monkeypatch.setenv("HUGEGRAPH_PASSWORD", "graph-secret")
        monkeypatch.setenv("ONTOGENY_LLM_API_KEY", "sk-test")
        monkeypatch.setenv("PATH", "/usr/bin")
        env = sandbox_env("/opt/ontogeny/server")
        for leaked in ("ONTOGENY_DB_DSN", "HUGEGRAPH_PASSWORD", "ONTOGENY_LLM_API_KEY"):
            assert leaked not in env, f"{leaked} must not reach the sandbox child"
        assert env["PATH"] == "/usr/bin"
        assert "/opt/ontogeny/server" in env["PYTHONPATH"]
        assert env["PYTHONDONTWRITEBYTECODE"] == "1"

    def test_operator_can_widen_the_allowlist(self, monkeypatch):
        from ontogeny.functions.sandbox import sandbox_env

        monkeypatch.setenv("MY_FUNC_TOKEN", "t")
        monkeypatch.setenv("ONTOGENY_SANDBOX_ENV_PASSTHROUGH", "MY_FUNC_TOKEN")
        assert sandbox_env("/s")["MY_FUNC_TOKEN"] == "t"

    async def test_functions_still_run_with_the_allowlist(self, client):
        """The golden package's sandboxed functions must keep working under the
        narrowed environment (they need nothing beyond PATH/PYTHONPATH)."""
        c, sc = client
        await c.post("/api/v1/admin/sync/work-center")
        await c.post("/api/v1/admin/sync/production-order")
        r = await c.post("/api/v1/functions/capacity-check/invoke",
                         json={"parameters": {"work_center_id": "WC-01", "qty": 10}})
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# MCP sessionless reads go through the broker (telemetry included)
# ---------------------------------------------------------------------------


class TestReadOnlyConvergence:
    async def test_sessionless_search_records_query_telemetry(self, client):
        from sqlalchemy import select

        from ontogeny.telemetry.service import TelemetryQueryRow

        c, sc = client
        await c.post("/api/v1/admin/sync/work-center")
        out = await sc.agents.read_only_tool("search_work_center", None, {"limit": 5})
        assert out["outcome"] == "ok"
        async with sc.sessionmaker() as s:
            rows = (await s.execute(select(TelemetryQueryRow))).scalars().all()
        assert any(r.object_type == "work-center" for r in rows), \
            "sessionless MCP search used to be invisible to the evolution loop"

    async def test_sessionless_write_still_refused(self, client):
        c, sc = client
        out = await sc.agents.read_only_tool("act_release_production_order", None, {})
        assert out["outcome"] == "WRITE_REQUIRES_SESSION"

    async def test_missing_required_argument_is_structured(self, client):
        c, sc = client
        out = await sc.agents.read_only_tool("traverse_graph", None, {})
        assert out["outcome"] != "ok" and "start_type" in out.get("error", "")


# ---------------------------------------------------------------------------
# the migrate planner: DSL vs live tables
# ---------------------------------------------------------------------------


class TestMigratePlanner:
    async def test_orphan_column_is_flagged_destructive(self, client):
        from sqlalchemy import text

        from ontogeny.stores.migrate import plan_migration

        c, sc = client
        await c.post("/api/v1/admin/sync/work-center")
        async with sc.sessionmaker() as s:
            await s.execute(text("ALTER TABLE ontogeny_obj_work_center ADD COLUMN ghost TEXT"))
            await s.commit()
            conn = await s.connection()  # re-acquired: commit released the prior one
            plan = await conn.run_sync(lambda cc: plan_migration(cc, sc.compiled))
            kinds = {(st.kind, st.column) for st in plan.steps}
        assert ("drop-column", "ghost") in kinds
        # destructive steps never ride --apply
        assert all(st.kind != "drop-column" for st in plan.safe)

    async def test_missing_column_is_safe_and_applicable(self, client):
        from sqlalchemy import text

        from ontogeny.stores.migrate import apply_safe, plan_migration

        c, sc = client
        await c.post("/api/v1/admin/sync/work-center")
        async with sc.sessionmaker() as s:
            await s.execute(text("ALTER TABLE ontogeny_obj_work_center DROP COLUMN site"))
            await s.commit()
            conn = await s.connection()  # re-acquired: commit released the prior one
            plan = await conn.run_sync(lambda cc: plan_migration(cc, sc.compiled))
            assert ("add-column", "site") in {(st.kind, st.column) for st in plan.steps}
            n = await conn.run_sync(lambda cc: apply_safe(cc, plan))
            await s.commit()
            assert n >= 1
        # the platform's own read path works again
        r = await c.post("/api/v1/objects/work-center/query", json={"limit": 1})
        assert r.status_code == 200

    async def test_in_sync_report_is_clean(self, client):
        from ontogeny.stores.migrate import plan_migration

        c, sc = client
        await c.post("/api/v1/admin/sync/work-center")
        async with sc.sessionmaker() as s:
            conn = await s.connection()
            plan = await conn.run_sync(lambda cc: plan_migration(cc, sc.compiled))
            assert plan.steps == []

    async def test_render_and_payload(self, client):
        from ontogeny.stores.migrate import plan_migration, summary_payload

        c, sc = client
        await c.post("/api/v1/admin/sync/work-center")
        async with sc.sessionmaker() as s:
            conn = await s.connection()
            plan = await conn.run_sync(lambda cc: plan_migration(cc, sc.compiled))
            assert "in sync" in plan.render()
        payload = summary_payload(plan)
        assert payload == {"safe": [], "destructive": []}


# ---------------------------------------------------------------------------
# the app split: layering invariants
# ---------------------------------------------------------------------------


class TestLayering:
    def test_api_module_does_not_import_run_diagnose(self):
        """The scheduled worker must not reach into the web layer: run_diagnose
        lives in the service layer (ontogeny.evolve.ops) now."""
        import ontogeny.api.app as app_mod

        assert not hasattr(app_mod, "run_diagnose")
        import ontogeny.evolve.ops as ops_mod

        assert hasattr(ops_mod, "run_diagnose")

    def test_route_files_own_no_sql_selects(self):
        """The split's rule: route bodies orchestrate calls; SQL lives in the
        service layer. (SSE/audit list filters are the one tolerated reader;
        they are selects over the platform's own audit tables.)"""
        import pathlib

        routes = pathlib.Path("server/ontogeny/api").glob("routes_*.py")
        # evolve/data still list their own console tables (audit trail, proposal
        # queue) -- tolerated readers; the business planes must stay SQL-free
        tolerated = {"routes_data.py", "routes_evolve.py", "routes_agent.py"}
        offenders = [
            p.name for p in routes
            if "select(" in p.read_text(encoding="utf-8") and p.name not in tolerated
        ]
        assert offenders == [], f"route modules drifted into SQL: {offenders}"

    def test_builder_save_is_reachable_at_service_level(self):
        import ontogeny.builder_ops as ops

        assert callable(ops.builder_save)
