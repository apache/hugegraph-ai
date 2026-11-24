# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio

import pytest
from fastmcp import Client

from hugegraph_mcp import server
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.tools import prepare_write
from hugegraph_mcp.toolsets import resolve_core_profile, tool_contract_version


def test_resolve_core_profile_and_contract_version():
    assert resolve_core_profile(None) == "compat"
    assert resolve_core_profile("LEAN") == "lean"
    assert tool_contract_version("core", "compat") == "2.0"
    assert tool_contract_version("core", "lean") == "3.0"
    assert tool_contract_version("legacy", "lean") == "2.0"
    with pytest.raises(ValueError):
        resolve_core_profile("unknown")


def test_lean_profile_omits_placeholders_and_gates_by_capabilities():
    async def _list_names(cfg: MCPConfig) -> set[str]:
        srv = server.create_server(cfg, toolset="core")
        async with Client(srv) as client:
            tools = await client.list_tools()
            return {t.name for t in tools}

    readonly_no_ai = asyncio.run(
        _list_names(MCPConfig(core_profile="lean", readonly=True, allow_ai=False, admin_mode=False))
    )
    assert "execute_gremlin_read_tool" not in readonly_no_ai
    assert "execute_gremlin_write_tool" not in readonly_no_ai
    assert "extract_graph_data_tool" not in readonly_no_ai
    assert "confirm_write_tool" not in readonly_no_ai
    assert "list_graphs_tool" not in readonly_no_ai
    assert {
        "inspect_graph_tool",
        "inspect_schema_tool",
        "query_graph_data_tool",
        "traverse_graph_tool",
        "prepare_write_tool",
        "get_write_status_tool",
        "list_write_plans_tool",
        "reconcile_write_tool",
    }.issubset(readonly_no_ai)

    with_ai_and_write = asyncio.run(
        _list_names(MCPConfig(core_profile="lean", readonly=False, allow_ai=True, admin_mode=False))
    )
    assert "extract_graph_data_tool" in with_ai_and_write
    assert "search_vid_embeddings_tool" in with_ai_and_write
    assert "confirm_write_tool" in with_ai_and_write
    assert "list_graphs_tool" not in with_ai_and_write


def test_prepare_write_rejects_invalid_kind_and_apply_mode():
    bad_kind = prepare_write.prepare_write(kind="drop_all")
    assert bad_kind["ok"] is False
    assert bad_kind["error"]["type"] == "VALIDATION_ERROR"

    bad_schema_mode = prepare_write.prepare_write(kind="schema", mode="apply")
    assert bad_schema_mode["ok"] is False
    assert bad_schema_mode["error"]["type"] == "VALIDATION_ERROR"


def test_prepare_write_dispatches_to_existing_planners(monkeypatch):
    calls = []
    monkeypatch.setattr(prepare_write, "manage_schema", lambda **kw: calls.append(("schema", kw)) or {"ok": True})
    monkeypatch.setattr(prepare_write, "manage_graph_data", lambda **kw: calls.append(("data", kw)) or {"ok": True})
    monkeypatch.setattr(
        prepare_write, "mutate_graph_properties", lambda **kw: calls.append(("props", kw)) or {"ok": True}
    )

    assert prepare_write.prepare_write(kind="schema", mode="validate", operations=[])["ok"] is True
    assert prepare_write.prepare_write(kind="import", graph_data={"vertices": []})["ok"] is True
    assert prepare_write.prepare_write(kind="delete", change_plan={"operations": []})["ok"] is True
    assert (
        prepare_write.prepare_write(
            kind="properties",
            target="vertex",
            operation="append",
            id="v1",
            properties={"age": 1},
        )["ok"]
        is True
    )
    assert [c[0] for c in calls] == ["schema", "data", "data", "props"]
    assert calls[1][1]["mode"] == "import"
    assert calls[1][1]["dry_run"] is True
    assert calls[1][1]["plan_tool_name"] == "prepare_write_tool"
