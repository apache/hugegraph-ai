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

"""Tests for shared tools, toolset selection, and admin gates."""

import asyncio
import logging
import warnings
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastmcp import Client

from hugegraph_mcp import server
from hugegraph_mcp.envelope import envelope_ok
from hugegraph_mcp.write_contract import LEGACY_DEPRECATION_CODE


async def _list_mcp_tools():
    list_tools = getattr(server.mcp, "_mcp_list_tools", None)
    if list_tools is None:
        list_tools = server.mcp._list_tools
    return await list_tools()


def _assert_envelope_shape(result):
    assert set(result) == {"ok", "data", "error", "warnings", "next_actions", "meta"}
    assert result["meta"]["request_id"].startswith("req-")
    assert "graph" in result["meta"]
    assert "graphspace" in result["meta"]
    assert "readonly" in result["meta"]
    assert "duration_ms" in result["meta"]


LEGACY_TOOL_NAMES = {
    "inspect_graph_tool",
    "generate_gremlin_tool",
    "execute_gremlin_read_tool",
    "extract_graph_data_tool",
    "design_schema_tool",
    "apply_schema_tool",
    "import_graph_data_tool",
    "delete_graph_data_tool",
    "refresh_vid_embeddings_tool",
    "execute_gremlin_write_tool",
}

CORE_TOOL_NAMES = LEGACY_TOOL_NAMES | {
    "confirm_write_tool",
    "get_write_status_tool",
    "inspect_schema_tool",
    "query_graph_data_tool",
    "traverse_graph_tool",
    "search_vid_embeddings_tool",
    "get_task_status_tool",
    "list_tasks_tool",
    "cancel_task_tool",
    "list_graphs_tool",
    "list_write_plans_tool",
    "cancel_write_plan_tool",
    "reconcile_write_tool",
    "mutate_graph_properties_tool",
}


def test_public_tool_contract_lists_core_tools_by_default(monkeypatch):
    monkeypatch.delenv("HUGEGRAPH_MCP_TOOLSET", raising=False)

    async def _tool_names():
        tools = await _list_mcp_tools()
        return {tool.name for tool in tools}

    assert asyncio.run(_tool_names()) == CORE_TOOL_NAMES


def test_import_graph_data_tool_runtime_input_schema():
    async def _input_schema():
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            tool = next(item for item in tools if item.name == "import_graph_data_tool")
            return tool.input_schema

    input_schema = asyncio.run(_input_schema())

    assert set(input_schema["properties"]) == {
        "mode",
        "text",
        "graph_schema",
        "example_prompt",
        "graph_data",
        "dry_run",
        "confirm",
        "plan_hash",
        "nonce",
        "expires_at",
    }
    assert "table_data" not in input_schema["properties"]
    assert "mapping" not in input_schema["properties"]
    assert input_schema["required"] == ["mode"]


def test_public_tool_contract_can_reload_as_legacy(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_TOOLSET", "legacy")
    import importlib

    import hugegraph_mcp.server as server_module

    importlib.reload(server_module)

    async def _tool_names():
        list_tools = getattr(server_module.mcp, "_mcp_list_tools", None)
        if list_tools is None:
            list_tools = server_module.mcp._list_tools
        tools = await list_tools()
        return {tool.name for tool in tools}

    try:
        assert asyncio.run(_tool_names()) == LEGACY_TOOL_NAMES
    finally:
        monkeypatch.delenv("HUGEGRAPH_MCP_TOOLSET", raising=False)
        importlib.reload(server_module)


@pytest.mark.parametrize("value", ["typo", "", "  ", "v2", "CORE"])
def test_invalid_toolsets_prevent_startup(monkeypatch, value):
    import importlib

    try:
        monkeypatch.setenv("HUGEGRAPH_MCP_TOOLSET", value)
        with pytest.raises(ValueError, match="expected core or legacy"):
            importlib.reload(server)
    finally:
        monkeypatch.delenv("HUGEGRAPH_MCP_TOOLSET", raising=False)
        importlib.reload(server)


@pytest.mark.parametrize(
    ("value", "canonical", "expected_tools"),
    [
        ("core", "core", CORE_TOOL_NAMES),
        ("legacy", "legacy", LEGACY_TOOL_NAMES),
        ("v2_core", "core", CORE_TOOL_NAMES),
        ("v1", "legacy", LEGACY_TOOL_NAMES),
        (" core ", "core", CORE_TOOL_NAMES),
    ],
)
def test_toolset_selection_metadata_and_startup_snapshot(monkeypatch, caplog, value, canonical, expected_tools):
    import importlib

    try:
        monkeypatch.setenv("HUGEGRAPH_MCP_TOOLSET", value)
        with caplog.at_level(logging.WARNING, logger="hugegraph_mcp.toolsets"):
            importlib.reload(server)
        deprecated = [record for record in caplog.records if "is deprecated" in record.message]
        assert len(deprecated) == int(value in {"v1", "v2_core"})
        # A later environment edit must not change metadata or behavior without a restart.
        monkeypatch.setenv("HUGEGRAPH_MCP_TOOLSET", "legacy" if canonical == "core" else "core")
        monkeypatch.setattr(server, "inspect_graph", lambda **kwargs: envelope_ok({"toolset": kwargs["toolset"]}))
        calls = []
        monkeypatch.setattr(server, "manage_schema", lambda **kwargs: calls.append(kwargs) or envelope_ok({}))

        async def check_tools():
            async with Client(server.mcp) as client:
                registered = {tool.name for tool in await client.list_tools()}
                assert registered == expected_tools
                for filename in ("README.md", "README.zh-CN.md"):
                    content = (Path(__file__).resolve().parents[1] / filename).read_text(encoding="utf-8")
                    documented = set()
                    for line in content.splitlines():
                        cells = [cell.strip() for cell in line.split("|")]
                        if len(cells) >= 4 and cells[1].endswith("_tool`") and canonical in cells[2]:
                            documented.add(cells[1].strip("`"))
                    assert documented == registered, filename
                result = await client.call_tool("inspect_graph_tool", {})
                return result.data

        result = asyncio.run(check_tools())
        assert result["data"]["toolset"] == canonical
        assert result["meta"]["toolset"] == canonical
        assert result["meta"]["mcp_tool_contract_version"] == "2.0"
        applied = server.apply_schema_tool(mode="apply", operations=[])
        if canonical == "legacy":
            assert applied["error"]["type"] == "FEATURE_DISABLED"
            assert not calls
        else:
            assert applied["ok"]
            assert len(calls) == 1
    finally:
        monkeypatch.delenv("HUGEGRAPH_MCP_TOOLSET", raising=False)
        importlib.reload(server)


def test_public_tool_argument_models_do_not_emit_schema_shadow_warning():
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")

        async def _list_tools():
            return await _list_mcp_tools()

        asyncio.run(_list_tools())

    assert not any("shadows an attribute" in str(item.message) for item in captured)


def test_server_import_restores_logging_globals():
    assert logging.root.manager.disable < logging.CRITICAL


def test_generate_gremlin_tool_execute_fails_closed_even_for_admin(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    mock = Mock()
    monkeypatch.setattr(server, "generate_gremlin", mock)

    result = server.generate_gremlin_tool(
        query="count vertices",
        execute=True,
        output_types=["vertex"],
    )

    _assert_envelope_shape(result)
    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert "hard-budget contract is incomplete" in result["error"]["message"]
    assert result["error"]["details"]["post_materialization_limits_are_hard_budgets"] is False
    mock.assert_not_called()


def test_generate_gremlin_tool_still_generates_without_execution(monkeypatch):
    expected = envelope_ok({"gremlin": "g.V().count()"})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "generate_gremlin", mock)

    result = server.generate_gremlin_tool(query="count vertices", execute=False)

    _assert_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with(
        query="count vertices",
        execute=False,
        output_types=None,
        limit_policy="reject_unbounded",
    )


def test_inspect_graph_tool_adds_contract_fields(monkeypatch):
    expected = envelope_ok({"graph": "hugegraph"})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "inspect_graph", mock)

    result = server.inspect_graph_tool()

    _assert_envelope_shape(result)
    assert result["data"]["mcp_tool_contract_version"] == "2.0"
    assert result["data"]["toolset"] == "core"
    assert result["meta"]["mcp_tool_contract_version"] == "2.0"
    assert result["meta"]["toolset"] == "core"
    mock.assert_called_once_with(include_raw_schema=False, include_counts=False, toolset="core")

    server.inspect_graph_tool(include_counts=True)
    mock.assert_called_with(include_raw_schema=False, include_counts=True, toolset="core")


def test_execute_gremlin_read_tool_fails_closed_even_for_admin(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    mock = Mock()
    monkeypatch.setattr(server, "execute_gremlin_read", mock)

    result = server.execute_gremlin_read_tool(gremlin_query="g.V().limit(3)")

    _assert_envelope_shape(result)
    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    capabilities = result["error"]["details"]["required_capabilities"]
    assert result["error"]["details"]["integration_contract_verified"] is False
    assert capabilities["gremlin_result_item_limit"]["status"] == "unknown"
    assert capabilities["http_streaming_response_limit"]["status"] == "verified_unsupported"
    mock.assert_not_called()


def test_extract_graph_data_tool_routes_to_extract_graph_data(monkeypatch):
    expected = envelope_ok({"graph_data": {"vertices": [], "edges": []}})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "extract_graph_data", mock)

    result = server.extract_graph_data_tool(
        text="Alice knows Bob.",
        graph_schema={"vertexlabels": ["person"]},
        example_prompt="extract people",
    )

    _assert_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with(
        text="Alice knows Bob.",
        schema={"vertexlabels": ["person"]},
        example_prompt="extract people",
    )


def test_design_schema_tool_routes_to_manage_schema_design(monkeypatch):
    expected = envelope_ok({"suggestions": []})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "manage_schema", mock)

    result = server.design_schema_tool(operations=[{"op": "add_vertex_label"}])

    _assert_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with(mode="design", operations=[{"op": "add_vertex_label"}])


def test_apply_schema_tool_validate_routes_to_manage_schema(monkeypatch):
    expected = envelope_ok({"valid": True})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "manage_schema", mock)

    result = server.apply_schema_tool(mode="validate", operations=[{"op": "add_vertex_label"}])

    _assert_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with(
        mode="validate",
        operations=[{"op": "add_vertex_label"}],
        confirm=False,
        plan_hash=None,
        nonce=None,
        expires_at=None,
    )


def test_apply_schema_tool_dry_run_routes_to_manage_schema(monkeypatch):
    expected = envelope_ok({"plan_hash": "abc123"})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "manage_schema", mock)

    result = server.apply_schema_tool(mode="dry_run", operations=[{"op": "add_vertex_label"}])

    _assert_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with(
        mode="dry_run",
        operations=[{"op": "add_vertex_label"}],
        confirm=False,
        plan_hash=None,
        nonce=None,
        expires_at=None,
    )


def test_apply_schema_tool_apply_routes_in_core(monkeypatch):
    expected = envelope_ok({"status": "planned"})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "manage_schema", mock)

    result = server.apply_schema_tool(
        mode="apply",
        operations=[{"type": "create_property_key", "name": "age"}],
        confirm=True,
        plan_hash="hash",
        nonce="nonce",
        expires_at=9999999999,
    )

    _assert_envelope_shape(result)
    assert result["ok"] is True
    assert result["warnings"][0].startswith(LEGACY_DEPRECATION_CODE)
    mock.assert_called_once_with(
        mode="apply",
        operations=[{"type": "create_property_key", "name": "age"}],
        confirm=True,
        plan_hash="hash",
        nonce="nonce",
        expires_at=9999999999,
    )


@pytest.mark.parametrize(
    ("tool_name", "dependency_name", "arguments"),
    [
        (
            "apply_schema_tool",
            "manage_schema",
            {
                "mode": "dry_run",
                "operations": [{"type": "create_property_key", "name": "age"}],
            },
        ),
        (
            "mutate_graph_properties_tool",
            "mutate_graph_properties",
            {
                "target": "vertex",
                "operation": "append",
                "id": "1",
                "properties": {"age": 42},
            },
        ),
        (
            "import_graph_data_tool",
            "manage_graph_data",
            {"mode": "ingest", "graph_data": {"vertices": [], "edges": []}},
        ),
        (
            "delete_graph_data_tool",
            "manage_graph_data",
            {"change_plan": {"operations": []}},
        ),
    ],
)
def test_legacy_write_wrappers_reject_partial_locator_before_business_logic(
    monkeypatch,
    tool_name,
    dependency_name,
    arguments,
):
    mock = Mock()
    monkeypatch.setattr(server, dependency_name, mock)

    result = getattr(server, tool_name)(**arguments, plan_hash="hash-only")

    _assert_envelope_shape(result)
    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["source"] == tool_name
    mock.assert_not_called()


def test_canonical_confirm_wrapper_passes_only_plan_id(monkeypatch):
    expected = envelope_ok({"plan_id": "wp-1", "status": "APPLIED"})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "confirm_write", mock)

    result = server.confirm_write_tool(plan_id="wp-1")

    _assert_envelope_shape(result)
    assert result["ok"] is True
    mock.assert_called_once_with(plan_id="wp-1")


def test_apply_schema_tool_apply_returns_feature_disabled_in_legacy(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_TOOLSET", "legacy")
    import importlib

    import hugegraph_mcp.server as server_module

    importlib.reload(server_module)
    result = server_module.apply_schema_tool(mode="apply", operations=[{"op": "test"}])

    _assert_envelope_shape(result)
    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert result["error"]["source"] == "apply_schema_tool"
    assert "apply" in result["error"]["message"].lower()
    monkeypatch.delenv("HUGEGRAPH_MCP_TOOLSET", raising=False)
    importlib.reload(server_module)


def test_delete_graph_data_tool_routes_to_manage_graph_data_delete(monkeypatch):
    expected = envelope_ok({"valid": True, "preview": [], "plan_hash": "abc123"})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "manage_graph_data", mock)
    change_plan = {
        "operations": [
            {
                "op": "delete_vertex",
                "label": "person",
                "match": {"name": "Alice"},
            }
        ]
    }

    result = server.delete_graph_data_tool(change_plan=change_plan)

    _assert_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with(
        mode="delete",
        change_plan=change_plan,
        dry_run=True,
        confirm=False,
        plan_hash=None,
        nonce=None,
        expires_at=None,
        plan_tool_name="delete_graph_data_tool",
    )


def test_generate_gremlin_tool_aligns_error_source(monkeypatch):
    expected = {
        **envelope_ok(),
        "ok": False,
        "data": None,
        "error": {
            "type": "HUGEGRAPH_AI_UNAVAILABLE",
            "message": "AI disabled",
            "suggestion": None,
            "retryable": False,
            "source": "hugegraph-ai",
            "details": {},
        },
    }
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "generate_gremlin", mock)

    result = server.generate_gremlin_tool(query="count vertices")

    _assert_envelope_shape(result)
    assert result["ok"] is False
    assert result["error"]["source"] == "generate_gremlin_tool"


def test_execute_gremlin_read_tool_reports_hard_budget_gate_source(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    mock = Mock()
    monkeypatch.setattr(server, "execute_gremlin_read", mock)

    result = server.execute_gremlin_read_tool(gremlin_query="g.addV('person')")

    _assert_envelope_shape(result)
    assert result["ok"] is False
    assert result["error"]["source"] == "execute_gremlin_read_tool"
    assert result["error"]["type"] == "FEATURE_DISABLED"
    mock.assert_not_called()


def test_raw_gremlin_execution_is_disabled_by_default(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "false")

    direct = server.execute_gremlin_read_tool(gremlin_query="g.V().limit(1)")
    generated = server.generate_gremlin_tool(query="one vertex", execute=True)

    assert direct["error"]["type"] == "FEATURE_DISABLED"
    assert generated["error"]["type"] == "FEATURE_DISABLED"


def test_hard_budget_gate_blocks_write_tool_by_default(monkeypatch):
    monkeypatch.delenv("HUGEGRAPH_MCP_TOOLSET", raising=False)
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "false")

    result = server.execute_gremlin_write_tool(gremlin_query="g.addV('test')")

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert "hard-budget contract is incomplete" in result["error"]["message"]
    assert "structured MCP query tools" in result["error"]["suggestion"]
    assert result["error"]["details"]["post_materialization_limits_are_hard_budgets"] is False
    assert "V1" not in result["error"]["message"]
    assert "V1" not in result["error"]["suggestion"]
    assert "V1" not in str(result["error"]["details"])


def test_admin_gate_blocks_refresh_embeddings_by_default(monkeypatch):
    monkeypatch.delenv("HUGEGRAPH_MCP_TOOLSET", raising=False)
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "false")

    result = server.refresh_vid_embeddings_tool(confirm=True)

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert (
        result["error"]["message"] == "refresh_vid_embeddings_tool is an admin/debug tool and is disabled by default."
    )
    assert (
        result["error"]["suggestion"] == "Set HUGEGRAPH_MCP_ADMIN_MODE=true and HUGEGRAPH_MCP_READONLY=false "
        "to enable refresh_vid_embeddings_tool."
    )
    assert result["error"]["details"]["toolset"] == "core"
    assert result["error"]["details"]["required_env"] == {
        "HUGEGRAPH_MCP_ADMIN_MODE": "true",
        "HUGEGRAPH_MCP_READONLY": "false",
    }
    assert "V1" not in result["error"]["message"]
    assert "V1" not in result["error"]["suggestion"]
    assert "V1" not in str(result["error"]["details"])


def test_raw_write_fails_closed_even_when_admin_and_writes_enabled(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    mock = Mock()
    monkeypatch.setattr(server, "execute_gremlin_write", mock)

    result = server.execute_gremlin_write_tool(gremlin_query="g.addV('test')")

    _assert_envelope_shape(result)
    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert "hard-budget contract is incomplete" in result["error"]["message"]
    mock.assert_not_called()


def test_execute_gremlin_write_tool_documents_disabled_contract():
    doc = server.execute_gremlin_write_tool.__doc__ or ""

    assert "disabled" in doc.lower()
    assert "hard-budget" in doc


def test_hard_budget_gate_precedes_write_readonly_check(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    mock = Mock()
    monkeypatch.setattr(server, "execute_gremlin_write", mock)

    result = server.execute_gremlin_write_tool(gremlin_query="g.addV('test')")

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert result["error"]["source"] == "execute_gremlin_write_tool"
    assert result["error"]["details"]["post_materialization_limits_are_hard_budgets"] is False
    mock.assert_not_called()


def test_admin_gate_allows_refresh_embeddings_when_enabled(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    expected = envelope_ok({"data": "refreshed"})
    mock = Mock(return_value=expected)
    monkeypatch.setattr(server, "refresh_vid_embeddings", mock)

    result = server.refresh_vid_embeddings_tool(confirm=True)

    _assert_envelope_shape(result)
    assert result["ok"] is True
    assert result["data"] == expected["data"]
    mock.assert_called_once_with(confirm=True)


def test_admin_gate_reads_current_env_after_import(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "false")
    blocked = server.execute_gremlin_write_tool(gremlin_query="g.addV('test')")
    assert blocked["ok"] is False
    assert blocked["error"]["type"] == "FEATURE_DISABLED"

    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    mock = Mock()
    monkeypatch.setattr(server, "execute_gremlin_write", mock)

    result = server.execute_gremlin_write_tool(gremlin_query="g.addV('test')")

    _assert_envelope_shape(result)
    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    mock.assert_not_called()


def test_execute_gremlin_write_tool_does_not_reach_executor(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    mock = Mock(side_effect=RuntimeError("must not execute"))
    monkeypatch.setattr(server, "execute_gremlin_write", mock)

    result = server.execute_gremlin_write_tool(gremlin_query="g.addV('test')")

    _assert_envelope_shape(result)
    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    mock.assert_not_called()


def test_refresh_vid_embeddings_tool_wraps_unexpected_exceptions(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    mock = Mock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(server, "refresh_vid_embeddings", mock)

    result = server.refresh_vid_embeddings_tool(confirm=True)

    _assert_envelope_shape(result)
    assert result["ok"] is False
    assert result["error"]["type"] == "FLOW_EXECUTION_FAILED"
    assert result["error"]["source"] == "refresh_vid_embeddings_tool"
    assert "boom" in result["error"]["message"]


def test_import_tool_description_matches_preview_only_behavior():
    tools = asyncio.run(_list_mcp_tools())
    tool = next(item for item in tools if item.name == "import_graph_data_tool")
    assert "no plan_id" in tool.description
    assert "FEATURE_DISABLED" in tool.description
