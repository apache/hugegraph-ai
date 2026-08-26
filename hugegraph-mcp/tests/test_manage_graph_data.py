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

import re
from copy import deepcopy
from unittest.mock import Mock

from hugegraph_mcp.tools import manage_graph_data as manage_graph_data_module
from hugegraph_mcp.tools.graph_data_gremlin import (
    _create_edge_query,
    _create_vertex_query,
    _g,
)


def _live_schema():
    return {
        "schema": {
            "propertykeys": [
                {"name": "name", "data_type": "TEXT"},
                {"name": "age", "data_type": "INT"},
                {"name": "since", "data_type": "INT"},
            ],
            "vertexlabels": [
                {
                    "name": "person",
                    "properties": ["name", "age"],
                    "primary_keys": ["name"],
                },
            ],
            "edgelabels": [
                {
                    "name": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "properties": ["since"],
                },
            ],
        },
        "simple_schema": {"vertices": ["person"], "edges": ["knows"]},
    }


def _delete_edge_plan():
    return {
        "operations": [
            {
                "op": "delete_edge",
                "label": "knows",
                "source_label": "person",
                "source_match": {"name": "Alice"},
                "target_label": "person",
                "target_match": {"name": "Bob"},
            }
        ]
    }


def _delete_vertex_plan():
    return {
        "operations": [
            {
                "op": "delete_vertex",
                "label": "person",
                "match": {"name": "Alice"},
            }
        ]
    }


def _mock_schema(monkeypatch):
    monkeypatch.setattr(
        manage_graph_data_module,
        "_fetch_live_schema",
        lambda: _live_schema(),
    )


def _customize_schema(id_strategy):
    schema = _live_schema()
    vertex_label = schema["schema"]["vertexlabels"][0]
    vertex_label["id_strategy"] = id_strategy
    vertex_label["primary_keys"] = []
    return schema


def _nested_count_result(count):
    return {
        "data": {"data": [count], "meta": {}},
        "total": 1,
        "duration_ms": 1,
        "is_read": True,
    }


def test_validate_graph_change_plan_rejects_unknown_op():
    result = manage_graph_data_module.validate_graph_change_plan(
        {"operations": [{"op": "merge_vertex", "label": "person"}]},
        _live_schema(),
    )

    assert result["valid"] is False
    assert "unsupported op" in result["errors"][0]["reason"]


def test_public_import_dry_run_rejects_customize_string_vertex_without_id(
    monkeypatch,
):
    monkeypatch.setattr(
        manage_graph_data_module,
        "_fetch_live_schema",
        lambda: _customize_schema("CUSTOMIZE_STRING"),
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="import",
        graph_data={
            "vertices": [
                {"label": "person", "properties": {"name": "Alice", "age": 30}}
            ],
            "edges": [],
        },
        dry_run=True,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert result["error"]["details"]["errors"] == [
        "vertex 0 missing required id for CUSTOMIZE_STRING label 'person'"
    ]


def test_public_import_dry_run_rejects_customize_number_vertex_with_bool_id(
    monkeypatch,
):
    monkeypatch.setattr(
        manage_graph_data_module,
        "_fetch_live_schema",
        lambda: _customize_schema("CUSTOMIZE_NUMBER"),
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="import",
        graph_data={
            "vertices": [
                {
                    "id": True,
                    "label": "person",
                    "properties": {"name": "Alice", "age": 30},
                }
            ],
            "edges": [],
        },
        dry_run=True,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert result["error"]["details"]["errors"] == [
        "vertex 0 id for CUSTOMIZE_NUMBER label 'person' must be an integer, got bool"
    ]


def test_validate_mode_operations_handles_unknown_mode():
    result = manage_graph_data_module._validate_mode_operations(
        "upsert",
        {"operations": []},
    )

    assert result["valid"] is False
    assert result["errors"][0]["reason"] == "unknown mode: upsert"


def test_validate_mode_operations_rejects_non_object_operation():
    result = manage_graph_data_module._validate_mode_operations(
        "import",
        {"operations": ["not-an-operation"]},
    )

    assert result["valid"] is False
    assert result["errors"][0]["reason"] == "operation must be an object"


def test_gremlin_literal_uses_single_quotes_to_avoid_gstring_interpolation():
    assert _g("${System.exit(0)}") == "'${System.exit(0)}'"
    assert _g("Alice's path\\name") == "'Alice\\'s path\\\\name'"
    assert _g("line1\nline2\r\n\tend") == "'line1\\nline2\\r\\n\\tend'"
    assert _g("bad\u0001char") == "'bad\\u0001char'"


def test_validate_delete_vertex_requires_primary_key_match():
    result = manage_graph_data_module.validate_graph_change_plan(
        {
            "operations": [
                {
                    "op": "delete_vertex",
                    "label": "person",
                    "match": {"age": 31},
                }
            ]
        },
        _live_schema(),
    )

    assert result["valid"] is False
    assert "must contain primary key" in result["errors"][0]["reason"]


def test_validate_edge_rejects_unknown_endpoint_label():
    result = manage_graph_data_module.validate_graph_change_plan(
        {
            "operations": [
                {
                    "op": "delete_edge",
                    "label": "knows",
                    "source_label": "ghost",
                    "source_match": {"name": "Alice"},
                    "target_label": "person",
                    "target_match": {"name": "Bob"},
                }
            ]
        },
        _live_schema(),
    )

    assert result["valid"] is False
    assert any(
        "source_label references undefined" in e["reason"] for e in result["errors"]
    )


def test_dry_run_delete_edge_rejects_non_single_match(monkeypatch):
    counts = iter([1, 1, 2])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is False
    assert "delete_edge matched_count must be 1" in result["errors"][0]["reason"]


def test_dry_run_delete_edge_returns_preview_and_hash(monkeypatch):
    queries = []
    counts = iter([1, 1, 1])

    def fake_read(query):
        queries.append(query)
        return {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        }

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_read", fake_read
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is True
    assert re.fullmatch(r"[0-9a-f]{32}", result["plan_hash"])
    assert result["preview"][0]["source_matched_count"] == 1
    assert result["preview"][0]["target_matched_count"] == 1
    assert result["preview"][0]["matched_count"] == 1
    assert queries == [
        "g.V().hasLabel('person').has('name','Alice').count()",
        "g.V().hasLabel('person').has('name','Bob').count()",
        "g.V().hasLabel('person').has('name','Alice').outE('knows').where(inV().hasLabel('person').has('name','Bob')).count()",
    ]


def test_dry_run_delete_edge_accepts_nested_count_result(monkeypatch):
    counts = iter([1, 1, 1])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: _nested_count_result(next(counts)),
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is True
    assert result["preview"][0]["source_matched_count"] == 1
    assert result["preview"][0]["target_matched_count"] == 1
    assert result["preview"][0]["matched_count"] == 1


def test_dry_run_delete_edge_rejects_missing_source(monkeypatch):
    counts = iter([0, 1])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is False
    assert (
        "delete_edge source endpoint matched_count must be 1"
        in result["errors"][0]["reason"]
    )
    assert "matched_count" not in result["preview"][0]


def test_dry_run_delete_edge_rejects_missing_target(monkeypatch):
    counts = iter([1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is False
    assert (
        "delete_edge target endpoint matched_count must be 1"
        in result["errors"][0]["reason"]
    )
    assert "matched_count" not in result["preview"][0]


def test_dry_run_delete_edge_rejects_zero_edge_match(monkeypatch):
    counts = iter([1, 1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_edge_plan(),
        _live_schema(),
    )

    assert result["valid"] is False
    assert "delete_edge matched_count must be 1, got 0" in result["errors"][0]["reason"]


def test_dry_run_delete_vertex_rejects_edges_when_not_cascade(monkeypatch):
    counts = iter([1, 3])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        {
            "operations": [
                {
                    "op": "delete_vertex",
                    "label": "person",
                    "match": {"name": "Alice"},
                    "cascade": False,
                }
            ]
        },
        _live_schema(),
    )

    assert result["valid"] is False
    assert "cascade=false" in result["errors"][0]["reason"]
    assert result["preview"][0]["associated_edge_count"] == 3


def test_dry_run_delete_vertex_cascade_preview_unwraps_nested_values(monkeypatch):
    def fake_read(query):
        if query.endswith(".count()"):
            return {"data": {"data": [1], "meta": {}}, "duration_ms": 1}
        return {
            "data": {
                "data": [{"id": "edge-1", "label": "knows"}],
                "meta": {"ignored": True},
            },
            "duration_ms": 1,
        }

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_read", fake_read
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        {
            "operations": [
                {
                    "op": "delete_vertex",
                    "label": "person",
                    "match": {"name": "Alice"},
                    "cascade": True,
                }
            ]
        },
        _live_schema(),
    )

    assert result["valid"] is False
    assert result["preview"][0]["associated_edges"] == [
        {"id": "edge-1", "label": "knows"}
    ]
    assert result["errors"][0]["error_type"] == "CASCADE_NOT_ENABLED"


def test_manage_delete_vertex_returns_blocked_by_relationships(monkeypatch):
    _mock_schema(monkeypatch)
    counts = iter([1, 2])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "BLOCKED_BY_RELATIONSHIPS"


def test_dry_run_delete_vertex_allows_no_edges_when_not_cascade(monkeypatch):
    counts = iter([1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_vertex_plan(),
        _live_schema(),
    )

    assert result["valid"] is True
    assert re.fullmatch(r"[0-9a-f]{32}", result["plan_hash"])
    assert result["preview"][0]["matched_count"] == 1
    assert result["preview"][0]["associated_edge_count"] == 0


def test_dry_run_delete_vertex_accepts_nested_count_result(monkeypatch):
    counts = iter([1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: _nested_count_result(next(counts)),
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_vertex_plan(),
        _live_schema(),
    )

    assert result["valid"] is True
    assert result["preview"][0]["matched_count"] == 1
    assert result["preview"][0]["associated_edge_count"] == 0


def test_dry_run_delete_vertex_rejects_non_single_match(monkeypatch):
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {"data": [0], "total": 1, "duration_ms": 1, "is_read": True},
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        _delete_vertex_plan(),
        _live_schema(),
    )

    assert result["valid"] is False
    assert "delete_vertex matched_count must be 1" in result["errors"][0]["reason"]


def test_manage_graph_data_execute_delete_vertex_verifies_removed(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    reads = []
    writes = []
    counts = iter([1, 0, 1, 0, 1, 0, 0])

    def fake_read(query):
        reads.append(query)
        return {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        }

    def fake_write(query, **_kwargs):
        writes.append(query)
        return {"success": True, "affected": 1, "duration_ms": 1, "is_write": True}

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_read", fake_read
    )
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_write", fake_write
    )
    dry_run = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=dry_run["data"]["plan_context"]["nonce"],
        expires_at=dry_run["data"]["plan_context"]["expires_at"],
    )

    assert result["ok"] is True
    assert writes == ["g.V().hasLabel('person').has('name','Alice').drop()"]
    assert reads[-1] == "g.V().hasLabel('person').has('name','Alice').count()"


def test_manage_graph_data_execute_delete_edge_verifies_removed(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    reads = []
    writes = []
    counts = iter([1, 1, 1, 1, 1, 1, 1, 1, 1, 0])

    def fake_read(query):
        reads.append(query)
        return {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        }

    def fake_write(query, **_kwargs):
        writes.append(query)
        return {"success": True, "affected": 1, "duration_ms": 1, "is_write": True}

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_read", fake_read
    )
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_write", fake_write
    )
    dry_run = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_edge_plan(),
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_edge_plan(),
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=dry_run["data"]["plan_context"]["nonce"],
        expires_at=dry_run["data"]["plan_context"]["expires_at"],
    )

    edge_match_query = (
        "g.V().hasLabel('person').has('name','Alice').outE('knows')"
        ".where(inV().hasLabel('person').has('name','Bob'))"
    )
    assert result["ok"] is True
    assert writes == [f"{edge_match_query}.drop()"]
    assert reads[-1] == f"{edge_match_query}.count()"


def test_manage_graph_data_execute_delete_edge_verify_failure(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    counts = iter([1, 1, 1, 1, 1, 1, 1, 1, 1, 1])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query, **_kwargs: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_write",
        lambda _query, **_kwargs: {
            "success": True,
            "affected": 1,
            "duration_ms": 1,
            "is_write": True,
        },
    )
    dry_run = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_edge_plan(),
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_edge_plan(),
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=dry_run["data"]["plan_context"]["nonce"],
        expires_at=dry_run["data"]["plan_context"]["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "DELETE_VERIFY_FAILED"
    assert result["error"]["details"]["failed_items"][0]["type"] == (
        "DELETE_VERIFY_FAILED"
    )


def test_graph_data_to_change_plan_maps_create_operations():
    result = manage_graph_data_module.graph_data_to_change_plan(
        {
            "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "source": {"name": "Alice"},
                    "target_label": "person",
                    "target": {"name": "Bob"},
                    "properties": {"since": 2024},
                }
            ],
        }
    )

    assert [op["op"] for op in result["operations"]] == ["create_vertex", "create_edge"]
    assert result["operations"][1]["source_match"] == {"name": "Alice"}


def test_graph_data_to_change_plan_preserves_outv_inv_id_contract():
    result = manage_graph_data_module.graph_data_to_change_plan(
        {
            "vertices": [
                {"id": "1:Alice", "label": "person", "properties": {"name": "Alice"}},
                {"id": "1:Bob", "label": "person", "properties": {"name": "Bob"}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "outV": "1:Alice",
                    "outVLabel": "person",
                    "inV": "1:Bob",
                    "inVLabel": "person",
                    "properties": {"since": 2024},
                }
            ],
        },
        live_schema=_live_schema(),
    )

    assert result["operations"][0]["id"] == "1:Alice"
    assert result["operations"][1]["id"] == "1:Bob"
    edge_op = result["operations"][2]
    assert edge_op["source_match"] == {"id": "1:Alice"}
    assert edge_op["target_match"] == {"id": "1:Bob"}


def test_graph_data_to_change_plan_object_id_endpoint_is_id():
    result = manage_graph_data_module.graph_data_to_change_plan(
        {
            "vertices": [
                {"id": "1:Alice", "label": "person", "properties": {"name": "Alice"}},
                {"id": "1:Bob", "label": "person", "properties": {"name": "Bob"}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "source": {"id": "1:Alice"},
                    "target_label": "person",
                    "target": {"id": "1:Bob"},
                }
            ],
        },
        live_schema=_live_schema(),
    )

    edge_op = result["operations"][2]
    assert edge_op["source_match"] == {"id": "1:Alice"}
    assert edge_op["target_match"] == {"id": "1:Bob"}


def test_graph_data_to_change_plan_object_primary_key_endpoint():
    result = manage_graph_data_module.graph_data_to_change_plan(
        {
            "vertices": [
                {"label": "person", "properties": {"name": "Alice"}},
                {"label": "person", "properties": {"name": "Bob"}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "source": {"name": "Alice"},
                    "target_label": "person",
                    "target": {"name": "Bob"},
                }
            ],
        },
        live_schema=_live_schema(),
    )

    edge_op = result["operations"][2]
    assert edge_op["source_match"] == {"name": "Alice"}
    assert edge_op["target_match"] == {"name": "Bob"}


def test_graph_data_to_change_plan_maps_scalar_endpoints_to_single_primary_key():
    result = manage_graph_data_module.graph_data_to_change_plan(
        {
            "vertices": [
                {"label": "person", "properties": {"name": "Alice"}},
                {"label": "person", "properties": {"name": "Bob"}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "source": "Alice",
                    "target_label": "person",
                    "target": "Bob",
                }
            ],
        },
        live_schema=_live_schema(),
    )

    edge_op = result["operations"][2]
    assert edge_op["source_match"] == {"name": "Alice"}
    assert edge_op["target_match"] == {"name": "Bob"}


def test_graph_data_to_change_plan_maps_edge_only_scalar_to_single_primary_key():
    result = manage_graph_data_module.graph_data_to_change_plan(
        {
            "vertices": [],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "source": "Alice",
                    "target_label": "person",
                    "target": "Bob",
                }
            ],
        },
        live_schema=_live_schema(),
    )

    edge_op = result["operations"][0]
    assert edge_op["source_match"] == {"name": "Alice"}
    assert edge_op["target_match"] == {"name": "Bob"}


def test_manage_graph_data_import_uses_primary_key_for_scalar_endpoints(monkeypatch):
    _mock_schema(monkeypatch)
    reads = []

    def fake_read(query):
        reads.append(query)
        return {"data": [0], "total": 1, "duration_ms": 1, "is_read": True}

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        fake_read,
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="import",
        graph_data={
            "vertices": [
                {"label": "person", "properties": {"name": "Alice"}},
                {"label": "person", "properties": {"name": "Bob"}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "source": "Alice",
                    "target_label": "person",
                    "target": "Bob",
                }
            ],
        },
    )

    assert result["ok"] is True
    assert not any("hasId('Alice')" in query for query in reads)
    assert not any("hasId('Bob')" in query for query in reads)
    assert reads[-2:] == [
        "g.V().hasLabel('person').has('name','Alice').count()",
        "g.V().hasLabel('person').has('name','Bob').count()",
    ]


def test_manage_graph_data_import_allows_edge_to_existing_vertex(monkeypatch):
    _mock_schema(monkeypatch)
    counts = iter([0, 0, 1])
    reads = []

    def fake_read(query):
        reads.append(query)
        return {"data": [next(counts)], "total": 1, "duration_ms": 1, "is_read": True}

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        fake_read,
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="import",
        graph_data={
            "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "source": "Alice",
                    "target_label": "person",
                    "target": "Bob",
                }
            ],
        },
    )

    assert result["ok"] is True
    preview = result["data"]["preview"][1]
    assert preview["source_planned_count"] == 1
    assert preview["source_live_count"] == 0
    assert preview["source_matched_count"] == 1
    assert preview["target_planned_count"] == 0
    assert preview["target_live_count"] == 1
    assert preview["target_matched_count"] == 1
    assert reads[-2:] == [
        "g.V().hasLabel('person').has('name','Alice').count()",
        "g.V().hasLabel('person').has('name','Bob').count()",
    ]


def test_graph_data_to_change_plan_does_not_degrade_numeric_ids_to_properties():
    result = manage_graph_data_module.graph_data_to_change_plan(
        {
            "vertices": [
                {"id": 123, "label": "person", "properties": {"name": "Alice"}},
                {"id": 456, "label": "person", "properties": {"name": "Bob"}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "outV": "123",
                    "outVLabel": "person",
                    "inV": "456",
                    "inVLabel": "person",
                }
            ],
        }
    )

    edge_op = result["operations"][2]
    assert edge_op["source_match"] == {"id": 123}
    assert edge_op["target_match"] == {"id": 456}


def test_create_vertex_query_preserves_explicit_id():
    query = _create_vertex_query(
        {
            "op": "create_vertex",
            "label": "person",
            "id": "1:Alice",
            "properties": {"name": "Alice"},
        }
    )

    assert query == "g.addV('person').property(T.id,'1:Alice').property('name','Alice')"


def test_dry_run_create_vertex_rejects_existing_explicit_id(monkeypatch):
    read = []

    def fake_read(query):
        read.append(query)
        return {"data": [1], "total": 1, "duration_ms": 1, "is_read": True}

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        fake_read,
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        {
            "operations": [
                {
                    "op": "create_vertex",
                    "label": "person",
                    "id": "1:Alice",
                    "properties": {"age": 31},
                }
            ]
        },
        _live_schema(),
    )

    assert result["valid"] is False
    assert result["preview"][0]["id_live_count"] == 1
    assert any(
        "create_vertex id identity already exists" in error["reason"]
        for error in result["errors"]
    )
    assert read == ["g.V().hasLabel('person').hasId('1:Alice').count()"]


def test_dry_run_create_vertex_rejects_existing_primary_key(monkeypatch):
    read = []

    def fake_read(query):
        read.append(query)
        return {"data": [1], "total": 1, "duration_ms": 1, "is_read": True}

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        fake_read,
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        {
            "operations": [
                {
                    "op": "create_vertex",
                    "label": "person",
                    "properties": {"name": "Alice"},
                }
            ]
        },
        _live_schema(),
    )

    assert result["valid"] is False
    assert result["preview"][0]["primary_key_live_count"] == 1
    assert any(
        "create_vertex primary_key identity already exists" in error["reason"]
        for error in result["errors"]
    )
    assert read == ["g.V().hasLabel('person').has('name','Alice').count()"]


def test_create_edge_query_matches_endpoints_by_id():
    query = _create_edge_query(
        {
            "op": "create_edge",
            "label": "knows",
            "source_label": "person",
            "source_match": {"id": "1:Alice"},
            "target_label": "person",
            "target_match": {"id": "1:Bob"},
        }
    )

    assert (
        query == "g.V().hasLabel('person').hasId('1:Alice').as('s')"
        ".V().hasLabel('person').hasId('1:Bob').addE('knows').from('s')"
    )


def test_dry_run_create_edge_rejects_non_unique_source(monkeypatch):
    counts = iter([2, 1])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        {
            "operations": [
                {
                    "op": "create_edge",
                    "label": "knows",
                    "source_label": "person",
                    "source_match": {"id": "1:Alice"},
                    "target_label": "person",
                    "target_match": {"id": "1:Bob"},
                }
            ]
        },
        _live_schema(),
    )

    assert result["valid"] is False
    assert (
        "create_edge source endpoint matched_count must be 1, got 2"
        in (result["errors"][0]["reason"])
    )
    assert result["preview"][0]["source_matched_count"] == 2


def test_dry_run_create_edge_accepts_same_batch_vertex_id_with_live_lookup(
    monkeypatch,
):
    read = []

    def fake_read(query):
        read.append(query)
        return {"data": [0], "total": 1, "duration_ms": 1, "is_read": True}

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        fake_read,
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        {
            "operations": [
                {
                    "op": "create_vertex",
                    "label": "person",
                    "id": "1:Alice",
                    "properties": {"name": "Alice"},
                },
                {
                    "op": "create_vertex",
                    "label": "person",
                    "id": "1:Bob",
                    "properties": {"name": "Bob"},
                },
                {
                    "op": "create_edge",
                    "label": "knows",
                    "source_label": "person",
                    "source_match": {"id": "1:Alice"},
                    "target_label": "person",
                    "target_match": {"id": "1:Bob"},
                },
            ]
        },
        _live_schema(),
    )

    assert result["valid"] is True
    assert result["preview"][2]["source_matched_count"] == 1
    assert result["preview"][2]["source_planned_count"] == 1
    assert result["preview"][2]["source_live_count"] == 0
    assert result["preview"][2]["target_matched_count"] == 1
    assert result["preview"][2]["target_planned_count"] == 1
    assert result["preview"][2]["target_live_count"] == 0
    assert read == [
        "g.V().hasLabel('person').hasId('1:Alice').count()",
        "g.V().hasLabel('person').has('name','Alice').count()",
        "g.V().hasLabel('person').hasId('1:Bob').count()",
        "g.V().hasLabel('person').has('name','Bob').count()",
        "g.V().hasLabel('person').hasId('1:Alice').count()",
        "g.V().hasLabel('person').hasId('1:Bob').count()",
    ]


def test_dry_run_create_edge_normalizes_same_batch_numeric_ids(monkeypatch):
    read = []

    def fake_read(query):
        read.append(query)
        return {"data": [0], "total": 1, "duration_ms": 1, "is_read": True}

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        fake_read,
    )

    plan = manage_graph_data_module.graph_data_to_change_plan(
        {
            "vertices": [
                {"id": 123, "label": "person", "properties": {"name": "Alice"}},
                {"id": 456, "label": "person", "properties": {"name": "Bob"}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "outV": "123",
                    "outVLabel": "person",
                    "inV": "456",
                    "inVLabel": "person",
                }
            ],
        }
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(plan, _live_schema())

    assert result["valid"] is True
    assert result["preview"][2]["source_matched_count"] == 1
    assert result["preview"][2]["target_matched_count"] == 1
    assert len(read) == 6


def test_dry_run_create_edge_rejects_same_batch_endpoint_with_live_duplicate(
    monkeypatch,
):
    counts = iter([1, 0, 1, 0])
    read = []

    def fake_read(query):
        read.append(query)
        return {"data": [next(counts)], "total": 1, "duration_ms": 1, "is_read": True}

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        fake_read,
    )

    result = manage_graph_data_module.dry_run_graph_change_plan(
        {
            "operations": [
                {
                    "op": "create_vertex",
                    "label": "person",
                    "properties": {"name": "Alice"},
                },
                {
                    "op": "create_vertex",
                    "label": "person",
                    "properties": {"name": "Bob"},
                },
                {
                    "op": "create_edge",
                    "label": "knows",
                    "source_label": "person",
                    "source_match": {"name": "Alice"},
                    "target_label": "person",
                    "target_match": {"name": "Bob"},
                },
            ]
        },
        _live_schema(),
    )

    assert result["valid"] is False
    preview = result["preview"][2]
    assert preview["source_planned_count"] == 1
    assert preview["source_live_count"] == 1
    assert preview["source_matched_count"] == 2
    assert preview["target_matched_count"] == 1
    assert any(
        "create_vertex primary_key identity already exists" in error["reason"]
        for error in result["errors"]
    )
    assert any(
        "create_edge source endpoint matched_count must be 1, got 2" in error["reason"]
        for error in result["errors"]
    )
    assert len(read) == 4


def test_execute_create_vertex_rechecks_identity_before_write(monkeypatch):
    counts = iter([0, 1])
    writes = []

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    def fake_write(query, **_kwargs):
        writes.append(query)
        return {"success": True, "affected": 1, "duration_ms": 1, "is_write": True}

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_write",
        fake_write,
    )

    result = manage_graph_data_module.execute_graph_change_plan(
        {
            "operations": [
                {
                    "op": "create_vertex",
                    "label": "person",
                    "properties": {"name": "Alice"},
                },
                {
                    "op": "create_vertex",
                    "label": "person",
                    "properties": {"name": "Bob"},
                },
            ]
        },
        live_schema=_live_schema(),
    )

    assert result["success"] is False
    assert result["status"] == "partial"
    assert writes == ["g.addV('person').property('name','Alice')"]
    assert result["failed_items"][0]["operation_index"] == 1
    assert result["failed_items"][0]["error"]["type"] == "INVALID_GRAPH_DATA"
    assert (
        result["failed_items"][0]["error"]["details"]["identity_type"] == "primary_key"
    )


def test_execute_create_edge_rejects_zero_affected(monkeypatch):
    counts = iter([1, 1])
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_write",
        lambda _query, **_kwargs: {"success": True, "affected": 0, "is_write": True},
    )

    result = manage_graph_data_module.execute_graph_change_plan(
        {
            "operations": [
                {
                    "op": "create_edge",
                    "label": "knows",
                    "source_label": "person",
                    "source_match": {"id": "1:Alice"},
                    "target_label": "person",
                    "target_match": {"id": "1:Bob"},
                }
            ]
        }
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "FLOW_EXECUTION_FAILED"
    assert "affected 0 element" in result["error"]["message"]


def test_graph_data_to_change_plan_preserves_explicit_zero_endpoint_id():
    result = manage_graph_data_module.graph_data_to_change_plan(
        {
            "vertices": [],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "source": 0,
                    "target_label": "person",
                    "target": 1,
                }
            ],
        }
    )

    edge_op = result["operations"][0]
    assert edge_op["source_match"] == {"id": 0}
    assert edge_op["target_match"] == {"id": 1}


def test_manage_graph_data_requires_confirm(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    counts = iter([1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
        dry_run=False,
        confirm=False,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "CONFIRM_REQUIRED"


def test_manage_graph_data_rejects_update_mode(monkeypatch):
    _mock_schema(monkeypatch)

    result = manage_graph_data_module.manage_graph_data(
        mode="update",
        change_plan=_delete_vertex_plan(),
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "Use 'import' or 'delete'" in result["error"]["message"]


def test_manage_graph_data_plan_hash_mismatch(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    counts = iter([1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
        dry_run=False,
        confirm=True,
        plan_hash="0000000000000000",
        nonce="test_nonce",
        expires_at=9999999999.0,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PLAN_HASH_MISMATCH"


def test_manage_graph_data_plan_hash_expired(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    counts = iter([1, 0, 1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )
    dry_run = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=dry_run["data"]["plan_context"]["nonce"],
        expires_at=0,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PLAN_EXPIRED"


def test_manage_graph_data_dry_run_returns_plan_hash(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    counts = iter([1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
    )

    assert result["ok"] is True
    assert re.fullmatch(r"[0-9a-f]{32}", result["data"]["plan_hash"])
    assert result["data"]["confirmable"] is True


def test_manage_graph_data_readonly_dry_run_warns_plan_must_be_regenerated(
    monkeypatch,
    tmp_path,
):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    unusable_state_dir = tmp_path / "not-a-directory"
    unusable_state_dir.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("HUGEGRAPH_MCP_STATE_DIR", str(unusable_state_dir))
    counts = iter([1, 0, 1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    dry_run = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
    )

    assert dry_run["ok"] is True
    assert dry_run["data"]["confirmable"] is False
    assert dry_run["data"]["readonly_preview_only"] is True
    assert any("preview-only" in warning for warning in dry_run["warnings"])
    assert any("rerun dry_run" in action for action in dry_run["next_actions"])

    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    result = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=dry_run["data"]["plan_context"]["nonce"],
        expires_at=dry_run["data"]["plan_context"]["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PLAN_HASH_MISMATCH"


def test_manage_graph_data_plan_hash_schema_field_order_same_hash():
    plan = _delete_vertex_plan()
    schema = _live_schema()
    reordered_schema = _live_schema()
    reordered_schema["schema"]["propertykeys"] = list(
        reversed(reordered_schema["schema"]["propertykeys"])
    )
    reordered_schema["schema"]["vertexlabels"][0]["properties"] = ["age", "name"]
    reordered_schema["schema"]["vertexlabels"][0]["primaryKeys"] = ["name"]
    reordered_schema["schema"]["vertexlabels"][0].pop("primary_keys")
    reordered_schema["schema"]["edgelabels"][0]["sourceLabel"] = "person"
    reordered_schema["schema"]["edgelabels"][0]["targetLabel"] = "person"
    reordered_schema["schema"]["edgelabels"][0].pop("source_label")
    reordered_schema["schema"]["edgelabels"][0].pop("target_label")

    first = manage_graph_data_module.calculate_graph_change_plan_hash(
        plan,
        schema_summary=manage_graph_data_module._schema_summary(schema),
    )
    second = manage_graph_data_module.calculate_graph_change_plan_hash(
        plan,
        schema_summary=manage_graph_data_module._schema_summary(reordered_schema),
    )

    assert first == second


def test_manage_graph_data_plan_hash_schema_primary_key_change_different_hash():
    plan = _delete_vertex_plan()
    schema = _live_schema()
    changed_schema = deepcopy(schema)
    changed_schema["schema"]["vertexlabels"][0]["primary_keys"] = ["age"]

    first = manage_graph_data_module.calculate_graph_change_plan_hash(
        plan,
        schema_summary=manage_graph_data_module._schema_summary(schema),
    )
    second = manage_graph_data_module.calculate_graph_change_plan_hash(
        plan,
        schema_summary=manage_graph_data_module._schema_summary(changed_schema),
    )

    assert first != second


def test_manage_graph_data_plan_hash_schema_metadata_ignored_same_hash():
    plan = _delete_vertex_plan()
    schema = _live_schema()
    schema_with_metadata = deepcopy(schema)
    schema_with_metadata["server_time"] = "2026-05-26T00:00:00Z"
    schema_with_metadata["schema"]["vertexlabels"][0]["id"] = 99
    schema_with_metadata["schema"]["vertexlabels"][0]["user_data"] = {"x": "y"}
    schema_with_metadata["simple_schema"] = {"unrelated": ["metadata"]}

    first = manage_graph_data_module.calculate_graph_change_plan_hash(
        plan,
        schema_summary=manage_graph_data_module._schema_summary(schema),
    )
    second = manage_graph_data_module.calculate_graph_change_plan_hash(
        plan,
        schema_summary=manage_graph_data_module._schema_summary(schema_with_metadata),
    )

    assert first == second


def test_manage_graph_data_readonly_rejects_execution(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    writes = []
    counts = iter([1, 0, 1, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_write",
        lambda query, **_kwargs: writes.append(query),
    )
    dry_run = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="delete",
        change_plan=_delete_vertex_plan(),
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=dry_run["data"]["plan_context"]["nonce"],
        expires_at=dry_run["data"]["plan_context"]["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "READONLY_VIOLATION"
    assert writes == []


def test_manage_graph_data_partial_write_returns_error_envelope(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")

    graph_data = {
        "vertices": [
            {"label": "person", "properties": {"name": "Alice"}},
            {"label": "person", "properties": {"name": "Bob"}},
        ],
        "edges": [],
    }
    writes = []
    counts = iter([0, 0, 0, 0, 0, 0])

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {
            "data": [next(counts)],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        },
    )

    def fake_write(query, **_kwargs):
        writes.append(query)
        if len(writes) == 1:
            return {"success": True, "affected": 1, "duration_ms": 1, "is_write": True}
        return {
            "success": False,
            "error_type": "connection_error",
            "message": "write failed",
        }

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_write", fake_write
    )

    dry_run = manage_graph_data_module.manage_graph_data(
        mode="import",
        graph_data=graph_data,
    )
    result = manage_graph_data_module.manage_graph_data(
        mode="import",
        graph_data=graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=dry_run["data"]["plan_context"]["nonce"],
        expires_at=dry_run["data"]["plan_context"]["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "FLOW_EXECUTION_FAILED"
    details = result["error"]["details"]
    assert details["status"] == "partial"
    assert details["success"] is False
    assert details["planned"] == {"create_vertex": 2}
    assert details["written"] == {"create_vertex": 1}
    assert details["failed_items"][0]["operation_index"] == 1
    assert details["failed_items"][0]["op"] == "create_vertex"
    assert result["error"]["retryable"] is False
    assert len(writes) == 2


def test_manage_graph_data_replayed_confirmation_does_not_execute_twice(
    monkeypatch,
):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    state = {"target_exists": True}
    read_calls = []

    def fake_read(query):
        read_calls.append(query)
        count = 0 if "bothE()" in query else int(state["target_exists"])
        return {
            "data": [count],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        }

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        fake_read,
    )
    execute_calls = []

    def fake_execute(plan, *, live_schema):
        execute_calls.append((plan, live_schema))
        state["target_exists"] = False
        return {"success": True, "results": [{"success": True}]}

    monkeypatch.setattr(
        manage_graph_data_module, "execute_graph_change_plan", fake_execute
    )
    dry_run = manage_graph_data_module.manage_graph_data(
        mode="delete", change_plan=_delete_vertex_plan(), nonce="data-replay"
    )
    context = dry_run["data"]["plan_context"]
    arguments = {
        "mode": "delete",
        "change_plan": _delete_vertex_plan(),
        "dry_run": False,
        "confirm": True,
        "plan_hash": dry_run["data"]["plan_hash"],
        "nonce": context["nonce"],
        "expires_at": context["expires_at"],
    }

    first = manage_graph_data_module.manage_graph_data(**arguments)
    second = manage_graph_data_module.manage_graph_data(**arguments)

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["error"]["type"] == "PLAN_ALREADY_USED"
    assert state["target_exists"] is False
    assert len(execute_calls) == 1
    assert len(read_calls) == 4


def test_manage_graph_data_unconsumed_target_drift_does_not_consume_nonce(
    monkeypatch,
):
    from hugegraph_mcp.confirmation_store import ConfirmationStore

    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    state = {"target_exists": True}

    def fake_read(query):
        count = 0 if "bothE()" in query else int(state["target_exists"])
        return {
            "data": [count],
            "total": 1,
            "duration_ms": 1,
            "is_read": True,
        }

    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools, "execute_gremlin_read", fake_read
    )
    execute_calls = []

    def fake_execute(plan, *, live_schema):
        execute_calls.append((plan, live_schema))
        return {"success": True, "results": [{"success": True}]}

    monkeypatch.setattr(
        manage_graph_data_module, "execute_graph_change_plan", fake_execute
    )
    dry_run = manage_graph_data_module.manage_graph_data(
        mode="delete", change_plan=_delete_vertex_plan(), nonce="data-stale"
    )
    context = dry_run["data"]["plan_context"]
    arguments = {
        "mode": "delete",
        "change_plan": _delete_vertex_plan(),
        "dry_run": False,
        "confirm": True,
        "plan_hash": dry_run["data"]["plan_hash"],
        "nonce": context["nonce"],
        "expires_at": context["expires_at"],
    }

    state["target_exists"] = False
    stale = manage_graph_data_module.manage_graph_data(**arguments)

    assert stale["ok"] is False
    assert ConfirmationStore.from_config().has_consumed(context["nonce"]) is False
    assert execute_calls == []

    state["target_exists"] = True
    restored = manage_graph_data_module.manage_graph_data(**arguments)
    assert restored["ok"] is True
    assert len(execute_calls) == 1


def test_manage_graph_data_import_validates_graph_payload(monkeypatch):
    _mock_schema(monkeypatch)

    result = manage_graph_data_module.manage_graph_data(
        mode="import",
        graph_data={
            "vertices": [{"label": "person", "properties": {"age": 31}}],
            "edges": [],
        },
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"


def test_manage_graph_data_dry_run_rejects_too_many_operations_before_plan(
    monkeypatch,
):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    execute_read = Mock(
        return_value={"data": [0], "total": 1, "duration_ms": 1, "is_read": True}
    )
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        execute_read,
    )
    graph_data = {
        "vertices": [
            {"label": "person", "properties": {"name": f"n{idx}"}} for idx in range(201)
        ],
        "edges": [],
    }

    result = manage_graph_data_module.manage_graph_data(
        mode="import",
        graph_data=graph_data,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "MAX_OPERATIONS" in result["error"]["details"]["errors"][0]["reason"]
    assert "plan_hash" not in (result.get("data") or {})
    execute_read.assert_not_called()


def test_manage_graph_data_dry_run_rejects_oversized_payload_before_plan(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    execute_read = Mock(
        return_value={"data": [0], "total": 1, "duration_ms": 1, "is_read": True}
    )
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        execute_read,
    )
    graph_data = {
        "vertices": [
            {
                "label": "person",
                "properties": {"name": "Alice", "note": "x" * 1_048_576},
            }
        ],
        "edges": [],
    }

    result = manage_graph_data_module.manage_graph_data(
        mode="import",
        graph_data=graph_data,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "MAX_PAYLOAD_BYTES" in result["error"]["details"]["errors"][0]["reason"]
    assert "plan_hash" not in (result.get("data") or {})
    execute_read.assert_not_called()
