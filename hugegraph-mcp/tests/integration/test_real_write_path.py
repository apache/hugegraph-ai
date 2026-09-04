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
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from hugegraph_mcp import server
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.hugegraph_client import build_hugegraph_client
from hugegraph_mcp.tools import manage_graph_data as manage_graph_data_module
from hugegraph_mcp.tools.graph_data_gremlin import _g
from pyhugegraph.client import PyHugeClient

pytestmark = [pytest.mark.integration, pytest.mark.real_hugegraph]


@pytest.fixture
def hugegraph_client(monkeypatch):
    if _env("RUN_MCP_REAL_HUGEGRAPH_TESTS") != "1":
        pytest.skip("set RUN_MCP_REAL_HUGEGRAPH_TESTS=1 to run real HugeGraph write tests")

    monkeypatch.setenv("HUGEGRAPH_URL", _env("HUGEGRAPH_URL", "http://127.0.0.1:8080"))
    monkeypatch.setenv("HUGEGRAPH_GRAPH_PATH", _env("HUGEGRAPH_GRAPH_PATH", "DEFAULT/hugegraph"))
    monkeypatch.setenv("HUGEGRAPH_USER", _env("HUGEGRAPH_USER", "admin"))
    monkeypatch.setenv("HUGEGRAPH_PASSWORD", _env("HUGEGRAPH_PASSWORD", "admin"))
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ALLOW_AI", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "false")

    client = build_hugegraph_client(MCPConfig.from_env(), client_cls=PyHugeClient)
    deadline = time.monotonic() + 60.0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client.schema().getSchema()
            break
        except Exception as exc:  # noqa: BLE001 - service startup is asynchronous
            last_error = exc
            time.sleep(1.0)
    else:
        pytest.fail(f"HugeGraph Server is not available: {last_error}")
    return client


def test_id_based_ingest_is_preview_only_without_create_capability(
    hugegraph_client,
):
    names = _schema_names("id_edge")
    _ensure_custom_id_schema(hugegraph_client, names)
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'decoy').property({_g(names.name_key)},'Alice')",
    )
    alice_id = f"alice_{uuid4().hex}"
    bob_id = f"bob_{uuid4().hex}"

    graph_data = {
        "vertices": [
            {
                "id": alice_id,
                "label": names.vertex_label,
                "properties": {names.name_key: "Alice"},
            },
            {
                "id": bob_id,
                "label": names.vertex_label,
                "properties": {names.name_key: "Bob"},
            },
        ],
        "edges": [
            {
                "label": names.edge_label,
                "source_label": names.vertex_label,
                "target_label": names.vertex_label,
                "source": {"id": alice_id},
                "target": {"id": bob_id},
            }
        ],
    }

    result = _import_graph_data(graph_data)

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasId({_g(alice_id)},{_g(bob_id)})",
        )
        == 0
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasId({_g(alice_id)}).out({_g(names.edge_label)}).hasId({_g(bob_id)})",
        )
        == 0
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
        {
            "type": "create_edge_label",
            "name": f"mcp_schema_edge_{suffix}",
            "source_label": label_name,
            "target_label": label_name,
            "enable_label_index": True,
            "user_data": {"owner": "mcp-integration-edge"},
        },
    ]

    for operation in operations:
        applied = _apply_schema_operation(operation)
        assert applied["data"]["status"] == "APPLIED"
        assert applied["data"]["operations"][0]["status"] == "APPLIED"
        receipt = applied["data"]["operations"][0]["receipt"]
        assert receipt["status"] == "APPLIED"
        assert receipt["reason_code"] == "SCHEMA_CREATED"
        assert receipt["committed_at"] is not None

    schema = hugegraph_client.schema().getSchema()
    raw_schema = schema.get("schema", schema)
    property_key = next(item for item in raw_schema["propertykeys"] if item.get("name") == property_name)
    vertex_label = next(item for item in raw_schema["vertexlabels"] if item.get("name") == label_name)
    edge_label = next(item for item in raw_schema["edgelabels"] if item.get("name") == f"mcp_schema_edge_{suffix}")
    assert _user_data_without_server_metadata(property_key.get("user_data")) == {"owner": "mcp-integration"}
    assert vertex_label.get("enable_label_index") is False
    assert _user_data_without_server_metadata(vertex_label.get("user_data")) == {"owner": "mcp-integration"}
    assert edge_label.get("enable_label_index") is True
    assert _user_data_without_server_metadata(edge_label.get("user_data")) == {"owner": "mcp-integration-edge"}


def test_create_edge_rejects_missing_endpoint(hugegraph_client):
    names = _schema_names("missing")
    _ensure_custom_id_schema(hugegraph_client, names)
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'alice').property({_g(names.name_key)},'Alice')",
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
    assert any("target endpoint matched_count must be 1" in error["reason"] for error in result["errors"])
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
        f"g.addV({_g(names.vertex_label)}).property(T.id,'alice_1').property({_g(names.name_key)},'Alice')",
    )
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'alice_2').property({_g(names.name_key)},'Alice')",
    )
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'bob').property({_g(names.name_key)},'Bob')",
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
    assert any("source endpoint matched_count must be 1" in error["reason"] for error in result["errors"])
    assert (
        _count(
            hugegraph_client,
            f"g.V().has({_g(names.name_key)},'Alice').out({_g(names.edge_label)})",
        )
        == 0
    )


def test_create_edge_uses_endpoint_ids_bound_before_predicate_expands(
    hugegraph_client,
):
    names = _schema_names("edge_bound_ids")
    _ensure_custom_id_schema(hugegraph_client, names)
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'alice-original').property({_g(names.name_key)},'Alice')",
    )
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'bob').property({_g(names.name_key)},'Bob')",
    )
    change_plan = {
        "operations": [
            {
                "op": "create_edge",
                "label": names.edge_label,
                "source_label": names.vertex_label,
                "source_match": {names.name_key: "Alice"},
                "target_label": names.vertex_label,
                "target_match": {names.name_key: "Bob"},
            }
        ]
    }

    dry_run = manage_graph_data_module.dry_run_graph_change_plan(
        change_plan,
        manage_graph_data_module._fetch_live_schema(),
    )
    assert dry_run["valid"] is True
    operation = dry_run["compiled_plan"]["operations"][0]
    assert operation["source_id"] == "alice-original"
    assert operation["target_id"] == "bob"

    # Expand the approved predicate after planning. The executor must retain
    # the original backend identity instead of matching both Alice vertices.
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,'alice-concurrent').property({_g(names.name_key)},'Alice')",
    )
    result = manage_graph_data_module.execute_graph_change_plan(dry_run["compiled_plan"])

    assert result["success"] is True
    assert _count(hugegraph_client, f"g.E().hasLabel({_g(names.edge_label)})") == 1
    assert (
        _count(
            hugegraph_client,
            f"g.V('alice-original').out({_g(names.edge_label)}).hasId('bob')",
        )
        == 1
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V('alice-concurrent').out({_g(names.edge_label)})",
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
        f"g.addV({_g(names.vertex_label)}).property(T.id,'conflict').property({_g(names.name_key)},'Existing')",
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
        "create_vertex id identity already exists" in error["reason"] for error in dry_run["error"]["details"]["errors"]
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
            f"g.V().hasLabel({_g(names.vertex_label)}).has({_g(names.name_key)},'Alice')",
        )
        == 0
    )
    assert (
        _count(
            hugegraph_client,
            f"g.V().hasLabel({_g(names.vertex_label)}).has({_g(names.name_key)},'Conflict')",
        )
        == 1
    )


def test_public_delete_edge_and_vertices_real_graph_state_matches(
    hugegraph_client,
):
    names = _schema_names("delete")
    _ensure_custom_id_schema(hugegraph_client, names)
    alice_id = f"{names.vertex_label}_alice"
    bob_id = f"{names.vertex_label}_bob"
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,{_g(alice_id)}).property({_g(names.name_key)},'Alice')",
    )
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,{_g(bob_id)}).property({_g(names.name_key)},'Bob')",
    )
    edge_create = f"g.V({_g(alice_id)}).as('s').V({_g(bob_id)}).addE({_g(names.edge_label)}).from('s')"
    _exec(hugegraph_client, edge_create)

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

    # The canonical plan-id path deletes the same stable edge identity.
    _exec(hugegraph_client, edge_create)
    canonical_preview = server.delete_graph_data_tool(change_plan=edge_delete_plan)
    assert canonical_preview["ok"] is True
    canonical_result = server.confirm_write_tool(plan_id=canonical_preview["data"]["plan_id"])
    assert canonical_result["ok"] is True
    assert canonical_result["data"]["status"] == "APPLIED"
    assert _count(hugegraph_client, f"g.E().hasLabel({_g(names.edge_label)})") == 0

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

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert _count(hugegraph_client, f"g.V().hasLabel({_g(names.vertex_label)})") == 2


def test_delete_confirmation_uses_dry_run_bound_vertex_id(hugegraph_client):
    names = _schema_names("bound_delete")
    _ensure_custom_id_schema(hugegraph_client, names)
    original_id = f"original_{uuid4().hex}"
    late_match_id = f"late_match_{uuid4().hex}"
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,{_g(original_id)}).property({_g(names.name_key)},'Shared')",
    )
    change_plan = {
        "operations": [
            {
                "op": "delete_vertex",
                "label": names.vertex_label,
                "match": {names.name_key: "Shared"},
                "cascade": False,
            }
        ]
    }

    dry_run = server.delete_graph_data_tool(change_plan=change_plan)
    assert dry_run["ok"] is True
    assert dry_run["data"]["confirmable"] is False
    assert dry_run["data"]["preview"][0]["target_id"] == original_id

    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,{_g(late_match_id)}).property({_g(names.name_key)},'Shared')",
    )
    context = dry_run["data"]["plan_context"]
    result = server.delete_graph_data_tool(
        change_plan=change_plan,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert _count(hugegraph_client, f"g.V({_g(original_id)})") == 1
    assert _count(hugegraph_client, f"g.V({_g(late_match_id)})") == 1


def test_delete_vertex_without_cascade_is_blocked_if_edge_added_after_dry_run(
    hugegraph_client,
):
    names = _schema_names("conditional_delete")
    _ensure_custom_id_schema(hugegraph_client, names)
    alice_id = f"alice_{uuid4().hex}"
    bob_id = f"bob_{uuid4().hex}"
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,{_g(alice_id)}).property({_g(names.name_key)},'Alice')",
    )
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,{_g(bob_id)}).property({_g(names.name_key)},'Bob')",
    )
    change_plan = {
        "operations": [
            {
                "op": "delete_vertex",
                "label": names.vertex_label,
                "match": {"id": alice_id},
                "cascade": False,
            }
        ]
    }

    dry_run = server.delete_graph_data_tool(change_plan=change_plan)
    assert dry_run["ok"] is True
    _exec(
        hugegraph_client,
        f"g.V({_g(alice_id)}).as('s').V({_g(bob_id)}).addE({_g(names.edge_label)}).from('s').next()",
    )
    assert _count(hugegraph_client, f"g.V({_g(alice_id)}).bothE()") == 1
    context = dry_run["data"]["plan_context"]
    result = server.delete_graph_data_tool(
        change_plan=change_plan,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=context["nonce"],
        expires_at=context["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert _count(hugegraph_client, f"g.V({_g(alice_id)})") == 1
    assert _count(hugegraph_client, f"g.V({_g(bob_id)})") == 1
    assert _count(hugegraph_client, f"g.E().hasLabel({_g(names.edge_label)})") == 1


@pytest.mark.xfail(
    reason="HugeGraph 1.7.0/RocksDB did not isolate concurrent edge-add and conditional vertex-delete",
    # This is a stochastic concurrency probe. An XPASS means only that this
    # run did not observe the known bad interleaving; it is not proof that the
    # backend provides the isolation capability.
    strict=False,
)
def test_rocksdb_isolates_conditional_vertex_delete_from_concurrent_edge_add(
    hugegraph_client,
):
    """Probe the HugeGraph 1.7.0/RocksDB delete capability profile.

    A client-side check followed by a delete cannot establish this property.  Both
    writes must race as separate server requests, released by the same barrier,
    and every committed outcome must be one of the two serializable outcomes:

    * delete wins, so edge creation fails and the target vertex is absent; or
    * edge creation wins, so ``not(bothE())`` prevents the vertex deletion.

    In particular, a successful edge creation followed by the vertex and edge
    disappearing would be an implicit cascade and must fail this test.
    """

    names = _schema_names("isolated_delete")
    _ensure_custom_id_schema(hugegraph_client, names)
    iterations = int(_env("MCP_ISOLATED_DELETE_STRESS_ITERATIONS", "50"))

    def race_write(query: str, start: Barrier) -> tuple[object | None, str | None]:
        client = build_hugegraph_client(MCPConfig.from_env(), client_cls=PyHugeClient)
        start.wait(timeout=10.0)
        try:
            result = _extract_count(_exec(client, query))
        except Exception as exc:  # noqa: BLE001 - record concurrent backend outcome
            return None, str(exc)
        return result, None

    violations: list[str] = []
    for iteration in range(iterations):
        alice_id = f"isolated_alice_{iteration}_{uuid4().hex}"
        bob_id = f"isolated_bob_{iteration}_{uuid4().hex}"
        _exec(
            hugegraph_client,
            f"g.addV({_g(names.vertex_label)}).property(T.id,{_g(alice_id)})"
            f".property({_g(names.name_key)},'Alice').iterate()",
        )
        _exec(
            hugegraph_client,
            f"g.addV({_g(names.vertex_label)}).property(T.id,{_g(bob_id)})"
            f".property({_g(names.name_key)},'Bob').iterate()",
        )

        start = Barrier(3)
        # count() returns 1 only when addE actually produced an edge.  An empty
        # traversal may complete without an exception after the concurrent
        # delete; treating that as a successful create would be false evidence
        # of an implicit cascade.
        add_query = f"g.V({_g(alice_id)}).as('s').V({_g(bob_id)}).addE({_g(names.edge_label)}).from('s').count()"
        delete_query = f"g.V({_g(alice_id)}).not(bothE()).drop().iterate(); true"
        with ThreadPoolExecutor(max_workers=2) as pool:
            add_future = pool.submit(race_write, add_query, start)
            delete_future = pool.submit(race_write, delete_query, start)
            start.wait(timeout=10.0)
            add_affected, add_error = add_future.result(timeout=30.0)
            delete_completed, delete_error = delete_future.result(timeout=30.0)

        alice_count = _count(hugegraph_client, f"g.V({_g(alice_id)})")
        bob_count = _count(hugegraph_client, f"g.V({_g(bob_id)})")
        edge_count = _count(
            hugegraph_client,
            f"g.V({_g(alice_id)}).outE({_g(names.edge_label)}).where(inV().hasId({_g(bob_id)}))",
        )
        observed = (add_affected, delete_completed, alice_count, bob_count, edge_count)
        allowed = {
            (None, True, 0, 1, 0),
            (0, True, 0, 1, 0),
            (1, True, 1, 1, 1),
        }
        if observed not in allowed:
            violations.append(
                f"iteration {iteration}: {observed}; add_error={add_error!r}, delete_error={delete_error!r}"
            )

        # Each iteration has unique IDs, but explicit cleanup keeps the stress
        # test bounded when the edge-add outcome wins repeatedly.
        _exec(hugegraph_client, f"g.V({_g(alice_id)},{_g(bob_id)}).drop().iterate()")

    assert not violations, f"{len(violations)} non-isolated outcomes; first 10:\n" + "\n".join(violations[:10])


def test_dry_run_rejects_edge_whose_target_vertex_is_created_later(
    hugegraph_client,
):
    names = _schema_names("future_endpoint")
    _ensure_custom_id_schema(hugegraph_client, names)
    change_plan = {
        "operations": [
            {
                "op": "create_vertex",
                "label": names.vertex_label,
                "id": "alice",
                "properties": {names.name_key: "Alice"},
            },
            {
                "op": "create_edge",
                "label": names.edge_label,
                "source_label": names.vertex_label,
                "source_match": {"id": "alice"},
                "target_label": names.vertex_label,
                "target_match": {"id": "bob"},
            },
            {
                "op": "create_vertex",
                "label": names.vertex_label,
                "id": "bob",
                "properties": {names.name_key: "Bob"},
            },
        ]
    }

    result = manage_graph_data_module.dry_run_graph_change_plan(
        change_plan,
        manage_graph_data_module._fetch_live_schema(),
    )

    assert result["valid"] is False
    assert result["preview"][1]["source_planned_count"] == 1
    assert result["preview"][1]["target_planned_count"] == 0
    assert any("target endpoint matched_count must be 1, got 0" in error["reason"] for error in result["errors"])
    assert _count(hugegraph_client, f"g.V().hasLabel({_g(names.vertex_label)})") == 0


def test_edge_by_id_query_and_mutate_handles_real_hugegraph_edge_id(
    hugegraph_client,
):
    names = _schema_names("edge_id")
    _ensure_custom_id_schema(hugegraph_client, names)
    alice_id = f"{names.vertex_label}_alice"
    bob_id = f"{names.vertex_label}_bob"
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,{_g(alice_id)}).property({_g(names.name_key)},'Alice')",
    )
    _exec(
        hugegraph_client,
        f"g.addV({_g(names.vertex_label)}).property(T.id,{_g(bob_id)}).property({_g(names.name_key)},'Bob')",
    )
    _exec(
        hugegraph_client,
        f"g.V({_g(alice_id)}).as('s').V({_g(bob_id)}).addE({_g(names.edge_label)}).from('s')",
    )
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
    before = hugegraph_client.graph().getEdgeById(edge_id).properties
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

    assert apply_result["ok"] is False
    assert apply_result["error"]["type"] == "FEATURE_DISABLED"
    assert apply_result["error"]["details"]["write_attempted"] is False
    assert hugegraph_client.graph().getEdgeById(edge_id).properties == before


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
    assert vertex_result["ok"] is False
    assert vertex_result["error"]["type"] == "FEATURE_DISABLED"
    assert vertex_result["error"]["details"]["write_attempted"] is False
    assert graph.getVertexById(alice.id).properties[names.list_key] == ["a"]

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
    assert edge_result["ok"] is False
    assert edge_result["error"]["type"] == "FEATURE_DISABLED"
    assert edge_result["error"]["details"]["write_attempted"] is False
    assert set(graph.getEdgeById(edge.id).properties[names.set_key]) == {"a"}


def test_import_partial_scenario_is_preview_only_and_has_no_side_effects(
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
    assert dry_run["data"]["confirmable"] is False

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
    assert result["error"]["type"] == "FEATURE_DISABLED"
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
            f"g.V().hasLabel({_g(names.vertex_label)}).hasId('conflict').has({_g(names.name_key)},'Duplicate')",
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
            f"g.addV({_g(names.vertex_label)}).property(T.id,'admin_blocked').property({_g(names.name_key)},'Blocked')"
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
    assert dry_run["ok"] is True, dry_run
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


def _apply_schema_operation(operation: dict) -> dict:
    operations = [operation]
    dry_run = server.apply_schema_tool(mode="dry_run", operations=operations)
    assert dry_run["ok"] is True
    assert dry_run["data"]["valid"] is True
    plan_id = dry_run["data"]["plan_id"]
    assert plan_id.startswith("wp_")
    result = server.confirm_write_tool(plan_id=plan_id)
    assert result["ok"] is True, result
    status = server.get_write_status_tool(plan_id=plan_id)
    assert status["ok"] is True
    assert status["data"] == result["data"]
    return result


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
    schema.vertexLabel(names.vertex_label).properties(names.name_key).useCustomizeStringId().nullableKeys(
        names.name_key
    ).ifNotExist().create()
    schema.edgeLabel(names.edge_label).sourceLabel(names.vertex_label).targetLabel(names.vertex_label).properties(
        names.name_key
    ).nullableKeys(names.name_key).ifNotExist().create()
    index = schema.indexLabel(names.name_index).onV(names.vertex_label).by(names.name_key)
    if unique_name:
        index.unique().ifNotExist().create()
    else:
        index.secondary().ifNotExist().create()
    _wait_for_schema_visibility(client, names, custom_id=True)


def _ensure_primary_key_schema(client, names: _Names) -> None:
    schema = client.schema()
    schema.propertyKey(names.name_key).asText().ifNotExist().create()
    schema.vertexLabel(names.vertex_label).properties(names.name_key).primaryKeys(names.name_key).ifNotExist().create()
    schema.edgeLabel(names.edge_label).sourceLabel(names.vertex_label).targetLabel(names.vertex_label).properties(
        names.name_key
    ).nullableKeys(names.name_key).ifNotExist().create()
    _wait_for_schema_visibility(client, names)


def _ensure_collection_schema(client, names: _Names) -> None:
    schema = client.schema()
    schema.propertyKey(names.name_key).asText().ifNotExist().create()
    schema.propertyKey(names.list_key).asText().valueList().ifNotExist().create()
    schema.propertyKey(names.set_key).asText().valueSet().ifNotExist().create()
    schema.vertexLabel(names.vertex_label).properties(names.name_key, names.list_key).primaryKeys(
        names.name_key
    ).nullableKeys(names.list_key).ifNotExist().create()
    schema.edgeLabel(names.edge_label).sourceLabel(names.vertex_label).targetLabel(names.vertex_label).properties(
        names.set_key
    ).nullableKeys(names.set_key).ifNotExist().create()
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
            schema_payload = schema.get("schema", schema) if isinstance(schema, dict) else {}
            property_keys = {
                item.get("name") for item in schema_payload.get("propertykeys", []) if isinstance(item, dict)
            }
            vertex_labels = {
                item.get("name") for item in schema_payload.get("vertexlabels", []) if isinstance(item, dict)
            }
            edge_labels = {item.get("name") for item in schema_payload.get("edgelabels", []) if isinstance(item, dict)}
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
    pytest.fail(f"Timed out waiting for HugeGraph schema visibility: {names.vertex_label}, last_error={last_error}")


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


def _user_data_without_server_metadata(value):
    if not isinstance(value, dict):
        return None
    return {key: item for key, item in value.items() if not (isinstance(key, str) and key.startswith("~"))}


def _env(name: str, default: str | None = None) -> str | None:
    import os

    return os.environ.get(name, default)
