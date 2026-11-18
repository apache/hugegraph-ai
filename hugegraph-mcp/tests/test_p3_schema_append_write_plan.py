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

"""Unit tests for Phase P3: schema append_vertex_label / append_edge_label WritePlan."""

import asyncio
from unittest.mock import Mock

from fastmcp import Client

from hugegraph_mcp import server
from hugegraph_mcp.tools.manage_schema import apply_schema_operations, validate_schema_operations
from hugegraph_mcp.tools.schema_write_adapter import APPEND_SCHEMA


def _live_schema(*, person_props=None, knows_props=None):
    return {
        "schema": {
            "propertykeys": [
                {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
                {"name": "age", "data_type": "INT", "cardinality": "SINGLE"},
                {"name": "weight", "data_type": "DOUBLE", "cardinality": "SINGLE"},
            ],
            "vertexlabels": [
                {
                    "name": "person",
                    "id_strategy": "PRIMARY_KEY",
                    "properties": list(person_props or ["name"]),
                    "primary_keys": ["name"],
                    "nullable_keys": [],
                }
            ],
            "edgelabels": [
                {
                    "name": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "properties": list(knows_props or []),
                    "nullable_keys": [],
                }
            ],
            "indexlabels": [],
        }
    }


def test_validate_append_vertex_and_edge_label():
    live = _live_schema()

    ok_v = validate_schema_operations(
        [{"type": "append_vertex_label", "name": "person", "properties": ["age"], "nullable_keys": ["age"]}],
        live_schema=live,
    )
    assert ok_v["valid"] is True

    ok_e = validate_schema_operations(
        [{"type": "append_edge_label", "name": "knows", "properties": ["weight"], "nullable_keys": ["weight"]}],
        live_schema=live,
    )
    assert ok_e["valid"] is True

    missing_label = validate_schema_operations(
        [{"type": "append_vertex_label", "name": "company", "properties": ["name"]}],
        live_schema=live,
    )
    assert missing_label["valid"] is False

    empty_payload = validate_schema_operations(
        [{"type": "append_vertex_label", "name": "person"}],
        live_schema=live,
    )
    assert empty_payload["valid"] is False

    bad_nullable = validate_schema_operations(
        [{"type": "append_vertex_label", "name": "person", "nullable_keys": ["age"]}],
        live_schema=live,
    )
    assert bad_nullable["valid"] is False


def test_append_schema_apply_conflict_when_missing():
    receipt = apply_schema_operations(
        [{"type": "append_vertex_label", "name": "ghost", "properties": ["age"]}],
        live_schema=_live_schema(),
    )
    assert receipt["status"] == "CONFLICT"
    assert receipt["reconciliation_required"] is False


def test_append_fields_match_distinguishes_missing_key_from_none_value():
    from hugegraph_mcp.tools.manage_schema import _append_fields_match

    op = {"type": "append_vertex_label", "name": "person", "user_data": {"note": None}}
    assert _append_fields_match(op, {"name": "person", "user_data": {}}) is False
    assert _append_fields_match(op, {"name": "person", "user_data": {"note": None}}) is True

    bool_op = {"type": "append_vertex_label", "name": "person", "user_data": {"enabled": 1}}
    assert _append_fields_match(bool_op, {"name": "person", "user_data": {"enabled": True}}) is False
    assert _append_fields_match(bool_op, {"name": "person", "user_data": {"enabled": 1}}) is True


def test_append_vertex_label_dry_run_confirm_and_reconcile(monkeypatch, tmp_path):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ENABLE_V2_PLAN_STORE", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_DB_PATH", str(tmp_path / "plans.db"))
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "hugegraph")
    monkeypatch.setenv("HUGEGRAPH_URL", "http://127.0.0.1:8080")

    current_schema = [_live_schema()]
    builder = Mock()
    builder.properties.return_value = builder
    builder.nullable_keys.return_value = builder
    builder.add_parameter.return_value = builder
    manager = Mock()
    manager.vertex_label.return_value = builder

    def _append_side_effect():
        current_schema[0] = _live_schema(person_props=["name", "age"])
        current_schema[0]["schema"]["vertexlabels"][0]["nullable_keys"] = ["age"]
        current_schema[0]["schema"]["vertexlabels"][0]["user_data"] = {"source": "mcp"}

    builder.append.side_effect = _append_side_effect

    monkeypatch.setattr("hugegraph_mcp.tools.manage_schema.current_live_schema", lambda *_a, **_k: current_schema[0])
    monkeypatch.setattr("hugegraph_mcp.tools.manage_schema._schema_manager", lambda: manager)

    op = {
        "type": "append_vertex_label",
        "name": "person",
        "properties": ["age"],
        "nullable_keys": ["age"],
        "user_data": {"source": "mcp"},
    }

    async def _run():
        async with Client(server.mcp) as client:
            dry = (await client.call_tool("apply_schema_tool", {"mode": "dry_run", "operations": [op]})).data
            assert dry["ok"] is True
            plan_id = dry["data"]["plan_id"]
            assert plan_id.startswith("wp_")

            status_before = (await client.call_tool("get_write_status_tool", {"plan_id": plan_id})).data
            assert status_before["data"]["operations"][0]["kind"] == APPEND_SCHEMA

            confirmed = (await client.call_tool("confirm_write_tool", {"plan_id": plan_id})).data
            assert confirmed["ok"] is True
            assert confirmed["data"]["status"] == "APPLIED"
            builder.nullable_keys.assert_called_once_with("age")
            builder.add_parameter.assert_called_once_with("user_data", {"source": "mcp"})
            builder.append.assert_called_once()

    asyncio.run(_run())


def test_append_schema_reconciles_pending_as_not_applied_not_conflict(monkeypatch, tmp_path):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ENABLE_V2_PLAN_STORE", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("HUGEGRAPH_MCP_PLAN_DB_PATH", str(tmp_path / "plans_reconcile.db"))
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "hugegraph")
    monkeypatch.setenv("HUGEGRAPH_URL", "http://127.0.0.1:8080")

    current_schema = [_live_schema()]
    builder = Mock()
    builder.properties.return_value = builder
    builder.nullable_keys.return_value = builder
    manager = Mock()
    manager.vertex_label.return_value = builder
    # Simulate ambiguous timeout before append actually landed
    builder.append.side_effect = RuntimeError("timeout")

    monkeypatch.setattr("hugegraph_mcp.tools.manage_schema.current_live_schema", lambda *_a, **_k: current_schema[0])
    monkeypatch.setattr("hugegraph_mcp.tools.manage_schema._schema_manager", lambda: manager)

    op = {"type": "append_vertex_label", "name": "person", "properties": ["age"], "nullable_keys": ["age"]}

    async def _run():
        async with Client(server.mcp) as client:
            dry = (await client.call_tool("apply_schema_tool", {"mode": "dry_run", "operations": [op]})).data
            plan_id = dry["data"]["plan_id"]
            confirmed = (await client.call_tool("confirm_write_tool", {"plan_id": plan_id})).data
            assert confirmed["ok"] is False
            status_after = (await client.call_tool("get_write_status_tool", {"plan_id": plan_id})).data
            assert status_after["data"]["status"] == "UNKNOWN"

            reconciled = (await client.call_tool("reconcile_write_tool", {"plan_id": plan_id})).data
            assert reconciled["ok"] is True
            assert reconciled["data"]["status"] != "CONFLICT"
            assert reconciled["data"]["operations"][0]["status"] == "UNKNOWN"

    asyncio.run(_run())
