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
"""The optimization batch, each pinned by its own probe:

- C10  plugin-scoped tools/list (X-ONTOGENY-Plugin header) -- a view filter for
       large ontologies; enforcement stays in the broker
- C11  the engine's transcript window (total prompt budget, marked elision)
- C12  native function-calling when the provider advertises it; the strict
       JSON protocol remains the default and the fallback
- C13  the search tools teach their own filter DSL in the description
- C14  /admin/metrics counters from the platform's own tables
"""
from __future__ import annotations

import json
import shutil

import httpx
import pytest
import pytest_asyncio

from ontogeny.agent.catalog import build_catalog
from ontogeny.api import build_app
from ontogeny.config import Settings
from ontogeny.demo import seed_from_package
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
    allow: [describe_ontology, search_work_center]
  approval: { writes: confirm }
  budget: { steps: 6, wall_ms: 60000, writes_per_session: 3 }
"""


def _settings(tmp_path, src) -> Settings:
    return Settings(
        dev_auth=True,
        db_dsn=f"sqlite+aiosqlite:///{tmp_path/'main.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}",
             "WMS_WEBHOOK": "https://wms.example.test/hook"})


async def _make(golden_pkg_path, tmp_path):
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
    return await _make(golden_pkg_path, tmp_path)


# ---------------------------------------------------------------------- C10


class TestPluginScopedListTools:
    async def test_header_narrows_the_view_not_the_law(self, golden_pkg_path, tmp_path):
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        sc = await _make(golden_pkg_path, tmp_path)
        app = build_app(sc)
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as hc:
                async with streamable_http_client("http://test/mcp", http_client=hc) as streams:
                    async with ClientSession(streams[0], streams[1]) as sess:
                        await sess.initialize()
                        full = await sess.list_tools()
                        full_names = {t.name for t in full.tools}
                        assert "search_material" in full_names  # whole catalog by default

                        scoped = httpx.AsyncClient(
                            transport=transport, base_url="http://test",
                            headers={"X-ONTOGENY-Plugin": "planning-copilot"})
                        async with streamable_http_client("http://test/mcp",
                                                          http_client=scoped) as streams2:
                            async with ClientSession(streams2[0], streams2[1]) as sess2:
                                await sess2.initialize()
                                narrow = await sess2.list_tools()
                                names = {t.name for t in narrow.tools}
                                # the plugin's effective tools + session tools
                                assert names == {"describe_ontology", "search_work_center",
                                                 "agent_open_session", "agent_get_session",
                                                 "agent_list_sessions", "agent_finish_session"}
                                # a VIEW filter: the tool still EXISTS and the
                                # broker still enforces the plugin's real
                                # catalog (narrowed per the plugin, not the
                                # header-less anonymous exploration path)
                                res = await sess2.call_tool(
                                    "search_material", {"limit": 1, "plugin": "planning-copilot"})
                                assert res.is_error is False
                                assert res.structured_content["outcome"] == "AGENT_TOOL_NOT_ALLOWED"

    async def test_unknown_plugin_in_header_is_an_error(self, golden_pkg_path, tmp_path):
        from mcp.shared.exceptions import MCPError

        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        sc = await _make(golden_pkg_path, tmp_path)
        app = build_app(sc)
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                    transport=transport, base_url="http://test",
                    headers={"X-ONTOGENY-Plugin": "no-such-plugin"}) as hc:
                async with streamable_http_client("http://test/mcp", http_client=hc) as streams:
                    async with ClientSession(streams[0], streams[1]) as sess:
                        await sess.initialize()
                        with pytest.raises(MCPError):
                            await sess.list_tools()


# ----------------------------------------------------------------- C11 + C12


class _RecordingLLM:
    """Records every prompt; replies from a script."""

    def __init__(self, replies, supports_tools=False):
        self.replies = list(replies)
        self.prompts = []
        self.supports_tool_calls = supports_tools
        self.saw_tools_param = None

    async def chat(self, messages, **kw):
        self.prompts.append(messages)
        self.saw_tools_param = kw.get("tools")
        if not self.replies:
            return {"content": json.dumps({"final": "(exhausted)"})}
        return self.replies.pop(0)


class TestEngineContextAndProtocol:
    async def test_transcript_window_elides_the_middle(self, sc):
        from ontogeny_ext_agent_llm import BuiltinLlmEngine

        llm = _RecordingLLM([json.dumps({"final": "done"})])
        engine = BuiltinLlmEngine(sc, llm)
        # a fake transcript far over the 60k budget: keep the newest steps
        big = [{"thought": "t" * 500, "tool": "describe_ontology",
                "args": {}, "outcome": "ok", "result": {"x": "y" * 500}}
               for _ in range(200)]
        bounded = engine._bounded(big)
        assert len(bounded) < len(big)
        assert bounded[0].get("_elided", "").startswith("1") or "omitted" in bounded[0].get("_elided", "")
        assert bounded[-1] == big[-1]  # newest steps survive
        assert len(json.dumps(bounded)) <= 60_000 + 200

    async def test_small_transcript_passes_through(self, sc):
        from ontogeny_ext_agent_llm import BuiltinLlmEngine

        engine = BuiltinLlmEngine(sc, None)
        small = [{"thought": "t", "tool": "x", "args": {}, "outcome": "ok", "result": None}]
        assert engine._bounded(small) is small

    async def test_native_tool_calls_drive_the_same_loop(self, sc):
        """A provider that advertises function-calling gets OpenAI-style tool
        schemas and its tool_calls reply drives the real loop -- same trail,
        same gates, same MCP transport as the JSON protocol."""
        from ontogeny_ext_agent_llm import BuiltinLlmEngine

        llm = _RecordingLLM(
            supports_tools=True,
            replies=[
                {"content": "checking the active set first",
                 "tool_calls": [{"function": {"name": "search_work_center",
                                              "arguments": json.dumps(
                                                  {"filter": {"field": "status", "op": "eq",
                                                              "value": "ACTIVE"}, "limit": 5})}}]},
                {"content": json.dumps({"final": "two active centres"})},
            ])
        engine = BuiltinLlmEngine(sc, llm)
        sid = (await sc.agents.open_session("planning-copilot", "native"))["id"]
        result = await engine.drive(sid)
        assert result.status == "finished"
        assert engine.last_transport == "mcp"
        assert llm.saw_tools_param, "provider must receive tool schemas"
        assert llm.saw_tools_param[0]["function"]["name"] == "describe_ontology"
        sess = await sc.agents.get_session(sid)
        assert [s["tool"] for s in sess["steps"]] == ["search_work_center"]
        assert sess["steps"][0]["thought"] == "checking the active set first"
        assert sess["steps"][0]["detail"]["total"] == 2

    async def test_native_final_answer_without_tool_call(self, sc):
        from ontogeny_ext_agent_llm import BuiltinLlmEngine

        llm = _RecordingLLM(supports_tools=True,
                            replies=[{"content": "nothing to do"}])
        engine = BuiltinLlmEngine(sc, llm)
        sid = (await sc.agents.open_session("planning-copilot", "native-final"))["id"]
        result = await engine.drive(sid)
        assert result.status == "finished"
        assert result.result["final"] == "nothing to do"


# ---------------------------------------------------------------------- C13


class TestFilterDslTeaching:
    def test_search_descriptions_teach_the_dsl(self, sc):
        catalog = build_catalog(sc.compiled)
        tdef = catalog["search_work_center"]
        assert "eq" in tdef.description and "and" in tdef.description
        assert "field" in tdef.description
        # the schema's filter property carries it too (MCP clients see it)
        assert "eq" in tdef.input_schema["properties"]["filter"]["description"]


# ---------------------------------------------------------------------- C14


class TestMetricsEndpoint:
    async def test_counters_shape_and_content(self, golden_pkg_path, tmp_path):
        sc = await _make(golden_pkg_path, tmp_path)
        app = build_app(sc)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     headers={"X-Ontogeny-Principal": json.dumps({"id": "ci-admin", "is_admin": True})}) as c:
            # generate some traffic (query telemetry rides the POST search path)
            await c.post("/api/v1/objects/work-center/query", json={"limit": 3},
                         headers={"X-Ontogeny-Principal": json.dumps({"id": "u", "Role": ["auditor"]})})
            sid = (await c.post("/api/v1/agent/sessions",
                                json={"plugin": "planning-copilot", "task": "metrics"})).json()["id"]
            await c.post(f"/api/v1/agent/sessions/{sid}/tools/describe_ontology", json={})

            r = await c.get("/api/v1/admin/metrics")
            assert r.status_code == 200
            body = r.json()
            assert {"queries", "actions", "agent", "outbox", "generated_at"} <= set(body)
            assert body["queries"]["total"] >= 1
            assert body["agent"]["sessions"]["total"] >= 1
            assert body["agent"]["steps_recorded"] >= 1
