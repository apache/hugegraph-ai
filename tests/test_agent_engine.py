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
"""Builtin-llm engine (paradigm §3 form C): scripted-stub LLM drives the real
loop through the real broker, so every gate (catalog, budget, approval,
isolation, audit) is exercised exactly as production would.

The stub LLM is a queue of decisions -- deterministic, no network, no model.
"""
from __future__ import annotations

import json
import shutil

import httpx
import pytest
import pytest_asyncio

from ontogeny_ext_agent_llm import BuiltinLlmEngine
from ontogeny.api import build_app
from ontogeny.config import Settings
from ontogeny.demo import seed_from_package
from ontogeny.service import ServiceContext


class StubLLM:
    """Pops one scripted reply per chat() call; records prompts for asserts."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.prompts: list[dict] = []

    async def chat(self, messages, **kw):
        self.prompts.append(messages[-1])
        if not self.replies:
            return {"content": json.dumps({"final": "(stub exhausted)"})}
        reply = self.replies.pop(0)
        return {"content": reply}


def _plugin(engine_kind: str = "builtin-llm") -> str:
    return f"""\
apiVersion: ontogeny/v1
kind: AgentPlugin
metadata:
  name: planning-copilot
spec:
  engine: {{ kind: {engine_kind} }}
  principal:
    id: "agent:planning-copilot"
    Role: [planner]
    site: plant-north
  tools:
    allow: [describe_ontology, search_work_center, act_release_production_order]
  approval: {{ writes: confirm }}
  budget: {{ steps: 6, wall_ms: 60000, writes_per_session: 3 }}
"""


def _sc_settings(tmp_path, src) -> Settings:
    return Settings(
        dev_auth=True,
        db_dsn=f"sqlite+aiosqlite:///{tmp_path/'main.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}",
             "WMS_WEBHOOK": "https://wms.example.test/hook"},
    )


@pytest_asyncio.fixture()
async def sc(golden_pkg_path, tmp_path):
    root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, root)
    (root / "agents").mkdir(exist_ok=True)
    # the package ships its own plugins; these tests exercise one injected
    # plugin in isolation, so start the copy from an empty agents/ dir
    for f in (root / "agents").glob("*.yaml"):
        f.unlink()
    (root / "agents" / "copilot.yaml").write_text(_plugin(), encoding="utf-8")
    src = tmp_path / "erp.db"
    # the package owns its source data: execute its own seed SQL so the tables
    # match the ontology exactly
    seed_from_package(golden_pkg_path, src, force=True)
    ctx = ServiceContext(_sc_settings(tmp_path, src), str(root))
    await ctx.initialize()
    for t in ctx.compiled.objects:
        await ctx.sync(t)
    return ctx


def _wire(sc, llm) -> BuiltinLlmEngine:
    engine = BuiltinLlmEngine(sc, llm)
    # engines register as factories (extension style); pin this stub instance
    sc.agent_engines["builtin-llm"] = lambda sc: engine
    return engine


async def _session(sc, task: str) -> int:
    s = await sc.agents.open_session("planning-copilot", task)
    return s["id"]


class TestBuiltinLlmEngine:
    async def test_happy_path_reaches_final_and_records_steps(self, sc):
        llm = StubLLM([
            json.dumps({"thought": "Check which work centres are ACTIVE before planning.",
                        "tool": "search_work_center",
                        "args": {"filter": {"field": "status", "op": "eq", "value": "ACTIVE"}, "limit": 5}}),
            json.dumps({"thought": "WC-01 is ACTIVE with the largest capacity; I can conclude.",
                        "final": "Two ACTIVE work centres; WC-01 (CNC Machining Cell) is the release target."}),
        ])
        engine = _wire(sc, llm)
        sid = await _session(sc, "Find an ACTIVE work centre")

        result = await engine.drive(sid)

        assert result.status == "finished"
        assert "WC-01" in result.result["final"]
        sess = await sc.agents.get_session(sid)
        # a final answer ends the RUN, not the session: the session stays open
        # (with the round's conclusion recorded) until budget or human finish
        assert sess["status"] == "open"
        assert [s["tool"] for s in sess["steps"]] == ["search_work_center"]
        # I4: the step carries the tool result (transcript is replayable)
        assert sess["steps"][0]["detail"]["total"] == 2
        # the decision process is observable, not just the tool calls
        assert sess["steps"][0]["thought"] == "Check which work centres are ACTIVE before planning."
        assert sess["result"]["thought"] == "WC-01 is ACTIVE with the largest capacity; I can conclude."

    async def test_session_survives_final_and_redrives(self, sc):
        """The headline lifecycle: one final answer must NOT end the session.
        The next instruction drives the SAME session (run #2, steps tagged),
        and even an explicit human finish can be re-opened by driving again.
        Only the budget threshold terminates a session for real."""
        llm = StubLLM([
            json.dumps({"final": "round one done"}),
            json.dumps({"thought": "look around", "tool": "describe_ontology", "args": {}}),
            json.dumps({"final": "round two done"}),
            json.dumps({"final": "round three done"}),
        ])
        engine = _wire(sc, llm)
        sid = await _session(sc, "multi-round")

        # every drive goes through start_run (what the run endpoint does):
        # it carries the instruction and bumps the run counter
        await sc.agents.start_run(sid, task="round one")
        first = await engine.drive(sid)
        assert first.result["final"] == "round one done"
        assert (await sc.agents.get_session(sid))["status"] == "open"

        await sc.agents.start_run(sid, task="round two instruction")
        second = await engine.drive(sid)
        assert second.result["final"] == "round two done"
        sess = await sc.agents.get_session(sid)
        assert sess["status"] == "open"
        assert sess["task"] == "round two instruction"
        assert sess["run_count"] == 2
        assert [s["run_no"] for s in sess["steps"]] == [2]

        # a human finish ends it -- and a later drive re-opens it
        await sc.agents.finish_session(sid, {"summary": "paused by human"})
        assert (await sc.agents.get_session(sid))["status"] == "finished"
        await sc.agents.start_run(sid, task="round three")
        third = await engine.drive(sid)
        assert third.result["final"] == "round three done"
        sess = await sc.agents.get_session(sid)
        assert sess["status"] == "open"
        assert sess["run_count"] == 3

    async def test_missing_thought_is_tolerated(self, sc):
        """A driver that omits the reasoning text must not break the loop."""
        llm = StubLLM([
            json.dumps({"tool": "describe_ontology", "args": {}}),
            json.dumps({"final": "done."}),
        ])
        engine = _wire(sc, llm)
        sid = await _session(sc, "look at the ontology")

        await engine.drive(sid)

        sess = await sc.agents.get_session(sid)
        assert sess["steps"][0]["thought"] == ""

    async def test_write_blocks_then_resumes_after_approval(self, sc):
        llm = StubLLM([
            json.dumps({"tool": "act_release_production_order",
                        "args": {"parameters": {}, "target_id": "PO-1002"}}),
            # after resume: confirm and finish
            json.dumps({"final": "The release was approved and executed."}),
        ])
        engine = _wire(sc, llm)
        sid = await _session(sc, "release PO-1002")
        planner = {"id": "u-planner", "Role": ["planner"], "site": "plant-north"}

        first = await engine.drive(sid)
        assert first.status == "blocked_on_approval"
        sess = await sc.agents.get_session(sid)
        assert sess["status"] == "blocked_on_approval"
        # nothing executed yet
        async with sc.sessionmaker() as s:
            po = await sc.query.get(s, "production-order", "PO-1002",
                                    {"id": "auditor", "Role": ["auditor"]})
        assert po["status"] == "PLANNED"

        approval_id = first.result["approval_id"]
        out = await sc.agents.decide(approval_id, "approved", planner)
        assert out["status"] == "executed"

        second = await engine.drive(sid, resume=True)
        assert second.status == "finished"
        sess = await sc.agents.get_session(sid)
        # resumed run reached a final: the session is open again, drivable
        assert sess["status"] == "open"
        assert [s["tool"] for s in sess["steps"]] == ["act_release_production_order"]

    async def test_budget_exhaustion_stops_the_loop(self, sc):
        # keep calling tools forever; budget.steps=6 must stop it
        replies = [json.dumps({"tool": "describe_ontology", "args": {}}) for _ in range(10)]
        llm = StubLLM(replies)
        engine = _wire(sc, llm)
        sid = await _session(sc, "forever")

        result = await engine.drive(sid)
        assert result.status == "budget_exhausted"
        sess = await sc.agents.get_session(sid)
        assert sess["status"] == "budget_exhausted"
        assert sess["budget"]["steps_used"] == 6

    async def test_hallucinated_tool_feeds_back_then_gives_up(self, sc):
        llm = StubLLM([
            json.dumps({"tool": "delete_database", "args": {}}),
            json.dumps({"tool": "drop_all_tables", "args": {}}),
            json.dumps({"tool": "rm_rf", "args": {}}),
        ])
        engine = _wire(sc, llm)
        sid = await _session(sc, "chaos")

        result = await engine.drive(sid)
        # never executed; engine gave up with a structured error
        assert result.status == "finished"
        assert "gave up" in result.result["error"]
        sess = await sc.agents.get_session(sid)
        # a gave-up run keeps the session open (error recorded), not finished
        assert sess["status"] == "open"
        # hallucinated tools are outside the catalog: the broker refuses them
        # before any step is recorded, so nothing may have run at all
        assert sess["steps"] == []
        # the model saw its own failures in the follow-up prompts (self-correction)
        assert len(llm.prompts) == 3

    async def test_unparseable_json_raises_llm_error_ending_cleanly(self, sc):
        llm = StubLLM(["this is not json at all"])
        engine = _wire(sc, llm)
        sid = await _session(sc, "x")
        result = await engine.drive(sid)
        assert result.status == "finished"
        assert result.result["error"].startswith("llm:")
        # the LLM failure must not kill the session: it stays open, re-drivable
        sess = await sc.agents.get_session(sid)
        assert sess["status"] == "open"
        assert sess["result"]["error"].startswith("llm:")

    async def test_no_llm_is_a_config_error(self, sc):
        engine = _wire(sc, None)
        sid = await _session(sc, "x")
        with pytest.raises(RuntimeError, match="LLM_NOT_CONFIGURED"):
            await engine.drive(sid)

    async def test_running_session_is_isolated_from_external_calls(self, sc):
        """Paradigm §2: while an engine owns a session, external tool calls get
        a structured refusal instead of interleaving with the loop."""
        llm = StubLLM([json.dumps({"tool": "describe_ontology", "args": {}}),
                       json.dumps({"final": "done"})])
        _wire(sc, llm)
        sid = await _session(sc, "x")

        # the engine owns the session mid-run...
        await sc.agents.set_status(sid, "running")
        out = await sc.agents.call_tool(sid, "describe_ontology", {})
        assert out["outcome"] == "AGENT_SESSION_RUNNING"   # external caller
        out = await sc.agents.call_tool(sid, "describe_ontology", {}, engine=True)
        assert out["outcome"] == "ok"                       # the driving engine
        await sc.agents.set_status(sid, "open")
        out = await sc.agents.call_tool(sid, "describe_ontology", {})
        assert out["outcome"] == "ok"


# ------------------------------------------------------------- run endpoint


@pytest_asyncio.fixture()
async def client(golden_pkg_path, tmp_path):
    root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, root)
    (root / "agents").mkdir(exist_ok=True)
    # the package ships its own plugins; these tests exercise one injected
    # plugin in isolation, so start the copy from an empty agents/ dir
    for f in (root / "agents").glob("*.yaml"):
        f.unlink()
    (root / "agents" / "copilot.yaml").write_text(_plugin(), encoding="utf-8")
    src = tmp_path / "erp.db"
    seed_from_package(golden_pkg_path, src, force=True)
    sc = ServiceContext(_sc_settings(tmp_path, src), str(root))
    await sc.initialize()
    app = build_app(sc)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, sc


class TestRunEndpoint:
    async def test_run_without_llm_returns_structured_config_error(self, client):
        c, _ = client
        await c.post("/api/v1/agent/sessions", json={"plugin": "planning-copilot", "task": "x"})
        r = await c.post("/api/v1/agent/sessions/1/run")
        assert r.status_code == 500  # OOError surfaces as 500 with stable code
        assert r.json()["details"]["code"] == "LLM_NOT_CONFIGURED"

    async def test_run_dispatches_pull_plugin_with_howto(self, client):
        """external-pull plugins are driven FROM outside; /run returns the how-to.
        The compiled snapshot is swapped directly (what the dispatcher reads)."""
        from dataclasses import replace as dc_replace

        c, sc = client
        plug = sc.compiled.agent_plugins["planning-copilot"]
        pulled = plug.model_copy(deep=True)
        pulled.spec.engine.kind = "external-pull"
        original = sc.compiled
        sc.compiled = dc_replace(original,
                                 agent_plugins={"planning-copilot": pulled})
        try:
            r = await c.post("/api/v1/agent/sessions",
                             json={"plugin": "planning-copilot", "task": "x"})
            sid = r.json()["id"]
            r = await c.post(f"/api/v1/agent/sessions/{sid}/run")
            assert r.status_code == 500
            body = r.json()
            assert body["details"]["engine"] == "external-pull"
            assert "05-agent-governance.md" in body["details"]["how"]
        finally:
            sc.compiled = original


class TestUnlimitedBudget:
    async def test_steps_zero_never_exhausts(self, sc):
        """A session opened with steps=0 is UNLIMITED: the engine must keep
        driving past the number of steps that would exhaust a capped session
        (the gate used to fire at steps_used >= 0 -- instantly)."""
        llm = StubLLM([
            json.dumps({"thought": f"step {i}", "tool": "search_work_center",
                        "args": {"filter": {"field": "status", "op": "eq", "value": "ACTIVE"}, "limit": 1}})
            for i in range(8)
        ] + [json.dumps({"thought": "done", "final": "ok"})])
        engine = _wire(sc, llm)
        s = await sc.agents.open_session("planning-copilot", "unlimited drive",
                                         budget={"steps": 0, "wall_ms": 0,
                                                 "writes_per_session": 0})
        result = await engine.drive(s["id"])
        assert result.status == "finished", result.result
        sess = await sc.agents.get_session(s["id"])
        # the loop ended on the model's own final: session stays open
        assert sess["status"] == "open"
        assert len(sess["steps"]) == 8  # all 8 tool calls went through
        # and the bounded plugin default (6) would have exhausted exactly here
        assert sess["budget"]["steps"] == 0
