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

"""M3: AgentCase eval -- scripted trajectories replayed through the real
broker as a deterministic selection function for agent-affecting changes.
"""

from __future__ import annotations

import shutil

import httpx
import pytest_asyncio
from sqlalchemy import func, select

from ontogeny.action.models import OutboxRow, RevisionRow
from ontogeny.agent.models import AgentSessionRow, AgentStepRow
from ontogeny.config import Settings
from ontogeny.core import load_package
from ontogeny.core.models import FunctionExecution
from ontogeny.demo import seed_from_package
from ontogeny.service import ServiceContext

PLUGIN = """\
apiVersion: ontogeny/v1
kind: AgentPlugin
metadata:
  name: planning-copilot
  display: Planning copilot
spec:
  principal:
    id: "agent:planning-copilot"
    Role: [planner]
    site: plant-north
  transport: { kind: local }
  tools:
    allow: [describe_ontology, search_production_order, act_release_production_order]
  approval: { writes: auto, auto_actions: [act_release_production_order] }
  budget: { steps: 25, wall_ms: 60000, writes_per_session: 5 }
"""

SUITE = """\
apiVersion: ontogeny/v1
kind: EvalSuite
metadata:
  name: planning-suite
spec:
  agents:
  - name: copilot-releases-and-is-idempotent
    plugin: planning-copilot
    script:
    - tool: search_production_order
      args: { filter: { field: status, op: eq, value: PLANNED }, limit: 5 }
    - tool: act_release_production_order
      args: { parameters: {}, target_id: PO-1002 }
    expect:
      outcomes: [ok, ok]
      idempotent: true
"""


@pytest_asyncio.fixture()
async def sc(golden_pkg_path, tmp_path):
    root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, root)
    (root / "agents").mkdir(exist_ok=True)
    # the package ships its own plugins; these tests exercise one injected
    # plugin in isolation, so start the copy from an empty agents/ dir
    for f in (root / "agents").glob("*.yaml"):
        f.unlink()
    (root / "agents" / "copilot.yaml").write_text(PLUGIN, encoding="utf-8")
    (root / "evals" / "planning.yaml").write_text(SUITE, encoding="utf-8")
    src = tmp_path / "erp.db"
    # the package owns its source data: execute its own seed SQL so the tables
    # match the ontology exactly
    seed_from_package(golden_pkg_path, src, force=True)
    settings = Settings(
        dev_auth=True,
        db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}", "WMS_WEBHOOK": "https://wms.example.test/hook"},
    )
    ctx = ServiceContext(settings, str(root))
    await ctx.initialize()
    for t in ctx.compiled.objects:
        await ctx.sync(t)
    return ctx


class TestAgentEval:
    async def test_eval_writes_only_to_isolated_snapshots(self, sc, monkeypatch):
        suite = sc.compiled.eval_suites["planning-suite"].model_copy(deep=True)
        suite.spec.agents.append(suite.spec.agents[0].model_copy(deep=True))
        suite.spec.agents[1].name = "second-independent-case"

        async def forbidden(*args, **kwargs):
            raise AssertionError("evaluation used the live broker/runtime")

        monkeypatch.setattr(sc.agents, "call_tool", forbidden)
        monkeypatch.setattr(sc.runtime, "execute", forbidden)
        async with sc.sessionmaker() as s:
            before = await sc.repo.get(s, "production-order", "PO-1002")
            counts = [
                await s.scalar(select(func.count()).select_from(m))
                for m in (RevisionRow, OutboxRow, AgentSessionRow, AgentStepRow)
            ]
            first = await sc.eval_runner.run(s, suite)
            second = await sc.eval_runner.run(s, suite)
            assert [c["outcomes"] for c in first["cases"]] == [["ok", "ok"], ["ok", "ok"]]
            assert [c["replay"] for c in first["cases"]] == [c["replay"] for c in second["cases"]]
            assert all(c["ok"] for c in first["cases"] + second["cases"])
            assert await sc.repo.get(s, "production-order", "PO-1002") == before
            assert counts == [
                await s.scalar(select(func.count()).select_from(m))
                for m in (RevisionRow, OutboxRow, AgentSessionRow, AgentStepRow)
            ]

    async def test_candidate_action_rules_are_used(self, sc):
        suite = sc.compiled.eval_suites["planning-suite"]
        candidate = load_package(sc.package_root)
        action = candidate.find("Action", "release-production-order")
        action.spec.rules[0].expr = "false"
        async with sc.sessionmaker() as s:
            report = await sc.eval_runner.run(s, suite, candidate_pkg=candidate)
        assert not report["cases"][0]["ok"]
        assert report["cases"][0]["actual"] == ["ok", "rejected"]

    async def test_webhook_effect_is_never_delivered(self, sc, monkeypatch):
        candidate = load_package(sc.package_root)
        action = candidate.find("Action", "release-production-order")
        next(effect for effect in action.spec.effects if effect.kind == "webhook").when = None

        async def forbidden(*args, **kwargs):
            raise AssertionError("evaluation attempted an HTTP delivery")

        monkeypatch.setattr(httpx.AsyncClient, "post", forbidden)
        suite = sc.compiled.eval_suites["planning-suite"]
        async with sc.sessionmaker() as s:
            before = await s.scalar(select(func.count()).select_from(OutboxRow))
            report = await sc.eval_runner.run(s, suite, candidate_pkg=candidate)
            assert report["cases"][0]["ok"], report
            assert await s.scalar(select(func.count()).select_from(OutboxRow)) == before

    async def test_function_backed_action_fails_closed(self, sc):
        candidate = load_package(sc.package_root)
        action = candidate.find("Action", "release-production-order")
        action.spec.execution = FunctionExecution(kind="function", entry="capacity.py:capacity")
        suite = sc.compiled.eval_suites["planning-suite"]
        async with sc.sessionmaker() as s:
            report = await sc.eval_runner.run(s, suite, candidate_pkg=candidate)
        assert not report["cases"][0]["ok"]
        assert "cannot execute function-backed tool" in report["cases"][0]["error"]

    async def test_function_tool_fails_closed(self, sc):
        candidate = load_package(sc.package_root)
        candidate.find("AgentPlugin", "planning-copilot").spec.tools.allow.append("call_material_availability")
        suite = sc.compiled.eval_suites["planning-suite"].model_copy(deep=True)
        suite.spec.agents[0].script = [{"tool": "call_material_availability", "args": {"parameters": {}}}]
        async with sc.sessionmaker() as s:
            report = await sc.eval_runner.run(s, suite, candidate_pkg=candidate)
        assert not report["cases"][0]["ok"]
        assert "cannot execute function-backed tool" in report["cases"][0]["error"]

    async def test_incompatible_candidate_schema_fails_closed(self, sc):
        candidate = load_package(sc.package_root)
        candidate.find("ObjectType", "material").spec.properties["unit_cost"].type = "string"
        suite = sc.compiled.eval_suites["planning-suite"]
        async with sc.sessionmaker() as s:
            report = await sc.eval_runner.run(s, suite, candidate_pkg=candidate)
        assert not report["cases"][0]["ok"]
        assert "incompatible eval snapshot" in report["cases"][0]["error"]

    async def test_scripted_replay_passes_and_detects_double_apply(self, sc):
        suite = sc.compiled.eval_suites["planning-suite"]
        async with sc.sessionmaker() as s:
            report = await sc.eval_runner.run(s, suite)
        case = report["cases"][0]
        assert case["kind"] == "agent"
        assert case["ok"], case
        assert case["outcomes"] == ["ok", "ok"]
        # idempotency: the replay must show the second release refused by rules
        assert "replay" in case
        assert case["replay"][1] == "rejected"

    async def test_outcome_mismatch_fails_the_case(self, sc):
        """A candidate that changes behaviour (here: the write tool leaves the
        plugin's allow list) must turn the suite red -- the selection function
        biting. The broker serves the COMPILED snapshot, so that is what the
        test swaps, exactly like a promotion would."""
        from dataclasses import replace as dc_replace

        suite = sc.compiled.eval_suites["planning-suite"]
        plug = sc.compiled.agent_plugins["planning-copilot"]
        stripped = plug.model_copy(deep=True)
        stripped.spec.tools.allow = [t for t in stripped.spec.tools.allow if t != "act_release_production_order"]
        original_compiled = sc.compiled
        sc.compiled = dc_replace(original_compiled, agent_plugins={"planning-copilot": stripped})
        try:
            async with sc.sessionmaker() as s:
                report = await sc.eval_runner.run(s, suite)
            case = report["cases"][0]
            assert not case["ok"], case
            assert case["actual"] == ["ok", "denied"]
        finally:
            sc.compiled = original_compiled
