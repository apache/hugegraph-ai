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
"""The MCP tool surface: one door, two transports.

Everything an external MCP client can reach is tested here at the protocol
level (an in-memory MCP client session, exactly what the builtin engine
drives) and over the wire (streamable HTTP at /mcp through the real FastAPI
app). The governance assertions are the point: a session-scoped MCP call
must land in the same broker gates as the REST session protocol -- budget
charged, catalog enforced, writes parked for human approval, steps recorded.

Sessions are opened INSIDE each test (not an async fixture): the in-memory
MCP transport carries anyio cancel scopes that must exit in the task that
entered them, and pytest-asyncio tears fixtures down in another task.
"""
from __future__ import annotations

import json
import shutil

import httpx
import pytest_asyncio

from ontogeny.api import build_app
from ontogeny.config import Settings
from ontogeny.demo import seed_from_package
from ontogeny.mcp_server import MCP_HTTP_PATH, in_process_mcp_session
from ontogeny.service import ServiceContext

PLUGIN = """\
apiVersion: ontogeny/v1
kind: AgentPlugin
metadata:
  name: planning-copilot
spec:
  engine: { kind: builtin-llm }
  principal:
    id: "agent:planning-copilot"
    Role: [planner]
    site: plant-north
  tools:
    allow: [describe_ontology, search_work_center, act_release_production_order]
  approval: { writes: confirm }
  budget: { steps: 4, wall_ms: 60000, writes_per_session: 3 }
"""


def _settings(tmp_path, src) -> Settings:
    return Settings(
        dev_auth=True,  # the /mcp bearer gate rejects anonymous when off
        db_dsn=f"sqlite+aiosqlite:///{tmp_path/'main.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}",
             "WMS_WEBHOOK": "https://wms.example.test/hook"},
    )


async def _make_sc(golden_pkg_path, tmp_path):
    root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, root)
    (root / "agents").mkdir(exist_ok=True)
    for f in (root / "agents").glob("*.yaml"):
        f.unlink()
    (root / "agents" / "copilot.yaml").write_text(PLUGIN, encoding="utf-8")
    src = tmp_path / "erp.db"
    seed_from_package(golden_pkg_path, src, force=True)
    sc = ServiceContext(_settings(tmp_path, src), str(root))
    await sc.initialize()
    for t in sc.compiled.objects:
        await sc.sync(t)
    return sc


@pytest_asyncio.fixture()
async def sc(golden_pkg_path, tmp_path):
    return await _make_sc(golden_pkg_path, tmp_path)


async def _open(mcp, plugin: str = "planning-copilot", task: str = "t") -> int:
    out = await mcp.call_tool("agent_open_session", {"plugin": plugin, "task": task})
    assert out.get("id"), out
    return out["id"]


class TestProtocolSurface:
    async def test_tool_list_mirrors_the_catalog_plus_session_tools(self, sc):
        from ontogeny.agent.catalog import build_catalog

        async with in_process_mcp_session(sc) as mcp:
            names = {t["name"] for t in await mcp.list_tools()}
            assert set(build_catalog(sc.compiled)) <= names
            assert {"agent_open_session", "agent_get_session",
                    "agent_list_sessions", "agent_finish_session"} <= names
            # the reserved transport arguments ride on every tool's schema
            tool = next(t for t in await mcp.list_tools()
                        if t["name"] == "search_work_center")
            assert {"plugin", "session_id", "thought"} <= set(tool["input_schema"]["properties"])

    async def test_governed_call_records_step_thought_and_budget(self, sc):
        async with in_process_mcp_session(sc) as mcp:
            sid = await _open(mcp, task="find active work centres")
            out = await mcp.call_tool("search_work_center", {
                "filter": {"field": "status", "op": "eq", "value": "ACTIVE"}, "limit": 5,
                "session_id": sid, "plugin": "planning-copilot",
                "thought": "planning needs the active set"})
            assert out["outcome"] == "ok"
            assert out["detail"]["total"] == 2

            sess = await sc.agents.get_session(sid)
            assert [s["tool"] for s in sess["steps"]] == ["search_work_center"]
            assert sess["steps"][0]["thought"] == "planning needs the active set"
            assert sess["budget"]["steps_used"] == 1

    async def test_write_parks_for_human_approval_like_the_rest_protocol(self, sc):
        """The approval gate (M2) must hold through the MCP transport too."""
        async with in_process_mcp_session(sc) as mcp:
            sid = await _open(mcp, task="release PO-1002")
            out = await mcp.call_tool("act_release_production_order", {
                "parameters": {}, "target_id": "PO-1002",
                "session_id": sid, "plugin": "planning-copilot"})
            assert out["outcome"] == "pending_approval"
            approval_id = out["approval_id"]

        async with sc.sessionmaker() as s:
            po = await sc.query.get(s, "production-order", "PO-1002",
                                    {"id": "auditor", "Role": ["auditor"]})
        assert po["status"] == "PLANNED"  # nothing executed yet

        planner = {"id": "u-planner", "Role": ["planner"], "site": "plant-north"}
        decision = await sc.agents.decide(approval_id, "approved", planner)
        assert decision["status"] == "executed"
        async with sc.sessionmaker() as s:
            po = await sc.query.get(s, "production-order", "PO-1002",
                                    {"id": "auditor", "Role": ["auditor"]})
        assert po["status"] == "RELEASED"

    async def test_sessionless_write_is_refused(self, sc):
        async with in_process_mcp_session(sc) as mcp:
            out = await mcp.call_tool("act_release_production_order",
                                      {"parameters": {}, "target_id": "PO-1002"})
            assert out["outcome"] == "WRITE_REQUIRES_SESSION"

    async def test_sessionless_read_narrows_to_the_plugin_catalog(self, sc):
        async with in_process_mcp_session(sc) as mcp:
            # inside the plugin's list: reads fine under the plugin principal
            out = await mcp.call_tool("search_work_center",
                                      {"limit": 2, "plugin": "planning-copilot"})
            assert out["outcome"] == "ok"
            # outside it: refused even though the tool exists (I1)
            out = await mcp.call_tool("search_material",
                                      {"limit": 2, "plugin": "planning-copilot"})
            assert out["outcome"] == "AGENT_TOOL_NOT_ALLOWED"

    async def test_allow_list_enforced_inside_sessions_too(self, sc):
        async with in_process_mcp_session(sc) as mcp:
            sid = await _open(mcp)
            out = await mcp.call_tool("search_material",
                                      {"limit": 2, "session_id": sid,
                                       "plugin": "planning-copilot"})
            assert out["outcome"] == "AGENT_TOOL_NOT_ALLOWED"

    async def test_budget_exhaustion_is_a_structured_outcome(self, sc):
        async with in_process_mcp_session(sc) as mcp:
            sid = await _open(mcp)
            out = {}
            for _ in range(5):  # budget.steps=4: the 5th call must be refused
                out = await mcp.call_tool("describe_ontology",
                                          {"session_id": sid, "plugin": "planning-copilot"})
            assert out["outcome"] == "AGENT_BUDGET_EXCEEDED"
            sess = await sc.agents.get_session(sid)
            assert sess["budget"]["steps_used"] == 4

    async def test_unknown_tool_maps_to_not_found(self, sc):
        async with in_process_mcp_session(sc) as mcp:
            out = await mcp.call_tool("delete_database", {})
            assert out["outcome"] == "NOT_FOUND"

    async def test_running_session_isolation_engine_vs_external(self, sc):
        """§2: while the engine owns a running session, an external MCP caller
        gets the structured refusal; the engine-mode surface drives on."""
        sid = (await sc.agents.open_session("planning-copilot", "x"))["id"]
        await sc.agents.set_status(sid, "running")

        async with in_process_mcp_session(sc, engine_mode=False) as external:
            out = await external.call_tool("describe_ontology",
                                           {"session_id": sid, "plugin": "planning-copilot"})
            assert out["outcome"] == "AGENT_SESSION_RUNNING"
        async with in_process_mcp_session(sc) as engine_client:
            out = await engine_client.call_tool(
                "describe_ontology", {"session_id": sid, "plugin": "planning-copilot"})
            assert out["outcome"] == "ok"

    async def test_session_lifecycle_over_pure_mcp(self, sc):
        async with in_process_mcp_session(sc) as mcp:
            sid = await _open(mcp, task="look around")
            out = await mcp.call_tool("agent_get_session", {"session_id": sid})
            assert out["status"] == "open"
            assert "search_work_center" in out["tools"]

            out = await mcp.call_tool("agent_list_sessions", {"plugin": "planning-copilot"})
            assert any(s["id"] == sid for s in out["sessions"])

            out = await mcp.call_tool("agent_finish_session",
                                      {"session_id": sid, "result": {"final": "done"}})
            assert out["status"] == "finished"
            out = await mcp.call_tool("agent_get_session", {"session_id": sid})
            assert out["result"]["final"] == "done"


class TestWireSurface:
    """The mounted /mcp endpoint, driven by a real streamable-HTTP MCP client
    over the ASGI transport (no sockets): what Claude Desktop et al. do."""

    async def test_streamable_http_end_to_end(self, golden_pkg_path, tmp_path):
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        sc = await _make_sc(golden_pkg_path, tmp_path)
        app = build_app(sc)
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            assert any(getattr(r, "path", None) == MCP_HTTP_PATH for r in app.routes)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as hc:
                async with streamable_http_client(f"http://test{MCP_HTTP_PATH}",
                                                   http_client=hc) as streams:
                    async with ClientSession(streams[0], streams[1]) as sess:
                        await sess.initialize()
                        tools = await sess.list_tools()
                        assert "search_work_center" in {t.name for t in tools.tools}

                        opened = await sess.call_tool(
                            "agent_open_session",
                            {"plugin": "planning-copilot", "task": "wire"})
                        assert opened.is_error is False
                        sid = opened.structured_content["id"]

                        res = await sess.call_tool(
                            "search_work_center",
                            {"filter": {"field": "status", "op": "eq", "value": "ACTIVE"},
                             "limit": 5, "session_id": sid,
                             "plugin": "planning-copilot"})
                        assert res.is_error is False
                        assert res.structured_content["outcome"] == "ok"
                        assert res.structured_content["detail"]["total"] == 2

    async def test_mcp_route_is_never_shadowed(self, golden_pkg_path, tmp_path):
        sc = await _make_sc(golden_pkg_path, tmp_path)
        app = build_app(sc)
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as hc:
                r = await hc.post(MCP_HTTP_PATH, json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "t", "version": "0"}}},
                    headers={"Accept": "application/json, text/event-stream"})
                # the governed MCP route answers (a 4xx JSON-RPC error at
                # worst), never the SPA fallback HTML
                assert r.status_code < 500
                assert "text/html" not in r.headers.get("content-type", "")


class TestEngineSpeaksMcp:
    """The builtin engine dogfoods the surface: its tool calls travel the MCP
    protocol (in-memory session), not an in-process shortcut."""

    @staticmethod
    def _stub_llm(replies: list[str]):
        class StubLLM:
            def __init__(self):
                self.replies = list(replies)

            async def chat(self, messages, **kw):
                if not self.replies:
                    return {"content": json.dumps({"final": "(exhausted)"})}
                return {"content": self.replies.pop(0)}
        return StubLLM()

    async def test_engine_records_mcp_transport(self, sc):
        from ontogeny_ext_agent_llm import BuiltinLlmEngine

        engine = BuiltinLlmEngine(sc, self._stub_llm([
            json.dumps({"thought": "look", "tool": "describe_ontology", "args": {}}),
            json.dumps({"final": "done via mcp"}),
        ]))
        sid = (await sc.agents.open_session("planning-copilot", "x"))["id"]
        result = await engine.drive(sid)
        assert result.status == "finished"
        assert engine.last_transport == "mcp"
        sess = await sc.agents.get_session(sid)
        assert [s["tool"] for s in sess["steps"]] == ["describe_ontology"]

    async def test_engine_falls_back_without_the_extra(self, sc, monkeypatch):
        import ontogeny.mcp_server as mod

        def _missing(_sc):
            raise ImportError("mcp")

        monkeypatch.setattr(mod, "in_process_mcp_session", _missing)
        from ontogeny_ext_agent_llm import BuiltinLlmEngine

        engine = BuiltinLlmEngine(sc, self._stub_llm([]))
        sid = (await sc.agents.open_session("planning-copilot", "x"))["id"]
        result = await engine.drive(sid)
        assert result.status == "finished"
        assert engine.last_transport == "broker"


class TestRefreshOnPromote:
    async def test_refresh_rebuilds_tool_registrations(self, sc):
        from dataclasses import replace

        from ontogeny.mcp_server import McpSurface

        # a promote that drops the object type must drop its tool: refresh()
        # is what _rebuild_services calls on every recompile
        slim = replace(sc.compiled,
                       objects={k: v for k, v in sc.compiled.objects.items()
                                if k != "work-center"})
        assert "work-center" not in slim.objects

        surface = McpSurface(type("FakeSc", (), {"compiled": slim})(), engine_mode=True)
        surface.build()
        assert surface.server is not None
        tools = await surface.server.list_tools()
        names = {t.name for t in tools}
        assert "search_work_center" not in names
        assert "search_production_order" in names
