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

"""Layer B integration tests for the real HugeGraph write path."""

from __future__ import annotations

import time
from uuid import uuid4

import pytest
from pyhugegraph.client import PyHugeClient

from hugegraph_mcp import server
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.hugegraph_client import build_hugegraph_client
from hugegraph_mcp.tools import manage_graph_data as manage_graph_data_module
from hugegraph_mcp.tools.graph_data_gremlin import _g

pytestmark = [pytest.mark.integration, pytest.mark.real_hugegraph]


@pytest.fixture
def hugegraph_client(monkeypatch):
    if _env("RUN_MCP_REAL_HUGEGRAPH_TESTS") != "1":
        pytest.skip(
            "set RUN_MCP_REAL_HUGEGRAPH_TESTS=1 to run real HugeGraph write tests"
        )

    monkeypatch.setenv("HUGEGRAPH_URL", _env("HUGEGRAPH_URL", "http://127.0.0.1:8080"))
    monkeypatch.setenv(
        "HUGEGRAPH_GRAPH_PATH", _env("HUGEGRAPH_GRAPH_PATH", "DEFAULT/hugegraph")
    )
    monkeypatch.setenv("HUGEGRAPH_USER", _env("HUGEGRAPH_USER", "admin"))
    monkeypatch.setenv("HUGEGRAPH_PASSWORD", _env("HUGEGRAPH_PASSWORD", "admin"))
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ALLOW_AI", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "false")

    client = build_hugegraph_client(MCPConfig.from_env(), client_cls=PyHugeClient)
    try:
        client.schema().getSchema()
    except Exception as exc:  # noqa: BLE001 - depends on external service
        pytest.fail(f"HugeGraph Server is not available: {exc}")
    return client


def test_id_based_ingest_writes_the_intended_edge(hugegraph_client):
    names = _schema_names("id_edge")
    _ensure_custom_id_schema(hugegraph_client, names)
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'decoy')"
        f".property({_g(names.name_key)},'Alice')",
    )

    graph_data = {
        "vertices": [
            {
                "id": "alice",
                "label": names.vertex_label,
                "properties": {names.name_key: "Alice"},
            },
            {
                "id": "bob",
                "label": names.vertex_label,
                "properties": {names.name_key: "Bob"},
            },
        ],
        "edges": [
            {
                "label": names.edge_label,
                "source_label": names.vertex_label,
                "target_label": names.vertex_label,
                "source": {"id": "alice"},
                "target": {"id": "bob"},
            }
        ],
    }

    result = _import_graph_data(graph_data)

    assert result["ok"] is True
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasId('alice').out({_g(names.edge_label)}).hasId('bob')",
        )
        == 1
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasId('decoy').out({_g(names.edge_label)})",
        )
        == 0
    )


def test_apply_schema_forwards_and_verifies_supported_fields(hugegraph_client):
    suffix = uuid4().hex[:8]
    property_name = f"mcp_schema_property_{suffix}"
    label_name = f"mcp_schema_vertex_{suffix}"
    operations = [
        {
            "type": "create_property_key",
            "name": property_name,
            "data_type": "TEXT",
            "user_data": {"owner": "mcp-integration"},
        },
        {
            "type": "create_vertex_label",
            "name": label_name,
            "id_strategy": "PRIMARY_KEY",
            "properties": [property_name],
            "primary_keys": [property_name],
            "enable_label_index": False,
            "user_data": {"owner": "mcp-integration"},
        },
    ]

    dry_run = server.apply_schema_tool(mode="dry_run", operations=operations)
    assert dry_run["ok"] is True
    assert dry_run["data"]["valid"] is True
    context = dry_run["data"]["plan_context"]

    applied = server.apply_schema_tool(
        mode="apply",
        operations=operations,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )
    assert applied["ok"] is True
    assert applied["data"]["status"] == "applied"

    schema = hugegraph_client.schema().getSchema()
    raw_schema = schema.get("schema", schema)
    property_key = next(
        item for item in raw_schema["propertykeys"] if item.get("name") == property_name
    )
    vertex_label = next(
        item for item in raw_schema["vertexlabels"] if item.get("name") == label_name
    )
    assert property_key.get("user_data") == {"owner": "mcp-integration"}
    assert vertex_label.get("enable_label_index") is False
    assert vertex_label.get("user_data") == {"owner": "mcp-integration"}


def test_create_edge_rejects_missing_endpoint(hugegraph_client):
    names = _schema_names("missing")
    _ensure_custom_id_schema(hugegraph_client, names)
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'alice')"
        f".property({_g(names.name_key)},'Alice')",
    )
    change_plan = {
        "operations": [
            {
                "op": "create_edge",
                "label": names.edge_label,
                "source_label": names.vertex_label,
                "source_match": {"id": "alice"},
                "target_label": names.vertex_label,
                "target_match": {"id": "bob"},
            }
        ]
    }

    result = manage_graph_data_module.dry_run_graph_change_plan(
        change_plan,
        manage_graph_data_module._fetch_live_schema(),
    )

    assert result["valid"] is False
    assert any(
        "target endpoint matched_count must be 1" in error["reason"]
        for error in result["errors"]
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasId('alice').out({_g(names.edge_label)}).hasId('bob')",
        )
        == 0
    )


def test_create_edge_rejects_non_unique_property_match(hugegraph_client):
    names = _schema_names("nonunique")
    _ensure_custom_id_schema(hugegraph_client, names)
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'alice_1')"
        f".property({_g(names.name_key)},'Alice')",
    )
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'alice_2')"
        f".property({_g(names.name_key)},'Alice')",
    )
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'bob')"
        f".property({_g(names.name_key)},'Bob')",
    )
    change_plan = {
        "operations": [
            {
                "op": "create_edge",
                "label": names.edge_label,
                "source_label": names.vertex_label,
                "source_match": {names.name_key: "Alice"},
                "target_label": names.vertex_label,
                "target_match": {"id": "bob"},
            }
        ]
    }

    result = manage_graph_data_module.dry_run_graph_change_plan(
        change_plan,
        manage_graph_data_module._fetch_live_schema(),
    )

    assert result["valid"] is False
    assert any(
        "source endpoint matched_count must be 1" in error["reason"]
        for error in result["errors"]
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().has({_g(names.name_key)},'Alice').out({_g(names.edge_label)})",
        )
        == 0
    )


def test_create_vertex_existing_id_rejected_in_dry_run_without_writes(
    hugegraph_client,
):
    names = _schema_names("id_conflict")
    _ensure_custom_id_schema(hugegraph_client, names)
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'conflict')"
        f".property({_g(names.name_key)},'Existing')",
    )
    graph_data = {
        "vertices": [
            {
                "id": "alice",
                "label": names.vertex_label,
                "properties": {names.name_key: "Alice"},
            },
            {
                "id": "conflict",
                "label": names.vertex_label,
                "properties": {names.name_key: "Duplicate"},
            },
        ],
        "edges": [],
    }

    dry_run = server.import_graph_data_tool(mode="ingest", graph_data=graph_data)

    assert dry_run["ok"] is False
    assert dry_run["error"]["type"] == "INVALID_GRAPH_DATA"
    assert any(
        "create_vertex id identity already exists" in error["reason"]
        for error in dry_run["error"]["details"]["errors"]
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasLabel({_g(names.vertex_label)}).hasId('alice')",
        )
        == 0
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasLabel({_g(names.vertex_label)}).hasId('conflict')",
        )
        == 1
    )


def test_create_vertex_existing_primary_key_rejected_in_dry_run_without_writes(
    hugegraph_client,
):
    names = _schema_names("pk_conflict")
    _ensure_primary_key_schema(hugegraph_client, names)
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property({_g(names.name_key)},'Conflict')",
    )
    graph_data = {
        "vertices": [
            {
                "label": names.vertex_label,
                "properties": {names.name_key: "Alice"},
            },
            {
                "label": names.vertex_label,
                "properties": {names.name_key: "Conflict"},
            },
        ],
        "edges": [],
    }

    dry_run = server.import_graph_data_tool(mode="ingest", graph_data=graph_data)

    assert dry_run["ok"] is False
    assert dry_run["error"]["type"] == "INVALID_GRAPH_DATA"
    assert any(
        "create_vertex primary_key identity already exists" in error["reason"]
        for error in dry_run["error"]["details"]["errors"]
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasLabel({_g(names.vertex_label)})"
            f".has({_g(names.name_key)},'Alice')",
        )
        == 0
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasLabel({_g(names.vertex_label)})"
            f".has({_g(names.name_key)},'Conflict')",
        )
        == 1
    )


def test_public_delete_edge_and_vertices_real_graph_state_matches(
    hugegraph_client,
):
    names = _schema_names("delete")
    _ensure_primary_key_schema(hugegraph_client, names)
    graph_data = {
        "vertices": [
            {
                "label": names.vertex_label,
                "properties": {names.name_key: "Alice"},
            },
            {
                "label": names.vertex_label,
                "properties": {names.name_key: "Bob"},
            },
        ],
        "edges": [
            {
                "label": names.edge_label,
                "source_label": names.vertex_label,
                "source": {names.name_key: "Alice"},
                "target_label": names.vertex_label,
                "target": {names.name_key: "Bob"},
            }
        ],
    }

    result = _import_graph_data(graph_data)

    assert result["ok"] is True
    assert _count(hugegraph_client, f"g.V().hasLabel({_g(names.vertex_label)})") == 2
    assert _count(hugegraph_client, f"g.E().hasLabel({_g(names.edge_label)})") == 1

    edge_delete_plan = {
        "operations": [
            {
                "op": "delete_edge",
                "label": names.edge_label,
                "source_label": names.vertex_label,
                "source_match": {names.name_key: "Alice"},
                "target_label": names.vertex_label,
                "target_match": {names.name_key: "Bob"},
            }
        ]
    }
    result = _delete_graph_data(edge_delete_plan)

    assert result["ok"] is True
    assert _count(hugegraph_client, f"g.E().hasLabel({_g(names.edge_label)})") == 0
    assert _count(hugegraph_client, f"g.V().hasLabel({_g(names.vertex_label)})") == 2

    vertex_delete_plan = {
        "operations": [
            {
                "op": "delete_vertex",
                "label": names.vertex_label,
                "match": {names.name_key: "Alice"},
            },
            {
                "op": "delete_vertex",
                "label": names.vertex_label,
                "match": {names.name_key: "Bob"},
            },
        ]
    }
    result = _delete_graph_data(vertex_delete_plan)

    assert result["ok"] is True
    assert _count(hugegraph_client, f"g.V().hasLabel({_g(names.vertex_label)})") == 0


def test_edge_by_id_query_and_mutate_handles_real_hugegraph_edge_id(
    hugegraph_client,
):
    names = _schema_names("edge_id")
    _ensure_primary_key_schema(hugegraph_client, names)
    graph_data = {
        "vertices": [
            {
                "label": names.vertex_label,
                "properties": {names.name_key: "Alice"},
            },
            {
                "label": names.vertex_label,
                "properties": {names.name_key: "Bob"},
            },
        ],
        "edges": [
            {
                "label": names.edge_label,
                "source_label": names.vertex_label,
                "source": {names.name_key: "Alice"},
                "target_label": names.vertex_label,
                "target": {names.name_key: "Bob"},
            }
        ],
    }

    result = _import_graph_data(graph_data)

    assert result["ok"] is True
    edge_id = _edge_id(hugegraph_client, names)
    assert ">" in edge_id

    query_result = server.query_graph_data_tool(
        target="edge",
        operation="get_by_id",
        id=edge_id,
    )

    assert query_result["ok"] is True
    assert query_result["data"]["items"][0]["id"] == edge_id

    dry_run = server.mutate_graph_properties_tool(
        target="edge",
        operation="append",
        id=edge_id,
        properties={names.name_key: "friendship"},
    )
    assert dry_run["ok"] is True
    plan_context = dry_run["data"]["plan_context"]
    apply_result = server.mutate_graph_properties_tool(
        target="edge",
        operation="append",
        id=edge_id,
        properties={names.name_key: "friendship"},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_context["nonce"],
        expires_at=plan_context["expires_at"],
    )

    assert apply_result["ok"] is True
    query_result = server.query_graph_data_tool(
        target="edge",
        operation="get_by_id",
        id=edge_id,
    )
    assert (
        query_result["data"]["items"][0]["properties"][names.name_key] == "friendship"
    )

    dry_run = server.mutate_graph_properties_tool(
        target="edge",
        operation="eliminate",
        id=edge_id,
        properties={names.name_key: "friendship"},
    )
    assert dry_run["ok"] is True
    plan_context = dry_run["data"]["plan_context"]
    apply_result = server.mutate_graph_properties_tool(
        target="edge",
        operation="eliminate",
        id=edge_id,
        properties={names.name_key: "friendship"},
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_context["nonce"],
        expires_at=plan_context["expires_at"],
    )

    assert apply_result["ok"] is True
    query_result = server.query_graph_data_tool(
        target="edge",
        operation="get_by_id",
        id=edge_id,
    )
    assert names.name_key not in query_result["data"]["items"][0]["properties"]


def test_collection_append_matches_real_vertex_list_and_edge_set(hugegraph_client):
    names = _schema_names("collection_append")
    _ensure_collection_schema(hugegraph_client, names)
    graph = hugegraph_client.graph()
    alice = graph.addVertex(
        names.vertex_label,
        {names.name_key: "Alice", names.list_key: ["a"]},
    )
    bob = graph.addVertex(
        names.vertex_label,
        {names.name_key: "Bob"},
    )
    edge = graph.addEdge(
        names.edge_label,
        alice.id,
        bob.id,
        {names.set_key: ["a"]},
    )

    vertex_dry_run = server.mutate_graph_properties_tool(
        target="vertex",
        operation="append",
        id=alice.id,
        properties={names.list_key: ["b", "b"]},
    )
    assert vertex_dry_run["ok"] is True
    assert vertex_dry_run["data"]["after"]["properties"][names.list_key] == [
        "a",
        "b",
        "b",
    ]
    vertex_context = vertex_dry_run["data"]["plan_context"]
    vertex_result = server.mutate_graph_properties_tool(
        target="vertex",
        operation="append",
        id=alice.id,
        properties={names.list_key: ["b", "b"]},
        dry_run=False,
        confirm=True,
        plan_hash=vertex_dry_run["data"]["plan_hash"],
        nonce=vertex_context["nonce"],
        expires_at=vertex_context["expires_at"],
    )
    assert vertex_result["ok"] is True
    assert graph.getVertexById(alice.id).properties[names.list_key] == ["a", "b", "b"]

    edge_dry_run = server.mutate_graph_properties_tool(
        target="edge",
        operation="append",
        id=edge.id,
        properties={names.set_key: ["b", "a"]},
    )
    assert edge_dry_run["ok"] is True
    assert edge_dry_run["data"]["after"]["properties"][names.set_key] == ["a", "b"]
    edge_context = edge_dry_run["data"]["plan_context"]
    edge_result = server.mutate_graph_properties_tool(
        target="edge",
        operation="append",
        id=edge.id,
        properties={names.set_key: ["b", "a"]},
        dry_run=False,
        confirm=True,
        plan_hash=edge_dry_run["data"]["plan_hash"],
        nonce=edge_context["nonce"],
        expires_at=edge_context["expires_at"],
    )
    assert edge_result["ok"] is True
    assert set(graph.getEdgeById(edge.id).properties[names.set_key]) == {"a", "b"}


def test_partial_write_returns_error_envelope_and_real_graph_state_matches(
    hugegraph_client,
):
    names = _schema_names("partial")
    _ensure_custom_id_schema(hugegraph_client, names, unique_name=True)
    graph_data = {
        "vertices": [
            {
                "label": names.vertex_label,
                "id": "alice",
                "properties": {names.name_key: "Duplicate"},
            },
            {
                "label": names.vertex_label,
                "id": "conflict",
                "properties": {names.name_key: "Duplicate"},
            },
        ],
        "edges": [],
    }
    dry_run = server.import_graph_data_tool(mode="ingest", graph_data=graph_data)
    assert dry_run["ok"] is True

    plan_context = dry_run["data"]["plan_context"]

    result = server.import_graph_data_tool(
        mode="ingest",
        graph_data=graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_context["nonce"],
        expires_at=plan_context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["details"]["status"] == "partial"
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasLabel({_g(names.vertex_label)}).hasId('alice')",
        )
        == 1
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasLabel({_g(names.vertex_label)})"
            f".hasId('conflict').has({_g(names.name_key)},'Duplicate')",
        )
        == 0
    )


def test_public_ingest_readonly_gate_prevents_real_write(hugegraph_client, monkeypatch):
    names = _schema_names("readonly")
    _ensure_custom_id_schema(hugegraph_client, names)
    graph_data = {
        "vertices": [
            {
                "id": "readonly_alice",
                "label": names.vertex_label,
                "properties": {names.name_key: "Alice"},
            }
        ],
        "edges": [],
    }
    dry_run = server.import_graph_data_tool(mode="ingest", graph_data=graph_data)
    assert dry_run["ok"] is True
    plan_context = dry_run["data"]["plan_context"]

    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    result = server.import_graph_data_tool(
        mode="ingest",
        graph_data=graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_context["nonce"],
        expires_at=plan_context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "READONLY_VIOLATION"
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasLabel({_g(names.vertex_label)}).hasId('readonly_alice')",
        )
        == 0
    )


def test_admin_write_tool_gate_prevents_real_write(hugegraph_client, monkeypatch):
    names = _schema_names("admin")
    _ensure_custom_id_schema(hugegraph_client, names)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "false")

    result = server.execute_gremlin_write_tool(
        gremlin_query=(
            f"g.addV({_g(names.vertex_label)}).property(T.id,'admin_blocked')"
            f".property({_g(names.name_key)},'Blocked')"
        )
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasLabel({_g(names.vertex_label)}).hasId('admin_blocked')",
        )
        == 0
    )


def _import_graph_data(graph_data: dict) -> dict:
    dry_run = server.import_graph_data_tool(mode="ingest", graph_data=graph_data)
    assert dry_run["ok"] is True
    plan_context = dry_run["data"]["plan_context"]
    return server.import_graph_data_tool(
        mode="ingest",
        graph_data=graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_context["nonce"],
        expires_at=plan_context["expires_at"],
    )


def _delete_graph_data(change_plan: dict) -> dict:
    dry_run = server.delete_graph_data_tool(change_plan=change_plan)
    assert dry_run["ok"] is True
    plan_context = dry_run["data"]["plan_context"]
    return server.delete_graph_data_tool(
        change_plan=change_plan,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_context["nonce"],
        expires_at=plan_context["expires_at"],
    )


class _Names:
    def __init__(self, prefix: str) -> None:
        suffix = uuid4().hex[:8]
        self.name_key = f"{prefix}_name_{suffix}"
        self.list_key = f"{prefix}_list_{suffix}"
        self.set_key = f"{prefix}_set_{suffix}"
        self.vertex_label = f"{prefix}_v_{suffix}"
        self.edge_label = f"{prefix}_e_{suffix}"
        self.name_index = f"{prefix}_name_idx_{suffix}"


def _schema_names(prefix: str) -> _Names:
    return _Names(prefix)


def _ensure_custom_id_schema(
    client,
    names: _Names,
    *,
    unique_name: bool = False,
) -> None:
    schema = client.schema()
    schema.propertyKey(names.name_key).asText().ifNotExist().create()
    schema.vertexLabel(names.vertex_label).properties(
        names.name_key
    ).useCustomizeStringId().nullableKeys(names.name_key).ifNotExist().create()
    schema.edgeLabel(names.edge_label).sourceLabel(names.vertex_label).targetLabel(
        names.vertex_label
    ).properties(names.name_key).nullableKeys(names.name_key).ifNotExist().create()
    index = (
        schema.indexLabel(names.name_index).onV(names.vertex_label).by(names.name_key)
    )
    if unique_name:
        index.unique().ifNotExist().create()
    else:
        index.secondary().ifNotExist().create()
    _wait_for_schema_visibility(client, names, custom_id=True)


def _ensure_primary_key_schema(client, names: _Names) -> None:
    schema = client.schema()
    schema.propertyKey(names.name_key).asText().ifNotExist().create()
    schema.vertexLabel(names.vertex_label).properties(names.name_key).primaryKeys(
        names.name_key
    ).ifNotExist().create()
    schema.edgeLabel(names.edge_label).sourceLabel(names.vertex_label).targetLabel(
        names.vertex_label
    ).properties(names.name_key).nullableKeys(names.name_key).ifNotExist().create()
    _wait_for_schema_visibility(client, names)


def _ensure_collection_schema(client, names: _Names) -> None:
    schema = client.schema()
    schema.propertyKey(names.name_key).asText().ifNotExist().create()
    schema.propertyKey(names.list_key).asText().valueList().ifNotExist().create()
    schema.propertyKey(names.set_key).asText().valueSet().ifNotExist().create()
    schema.vertexLabel(names.vertex_label).properties(
        names.name_key, names.list_key
    ).primaryKeys(names.name_key).nullableKeys(names.list_key).ifNotExist().create()
    schema.edgeLabel(names.edge_label).sourceLabel(names.vertex_label).targetLabel(
        names.vertex_label
    ).properties(names.set_key).nullableKeys(names.set_key).ifNotExist().create()
    _wait_for_schema_visibility(
        client,
        names,
        required_property_keys={names.name_key, names.list_key, names.set_key},
    )


def _exec(client, query: str):
    return client.gremlin().exec(query)


def _count(client, query: str) -> int:
    return int(_extract_count(_exec(client, f"{query}.count()")) or 0)


def _edge_id(client, names: _Names) -> str:
    data = _exec(client, f"g.E().hasLabel({_g(names.edge_label)}).id()")
    edge_id = _extract_count(data)
    assert isinstance(edge_id, str)
    return edge_id


def _wait_for_schema_visibility(
    client,
    names: _Names,
    *,
    custom_id: bool = False,
    required_property_keys: set[str] | None = None,
) -> None:
    deadline = time.monotonic() + 5.0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            schema = client.schema().getSchema()
            schema_payload = (
                schema.get("schema", schema) if isinstance(schema, dict) else {}
            )
            property_keys = {
                item.get("name")
                for item in schema_payload.get("propertykeys", [])
                if isinstance(item, dict)
            }
            vertex_labels = {
                item.get("name")
                for item in schema_payload.get("vertexlabels", [])
                if isinstance(item, dict)
            }
            edge_labels = {
                item.get("name")
                for item in schema_payload.get("edgelabels", [])
                if isinstance(item, dict)
            }
            if (
                (required_property_keys or {names.name_key}) <= property_keys
                and names.vertex_label in vertex_labels
                and names.edge_label in edge_labels
            ):
                _write_and_drop_schema_probe(client, names, custom_id=custom_id)
                return
        except Exception as exc:  # noqa: BLE001 - retry until service is ready
            last_error = exc
        time.sleep(0.1)
    pytest.fail(
        "Timed out waiting for HugeGraph schema visibility: "
        f"{names.vertex_label}, last_error={last_error}"
    )


def _write_and_drop_schema_probe(
    client,
    names: _Names,
    *,
    custom_id: bool,
) -> None:
    probe_value = f"__schema_probe_{uuid4().hex}"
    add_vertex = (
        f"g.addV({_g(names.vertex_label)}).property(T.id,{_g(probe_value)})"
        f".property({_g(names.name_key)},{_g(probe_value)}).next()"
        if custom_id
        else f"g.addV({_g(names.vertex_label)}).property({_g(names.name_key)},{_g(probe_value)}).next()"
    )
    _exec(client, "v = " + add_vertex + "; g.V(v.id()).drop().iterate(); true")


def _extract_count(data):
    if isinstance(data, dict) and "data" in data:
        return _extract_count(data["data"])
    if isinstance(data, list):
        return _extract_count(data[0]) if data else 0
    return data


def _env(name: str, default: str | None = None) -> str | None:
    import os

    return os.environ.get(name, default)
