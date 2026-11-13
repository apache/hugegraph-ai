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

"""Agent plugin surface (M1): DSL validation, catalog intersection, session
lifecycle, governed tool execution through the real ServiceContext.
"""

from __future__ import annotations

import shutil

import pytest
import pytest_asyncio

from ontogeny.config import Settings
from ontogeny.core import validate
from ontogeny.core.loader import load_package as load_pkg
from ontogeny.demo import seed_from_package
from ontogeny.service import ServiceContext

# ------------------------------------------------------------------ DSL


def _pkg_with_plugin(tmp_path, golden_pkg_path, plugin_yaml: str):
    root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, root)
    (root / "agents").mkdir(exist_ok=True)
    # the package ships its own plugins; these tests exercise one injected
    # plugin in isolation, so start the copy from an empty agents/ dir
    for f in (root / "agents").glob("*.yaml"):
        f.unlink()
    (root / "agents" / "copilot.yaml").write_text(plugin_yaml, encoding="utf-8")
    return load_pkg(root)


VALID = """\
apiVersion: ontogeny/v1
kind: AgentPlugin
metadata:
  name: product-copilot
  display: Product copilot
spec:
  principal:
    id: "agent:product-copilot"
    Role: [product]
    site: hq
  transport: { kind: http }
  tools:
    allow: [describe_ontology, search_wafer_lot, search_tapeout_version, search_equipment,
        act_tapeout]
    deny: []
  approval: { writes: confirm }
  budget: { steps: 25, wall_ms: 60000, writes_per_session: 2 }
"""


class TestPluginDSL:
    def test_valid_plugin_loads_and_compiles(self, golden_pkg_path, tmp_path):
        pkg = _pkg_with_plugin(tmp_path, golden_pkg_path, VALID)
        rep = validate(pkg)
        assert rep.ok, [i.message for i in rep.issues if i.severity == "error"]
        assert len(pkg.agent_plugins()) == 1

    def test_unknown_tool_rejected(self, golden_pkg_path, tmp_path):
        bad = VALID.replace("search_equipment", "search_nope")
        pkg = _pkg_with_plugin(tmp_path, golden_pkg_path, bad)
        rep = validate(pkg)
        assert not rep.ok
        assert any(i.code == "AGENT-TOOL-UNKNOWN" for i in rep.issues)

    def test_unknown_role_rejected(self, golden_pkg_path, tmp_path):
        bad = VALID.replace("Role: [product]", "Role: [prodct]")
        pkg = _pkg_with_plugin(tmp_path, golden_pkg_path, bad)
        rep = validate(pkg)
        assert not rep.ok
        assert any(i.code == "AGENT-ROLE-UNKNOWN" for i in rep.issues)

    def test_allow_deny_conflict_rejected(self, golden_pkg_path, tmp_path):
        bad = VALID.replace("deny: []", "deny: [search_equipment]")
        pkg = _pkg_with_plugin(tmp_path, golden_pkg_path, bad)
        rep = validate(pkg)
        assert any(i.code == "AGENT-TOOL-CONFLICT" for i in rep.issues)

    def test_auto_without_actions_rejected(self, golden_pkg_path, tmp_path):
        bad = VALID.replace("approval: { writes: confirm }", "approval: { writes: auto }")
        pkg = _pkg_with_plugin(tmp_path, golden_pkg_path, bad)
        rep = validate(pkg)
        assert any(i.code == "AGENT-APPROVAL" for i in rep.issues)

    def test_bad_budget_rejected(self, golden_pkg_path, tmp_path):
        bad = VALID.replace("steps: 25", "steps: 0")
        pkg = _pkg_with_plugin(tmp_path, golden_pkg_path, bad)
        rep = validate(pkg)
        assert any(i.code == "AGENT-BUDGET" for i in rep.issues)


# ------------------------------------------------------------- catalog


class TestCatalog:
    def _compiled(self, golden_pkg_path, tmp_path):
        from ontogeny.registry import compile_package

        root = tmp_path / "pkg"
        shutil.copytree(golden_pkg_path, root)
        (root / "agents").mkdir(exist_ok=True)
        # the package ships its own plugins; these tests exercise one injected
        # plugin in isolation, so start the copy from an empty agents/ dir
        for f in (root / "agents").glob("*.yaml"):
            f.unlink()
        (root / "agents" / "copilot.yaml").write_text(VALID, encoding="utf-8")
        return compile_package(load_pkg(root))

    def test_effective_tools_is_an_intersection(self, golden_pkg_path, tmp_path):
        from ontogeny.agent.catalog import build_catalog, effective_tools

        compiled = self._compiled(golden_pkg_path, tmp_path)
        plug = next(iter(compiled.agent_plugins.values()))
        tools = effective_tools(compiled, plug)
        assert set(tools) == {
            "describe_ontology",
            "search_wafer_lot",
            "search_tapeout_version",
            "search_equipment",
            "act_tapeout",
        }
        # nothing outside the compiled vocabulary can appear
        assert set(tools) <= set(build_catalog(compiled))

    def test_empty_allow_means_reads_only(self, golden_pkg_path, tmp_path):
        from ontogeny.agent.catalog import effective_tools

        compiled = self._compiled(golden_pkg_path, tmp_path)
        plug = compiled.agent_plugins["product-copilot"]
        bare = plug.model_copy(deep=True)
        bare.spec.tools.allow = []
        bare.spec.tools.deny = []
        tools = effective_tools(compiled, bare)
        assert tools and not any(t.writes for t in tools.values())


# ------------------------------------------------------- service + broker


@pytest_asyncio.fixture()
async def sc(golden_pkg_path, tmp_path):
    root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, root)
    (root / "agents").mkdir(exist_ok=True)
    # the package ships its own plugins; these tests exercise one injected
    # plugin in isolation, so start the copy from an empty agents/ dir
    for f in (root / "agents").glob("*.yaml"):
        f.unlink()
    (root / "agents" / "copilot.yaml").write_text(VALID, encoding="utf-8")
    src = tmp_path / "erp.db"
    # the package owns its source data: execute its own seed SQL so the tables
    # match the ontology exactly
    seed_from_package(golden_pkg_path, src, force=True)
    settings = Settings(
        dev_auth=True,
        db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}", "FAB_WEBHOOK": "https://fab-portal.example.test/hook"},
    )
    ctx = ServiceContext(settings, str(root))
    await ctx.initialize()
    try:
        yield ctx
    finally:
        await ctx.engine.dispose()


class TestBroker:
    async def test_session_carries_frozen_budget_and_catalog(self, sc):
        out = await sc.agents.open_session("product-copilot", "盘点活跃设备并提交TO-A1流片")
        assert out["plugin"] == "product-copilot"
        assert out["principal"] == "agent:product-copilot"
        assert out["budget"]["steps"] == 25
        assert "act_tapeout" in out["tools"]
        assert out["catalog_hash"]

    async def test_unknown_plugin_rejected(self, sc):
        from ontogeny.errors import NotFoundError

        with pytest.raises(NotFoundError):
            await sc.agents.open_session("nope", "")

    async def test_search_runs_under_plugin_principal_and_masks(self, sc):
        for t in sc.compiled.objects:
            await sc.sync(t)
        session = await sc.agents.open_session("product-copilot", "")
        out = await sc.agents.call_tool(session["id"], "search_tapeout_version", {"limit": 5})
        assert out["outcome"] == "ok"
        rows = out["detail"]["objects"]
        assert rows and rows[0]["mask_cost"] == "__masked__"  # plugin has no markings

    async def test_tool_outside_catalog_refused(self, sc):
        session = await sc.agents.open_session("product-copilot", "")
        out = await sc.agents.call_tool(session["id"], "search_requirement", {})
        assert out["outcome"] == "AGENT_TOOL_NOT_ALLOWED"  # compiled but not in allow

    async def test_step_budget_enforced(self, sc):
        session = await sc.agents.open_session("product-copilot", "")
        sid = session["id"]
        # burn the budget with cheap describe calls (25 steps in the plugin spec)
        for _ in range(25):
            out = await sc.agents.call_tool(sid, "describe_ontology", {})
            assert out["outcome"] == "ok"
        out = await sc.agents.call_tool(sid, "describe_ontology", {})
        assert out["outcome"] == "AGENT_BUDGET_EXCEEDED"

    async def test_write_without_approval_is_pending(self, sc):
        await sc.sync("tapeout-version")
        session = await sc.agents.open_session("product-copilot", "")
        out = await sc.agents.call_tool(
            session["id"],
            "act_tapeout",
            {
                "parameters": {},
                "target_id": "TO-A1",
                "rationale": "TO-A1 is PLANNED and its mask set is ready; submit it to the fab",
            },
        )
        assert out["outcome"] == "pending_approval"
        assert out["approval_id"]
        # nothing executed: the tapeout version is still PLANNED
        async with sc.sessionmaker() as s:
            ver = await sc.query.get(s, "tapeout-version", "TO-A1", {"id": "auditor", "Role": ["auditor"]})
        assert ver["status"] == "PLANNED"

    async def test_finished_session_refuses_calls(self, sc):
        session = await sc.agents.open_session("product-copilot", "")
        await sc.agents.finish_session(session["id"], {"summary": "done"})
        out = await sc.agents.call_tool(session["id"], "describe_ontology", {})
        assert out["outcome"] == "AGENT_SESSION_CLOSED"


class TestDirectionSessionControls:
    """Configurable sessions: budget overrides (0 = unlimited), expiry, and
    multiple drives per session with per-run tagged traces."""

    async def test_budget_override_zero_is_unlimited(self, sc):
        limited = await sc.agents.open_session("product-copilot", "limited", budget={"steps": 1})
        unlimited = await sc.agents.open_session("product-copilot", "unlimited", budget={"steps": 0})

        async def step_probe(sess_id):
            out = await sc.agents.call_tool(sess_id, "search_tapeout_version", {"limit": 1})
            return out["outcome"]

        # limited: the first step passes, the second hits the ceiling
        assert await step_probe(limited["id"]) == "ok"
        assert await step_probe(limited["id"]) == "AGENT_BUDGET_EXCEEDED"
        # unlimited (steps=0): the gate never fires
        for _ in range(3):
            assert await step_probe(unlimited["id"]) == "ok"

    async def test_expired_session_refuses_calls_and_runs(self, sc):
        import datetime as _dt

        past = _dt.datetime.now(_dt.UTC) - _dt.timedelta(minutes=1)
        sess = await sc.agents.open_session("product-copilot", "expired", expires_at=past)
        out = await sc.agents.call_tool(sess["id"], "describe_ontology", {})
        assert out["outcome"] == "AGENT_SESSION_EXPIRED"
        from ontogeny.errors import OOError

        with pytest.raises(OOError) as ei:
            await sc.agents.start_run(sess["id"])
        assert ei.value.details.get("code") == "AGENT_SESSION_EXPIRED"

    async def test_rerun_increments_run_count_and_tags_steps(self, sc):
        first = await sc.agents.open_session("product-copilot", "multi-run")
        sid = first["id"]
        await sc.agents.call_tool(sid, "describe_ontology", {})
        await sc.agents.start_run(sid)  # run 2 (open session: counter bumps)
        await sc.agents.call_tool(sid, "search_tapeout_version", {"limit": 5})
        detail = await sc.agents.get_session(sid)
        assert detail["run_count"] == 2
        assert [st["run_no"] for st in detail["steps"]] == [1, 2]
