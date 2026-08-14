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

import json
import re
from unittest.mock import Mock

import pytest

from hugegraph_mcp import server
from hugegraph_mcp.envelope import envelope_ok
from hugegraph_mcp.tools import ingest_graph_data as ingest_graph_data_module
from hugegraph_mcp.tools import manage_graph_data as manage_graph_data_module


def _graph_data():
    return {
        "vertices": [
            {"label": "person", "properties": {"name": "Alice"}},
            {"label": "person", "properties": {"name": "Bob"}},
        ],
        "edges": [
            {
                "label": "knows",
                "source_label": "person",
                "target_label": "person",
                "source": {"name": "Alice"},
                "target": {"name": "Bob"},
            }
        ],
    }


def _live_schema():
    return {
        "schema": {
            "vertexlabels": [
                {
                    "id": 1,
                    "name": "person",
                    "properties": [{"name": "name"}, {"name": "age"}],
                    "primary_keys": ["name"],
                },
            ],
            "edgelabels": [
                {"name": "knows", "source_label": "person", "target_label": "person"},
            ],
            "propertykeys": [
                {"name": "name", "data_type": "TEXT"},
                {"name": "age", "data_type": "INT"},
            ],
        },
    }


def _mock_schema(monkeypatch):
    monkeypatch.setattr(
        ingest_graph_data_module, "_fetch_live_schema", lambda: _live_schema()
    )


def test_ingest_graph_data_accepts_string_property_schema(monkeypatch):
    schema = _live_schema()
    schema["schema"]["vertexlabels"][0]["properties"] = ["name", "age"]
    schema["schema"]["edgelabels"][0]["properties"] = ["since"]
    monkeypatch.setattr(ingest_graph_data_module, "_fetch_live_schema", lambda: schema)

    result = ingest_graph_data_module.ingest_graph_data(
        {
            "vertices": [
                {"label": "person", "properties": {"name": "Alice", "age": 30}},
                {"label": "person", "properties": {"name": "Bob", "age": 31}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "source": {"name": "Alice"},
                    "target": {"name": "Bob"},
                    "properties": {"since": 2020},
                }
            ],
        }
    )

    assert result["ok"] is True


def test_ingest_graph_data_dry_run(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data(_graph_data())

    assert result["ok"] is True
    assert re.fullmatch(r"[0-9a-f]{32}", result["data"]["plan_hash"])
    assert result["data"]["mutation_summary"] == {"vertices": 2, "edges": 1}
    assert any("index" in w for w in result["data"]["warnings"])
    assert "duplicate vertex labels detected" not in result["data"]["warnings"]


def test_ingest_graph_data_dry_run_same_input_same_hash(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setattr("hugegraph_mcp.plan_hash.time.time", lambda: 1000)

    # Same nonce + same payload + same expiry window = same hash.
    first = ingest_graph_data_module.ingest_graph_data(
        _graph_data(), nonce="fixed_nonce"
    )
    second = ingest_graph_data_module.ingest_graph_data(
        _graph_data(), nonce="fixed_nonce"
    )

    assert first["data"]["plan_hash"] == second["data"]["plan_hash"]


def test_ingest_graph_data_plan_hash_includes_schema(monkeypatch):
    graph_data = _graph_data()
    schema = _live_schema()
    schema_with_age_text = _live_schema()
    schema_with_age_text["schema"]["propertykeys"][1]["data_type"] = "TEXT"

    first = ingest_graph_data_module.calculate_plan_hash(graph_data, schema)
    second = ingest_graph_data_module.calculate_plan_hash(
        graph_data, schema_with_age_text
    )

    assert first != second


def test_ingest_plan_hash_schema_field_order_same_hash():
    graph_data = _graph_data()
    schema = _live_schema()
    reordered_schema = _live_schema()
    reordered_schema["schema"]["propertykeys"] = list(
        reversed(reordered_schema["schema"]["propertykeys"])
    )
    reordered_schema["schema"]["vertexlabels"][0]["properties"] = [
        {"name": "age"},
        {"name": "name"},
    ]

    first = ingest_graph_data_module.calculate_plan_hash(graph_data, schema)
    second = ingest_graph_data_module.calculate_plan_hash(graph_data, reordered_schema)

    assert first == second


def test_ingest_plan_hash_schema_primary_key_change_different_hash():
    graph_data = _graph_data()
    schema = _live_schema()
    changed_schema = _live_schema()
    changed_schema["schema"]["vertexlabels"][0]["primary_keys"] = ["age"]

    first = ingest_graph_data_module.calculate_plan_hash(graph_data, schema)
    second = ingest_graph_data_module.calculate_plan_hash(graph_data, changed_schema)

    assert first != second


def test_ingest_plan_hash_schema_id_strategy_change_different_hash():
    graph_data = _graph_data()
    schema = _live_schema()
    changed_schema = _live_schema()
    changed_schema["schema"]["vertexlabels"][0]["id_strategy"] = "CUSTOMIZE_STRING"

    first = ingest_graph_data_module.calculate_plan_hash(graph_data, schema)
    second = ingest_graph_data_module.calculate_plan_hash(graph_data, changed_schema)

    assert first != second


@pytest.mark.parametrize(
    ("id_strategy", "vertex_id", "expected_error"),
    [
        (
            "CUSTOMIZE_STRING",
            None,
            "missing required id for CUSTOMIZE_STRING label 'person'",
        ),
        (
            "CUSTOMIZE_STRING",
            1,
            "id for CUSTOMIZE_STRING label 'person' must be a string, got int",
        ),
        (
            "CUSTOMIZE_NUMBER",
            None,
            "missing required id for CUSTOMIZE_NUMBER label 'person'",
        ),
        (
            "CUSTOMIZE_NUMBER",
            True,
            "id for CUSTOMIZE_NUMBER label 'person' must be an integer, got bool",
        ),
    ],
)
def test_validate_graph_payload_rejects_invalid_customize_id(
    id_strategy, vertex_id, expected_error
):
    schema = _live_schema()
    vertex_label = schema["schema"]["vertexlabels"][0]
    vertex_label["id_strategy"] = id_strategy
    vertex_label["primary_keys"] = []
    vertex = {"label": "person", "properties": {"name": "Alice"}}
    if vertex_id is not None:
        vertex["id"] = vertex_id

    result = ingest_graph_data_module.validate_graph_payload(
        {"vertices": [vertex], "edges": []}, live_schema=schema
    )

    assert result["valid"] is False
    assert any(expected_error in error for error in result["errors"])


@pytest.mark.parametrize(
    ("cardinality", "value"),
    [
        ("SINGLE", "550e8400-e29b-41d4-a716-446655440000"),
        ("LIST", ["550e8400-e29b-41d4-a716-446655440000"]),
        ("SET", ["550e8400-e29b-41d4-a716-446655440000"]),
    ],
)
def test_validate_graph_payload_accepts_uuid_property(cardinality, value):
    schema = _live_schema()
    schema["schema"]["vertexlabels"][0]["properties"].append({"name": "uid"})
    schema["schema"]["propertykeys"].append(
        {"name": "uid", "data_type": "UUID", "cardinality": cardinality}
    )

    result = ingest_graph_data_module.validate_graph_payload(
        {
            "vertices": [
                {"label": "person", "properties": {"name": "Alice", "uid": value}}
            ],
            "edges": [],
        },
        live_schema=schema,
    )

    assert result["valid"] is True, result["errors"]


def test_validate_graph_payload_rejects_non_string_uuid():
    schema = _live_schema()
    schema["schema"]["vertexlabels"][0]["properties"].append({"name": "uid"})
    schema["schema"]["propertykeys"].append(
        {"name": "uid", "data_type": "UUID", "cardinality": "SINGLE"}
    )

    result = ingest_graph_data_module.validate_graph_payload(
        {
            "vertices": [
                {"label": "person", "properties": {"name": "Alice", "uid": 1}}
            ],
            "edges": [],
        },
        live_schema=schema,
    )

    assert result["valid"] is False
    assert any("expects UUID, got int" in error for error in result["errors"])


@pytest.mark.parametrize(
    ("id_strategy", "vertex_id"),
    [("CUSTOMIZE_STRING", "person-1"), ("CUSTOMIZE_NUMBER", 1)],
)
def test_validate_graph_payload_accepts_valid_customize_id(id_strategy, vertex_id):
    schema = _live_schema()
    vertex_label = schema["schema"]["vertexlabels"][0]
    vertex_label["idStrategy"] = id_strategy
    vertex_label["primary_keys"] = []

    result = ingest_graph_data_module.validate_graph_payload(
        {
            "vertices": [
                {
                    "id": vertex_id,
                    "label": "person",
                    "properties": {"name": "Alice"},
                }
            ],
            "edges": [],
        },
        live_schema=schema,
    )

    assert result["valid"] is True


def test_ingest_plan_hash_schema_metadata_ignored_same_hash():
    graph_data = _graph_data()
    schema = _live_schema()
    schema_with_metadata = _live_schema()
    schema_with_metadata["schema"]["propertykeys"][0]["id"] = 1
    schema_with_metadata["schema"]["propertykeys"][0]["user_data"] = {"x": "y"}
    schema_with_metadata["schema"]["vertexlabels"][0]["id"] = 99
    schema_with_metadata["server_time"] = "2026-05-26T00:00:00Z"

    first = ingest_graph_data_module.calculate_plan_hash(graph_data, schema)
    second = ingest_graph_data_module.calculate_plan_hash(
        graph_data, schema_with_metadata
    )

    assert first == second


def test_ingest_plan_hash_graph_data_order_same_hash():
    graph_data = _graph_data()
    reordered_graph_data = {
        "edges": [
            {
                "target": {"name": "Bob"},
                "source": {"name": "Alice"},
                "target_label": "person",
                "source_label": "person",
                "label": "knows",
            }
        ],
        "vertices": [
            {"properties": {"name": "Bob"}, "label": "person"},
            {"properties": {"name": "Alice"}, "label": "person"},
        ],
    }

    first = ingest_graph_data_module.calculate_plan_hash(graph_data, _live_schema())
    second = ingest_graph_data_module.calculate_plan_hash(
        reordered_graph_data,
        _live_schema(),
    )

    assert first == second


def test_ingest_graph_data_validate_invalid(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data({"vertices": [{}], "edges": []})

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert "missing required field: label" in result["error"]["details"]["errors"][0]


def test_ingest_graph_data_rejects_when_live_schema_unavailable(monkeypatch):
    monkeypatch.setattr(ingest_graph_data_module, "_fetch_live_schema", lambda: None)

    result = ingest_graph_data_module.ingest_graph_data(
        {"vertices": [{"label": "x"}], "edges": []}
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "CONNECTION_FAILED"
    assert "Cannot read live schema" in result["error"]["message"]


def test_ingest_graph_data_schema_mismatch(monkeypatch):
    _mock_schema(monkeypatch)

    # Edge source_label='ghost' does not exist in schema
    bad_data = {
        "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
        "edges": [
            {
                "label": "knows",
                "source_label": "ghost",
                "target_label": "person",
            }
        ],
    }

    result = ingest_graph_data_module.ingest_graph_data(bad_data)

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert any(
        "source_label 'ghost'" in e for e in result["error"]["details"]["errors"]
    )


def test_validate_graph_payload_rejects_labels_when_live_schema_is_empty():
    empty_schema = {
        "schema": {
            "propertykeys": [],
            "vertexlabels": [],
            "edgelabels": [],
            "indexlabels": [],
        }
    }

    result = ingest_graph_data_module.validate_graph_payload(
        {
            "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "source": {"name": "Alice"},
                    "target": {"name": "Bob"},
                }
            ],
        },
        live_schema=empty_schema,
    )

    assert result["valid"] is False
    assert "vertex 0 label 'person' does not exist in schema" in result["errors"]
    assert "edge 0 label 'knows' does not exist in schema" in result["errors"]
    assert "edge 0 source_label 'person' does not exist in schema" in result["errors"]
    assert "edge 0 target_label 'person' does not exist in schema" in result["errors"]


def test_ingest_graph_data_rejects_property_type_mismatch(monkeypatch):
    _mock_schema(monkeypatch)

    bad_data = {
        "vertices": [{"label": "person", "properties": {"name": "Alice", "age": "30"}}],
        "edges": [],
    }

    result = ingest_graph_data_module.ingest_graph_data(bad_data)

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert any(
        "property 'age' expects INT" in e for e in result["error"]["details"]["errors"]
    )


def _collection_schema():
    schema = _live_schema()
    schema["schema"]["propertykeys"].extend(
        [
            {"propertyName": "aliases", "dataType": "TEXT", "cardinalityType": "LIST"},
            {"name": "scores", "data_type": "INTEGER", "cardinality": "LIST"},
            {"name": "flags", "data_type": "BOOL", "cardinality": "LIST"},
            {"name": "metadata", "data_type": "OBJECT", "cardinality": "SINGLE"},
            {"name": "tags", "data_type": "TEXT", "cardinality": "SET"},
            {"name": "since", "data_type": "INT"},
        ]
    )
    schema["schema"]["vertexlabels"][0]["properties"].extend(
        [
            {"name": "aliases"},
            {"name": "scores"},
            {"name": "flags"},
            {"name": "metadata"},
        ]
    )
    schema["schema"]["edgelabels"][0]["properties"] = ["tags", "since"]
    return schema


def _collection_graph_data():
    return {
        "vertices": [
            {
                "label": "person",
                "properties": {
                    "name": "Alice",
                    "aliases": ["Al", "A"],
                    "scores": [1, 2],
                    "flags": [True, False],
                    "metadata": {"source": "test"},
                },
            },
            {"label": "person", "properties": {"name": "Bob"}},
        ],
        "edges": [
            {
                "label": "knows",
                "source_label": "person",
                "target_label": "person",
                "source": {"name": "Alice"},
                "target": {"name": "Bob"},
                "properties": {"tags": ["friend", "work"]},
            }
        ],
    }


def test_ingest_graph_data_accepts_vertex_list_and_edge_set_properties(monkeypatch):
    schema = _collection_schema()
    monkeypatch.setattr(ingest_graph_data_module, "_fetch_live_schema", lambda: schema)

    result = ingest_graph_data_module.ingest_graph_data(_collection_graph_data())

    assert result["ok"] is True
    assert result["data"]["mutation_summary"] == {"vertices": 2, "edges": 1}


@pytest.mark.parametrize(
    "property_keys_field", ["propertykeys", "property_keys", "propertyKeys"]
)
def test_validate_graph_payload_accepts_property_key_collection_aliases(
    property_keys_field,
):
    schema = _collection_schema()
    property_keys = schema["schema"].pop("propertykeys")
    schema["schema"][property_keys_field] = property_keys

    result = ingest_graph_data_module.validate_graph_payload(
        _collection_graph_data(),
        live_schema=schema,
    )

    assert result["valid"] is True


def test_validate_graph_payload_accepts_empty_collection():
    graph_data = _collection_graph_data()
    graph_data["vertices"][0]["properties"]["aliases"] = []

    result = ingest_graph_data_module.validate_graph_payload(
        graph_data,
        live_schema=_collection_schema(),
    )

    assert result["valid"] is True


def test_validate_graph_payload_preserves_top_level_none_but_rejects_none_element():
    top_level_none = _collection_graph_data()
    top_level_none["vertices"][0]["properties"]["aliases"] = None
    collection_none = _collection_graph_data()
    collection_none["vertices"][0]["properties"]["aliases"] = ["Al", None]

    allowed = ingest_graph_data_module.validate_graph_payload(
        top_level_none,
        live_schema=_collection_schema(),
    )
    rejected = ingest_graph_data_module.validate_graph_payload(
        collection_none,
        live_schema=_collection_schema(),
    )

    assert allowed["valid"] is True
    assert rejected["valid"] is False
    assert (
        "vertex 0 property 'aliases' element 1 expects TEXT, got NoneType"
        in rejected["errors"]
    )
    assert all("Al" not in error for error in rejected["errors"])


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("cardinality", "MANY", "unsupported cardinality 'MANY'"),
        ("data_type", "DECIMAL", "unsupported data_type 'DECIMAL'"),
    ],
)
def test_validate_graph_payload_rejects_unsupported_property_spec(
    field, value, expected
):
    schema = _collection_schema()
    aliases = next(
        item
        for item in schema["schema"]["propertykeys"]
        if (item.get("name") or item.get("propertyName")) == "aliases"
    )
    aliases[field] = value
    if field == "cardinality":
        aliases.pop("cardinalityType", None)
    else:
        aliases.pop("dataType", None)

    result = ingest_graph_data_module.validate_graph_payload(
        _collection_graph_data(),
        live_schema=schema,
    )

    assert result["valid"] is False
    assert f"vertex 0 property 'aliases' {expected}" in result["errors"]


def test_validate_graph_payload_validates_object_as_json_object():
    valid = ingest_graph_data_module.validate_graph_payload(
        _collection_graph_data(),
        live_schema=_collection_schema(),
    )
    invalid_data = _collection_graph_data()
    invalid_data["vertices"][0]["properties"]["metadata"] = ["not", "an", "object"]
    invalid = ingest_graph_data_module.validate_graph_payload(
        invalid_data,
        live_schema=_collection_schema(),
    )

    assert valid["valid"] is True
    assert invalid["valid"] is False
    assert "vertex 0 property 'metadata' expects OBJECT, got list" in invalid["errors"]


def test_validate_graph_payload_rejects_scalar_for_collection_property():
    graph_data = _collection_graph_data()
    graph_data["vertices"][0]["properties"]["aliases"] = "Al"

    result = ingest_graph_data_module.validate_graph_payload(
        graph_data,
        live_schema=_collection_schema(),
    )

    assert result["valid"] is False
    assert (
        "vertex 0 property 'aliases' expects LIST of TEXT, got str" in result["errors"]
    )


def test_validate_graph_payload_rejects_tuple_for_collection_property():
    graph_data = _collection_graph_data()
    graph_data["vertices"][0]["properties"]["aliases"] = ("Al", "A")

    result = ingest_graph_data_module.validate_graph_payload(
        graph_data,
        live_schema=_collection_schema(),
    )

    assert result["valid"] is False
    assert (
        "vertex 0 property 'aliases' expects LIST of TEXT, got tuple"
        in result["errors"]
    )


def test_validate_graph_payload_rejects_invalid_collection_element_without_value():
    graph_data = _collection_graph_data()
    graph_data["edges"][0]["properties"]["tags"] = ["friend", 7]

    result = ingest_graph_data_module.validate_graph_payload(
        graph_data,
        live_schema=_collection_schema(),
    )

    assert result["valid"] is False
    assert "edge 0 property 'tags' element 1 expects TEXT, got int" in result["errors"]
    assert all("friend" not in error for error in result["errors"])


def test_validate_graph_payload_rejects_bool_in_int_collection():
    graph_data = _collection_graph_data()
    graph_data["vertices"][0]["properties"]["scores"] = [1, True]

    result = ingest_graph_data_module.validate_graph_payload(
        graph_data,
        live_schema=_collection_schema(),
    )

    assert result["valid"] is False
    assert (
        "vertex 0 property 'scores' element 1 expects INT, got bool" in result["errors"]
    )


def test_validate_graph_payload_accepts_boolean_collection_and_rejects_wrong_element():
    graph_data = _collection_graph_data()

    valid = ingest_graph_data_module.validate_graph_payload(
        graph_data,
        live_schema=_collection_schema(),
    )
    graph_data["vertices"][0]["properties"]["flags"] = [True, 1]
    invalid = ingest_graph_data_module.validate_graph_payload(
        graph_data,
        live_schema=_collection_schema(),
    )

    assert valid["valid"] is True
    assert invalid["valid"] is False
    assert (
        "vertex 0 property 'flags' element 1 expects BOOLEAN, got int"
        in invalid["errors"]
    )


def test_validate_graph_payload_rejects_list_for_single_property():
    graph_data = _collection_graph_data()
    graph_data["edges"][0]["properties"]["since"] = [2020]

    result = ingest_graph_data_module.validate_graph_payload(
        graph_data,
        live_schema=_collection_schema(),
    )

    assert result["valid"] is False
    assert "edge 0 property 'since' expects INT, got list" in result["errors"]


def test_manage_graph_data_import_accepts_collections_in_dry_run(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setattr(
        manage_graph_data_module,
        "_fetch_live_schema",
        lambda: _collection_schema(),
    )
    monkeypatch.setattr(
        manage_graph_data_module.gremlin_tools,
        "execute_gremlin_read",
        lambda _query: {"data": [0], "total": 1, "is_read": True},
    )

    result = manage_graph_data_module.manage_graph_data(
        mode="import",
        graph_data=_collection_graph_data(),
    )

    assert result["ok"] is True
    assert result["data"]["confirmable"] is True
    assert result["data"]["plan_hash"]
    assert result["data"]["mutation_summary"] == {
        "create_edge": 1,
        "create_vertex": 2,
    }


def test_public_import_graph_data_rejects_invalid_collection_before_execute(
    monkeypatch,
):
    graph_data = _collection_graph_data()
    graph_data["vertices"][0]["properties"]["aliases"] = "Al"
    execute = Mock()
    monkeypatch.setattr(
        manage_graph_data_module,
        "_fetch_live_schema",
        lambda: _collection_schema(),
    )
    monkeypatch.setattr(manage_graph_data_module, "execute_graph_change_plan", execute)

    result = server.import_graph_data_tool(
        mode="ingest",
        graph_data=graph_data,
        dry_run=False,
        confirm=True,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert result["error"]["source"] == "import_graph_data_tool"
    assert (
        "vertex 0 property 'aliases' expects LIST of TEXT, got str"
        in result["error"]["details"]["errors"]
    )
    execute.assert_not_called()


def test_ingest_graph_data_rejects_missing_schema_primary_key(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data(
        {"vertices": [{"label": "person", "properties": {"age": 30}}], "edges": []}
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert any(
        "vertex 0 missing primary key value for label 'person': name" in e
        for e in result["error"]["details"]["errors"]
    )


def test_ingest_graph_data_allows_edge_target_outside_payload(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data(
        {
            "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "source": {"name": "Alice"},
                    "target": {"name": "Bob"},
                }
            ],
        }
    )

    assert result["ok"] is True
    assert result["data"]["mutation_summary"] == {"vertices": 1, "edges": 1}


def test_validate_graph_payload_allows_explicit_id_endpoint_without_primary_key():
    result = ingest_graph_data_module.validate_graph_payload(
        {
            "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "source": {"name": "Alice"},
                    "target": {"id": "1:Bob"},
                }
            ],
        },
        live_schema=_live_schema(),
    )

    assert result["valid"] is True


def test_validate_graph_payload_rejects_mixed_source_endpoint_forms():
    result = ingest_graph_data_module.validate_graph_payload(
        {
            "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "source": {"name": "Alice"},
                    "outV": "1:Alice",
                    "outVLabel": "person",
                    "target_label": "person",
                    "target": {"name": "Bob"},
                }
            ],
        },
        live_schema=_live_schema(),
    )

    assert result["valid"] is False
    assert any("mixes source and outV endpoint forms" in e for e in result["errors"])


def test_validate_graph_payload_rejects_mixed_target_endpoint_forms():
    result = ingest_graph_data_module.validate_graph_payload(
        {
            "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "source": {"name": "Alice"},
                    "target_label": "person",
                    "target": {"name": "Bob"},
                    "inV": "1:Bob",
                    "inVLabel": "person",
                }
            ],
        },
        live_schema=_live_schema(),
    )

    assert result["valid"] is False
    assert any("mixes target and inV endpoint forms" in e for e in result["errors"])


def test_ingest_graph_data_rejects_edge_endpoint_missing_primary_key(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data(
        {
            "vertices": [
                {"label": "person", "properties": {"name": "Alice"}},
                {"label": "person", "properties": {"name": "Bob"}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "source": {"name": "Alice"},
                    "target": {"age": 31},
                }
            ],
        }
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    assert any(
        "edge 0 target endpoint missing primary key for label 'person': name" in e
        for e in result["error"]["details"]["errors"]
    )


def test_validate_graph_payload_rejects_ambiguous_scalar_endpoint():
    result = ingest_graph_data_module.validate_graph_payload(
        {
            "vertices": [
                {
                    "id": "Alice",
                    "label": "person",
                    "properties": {"name": "Other Alice"},
                },
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

    assert result["valid"] is False
    assert any(
        "source scalar endpoint is ambiguous" in error for error in result["errors"]
    )


def test_ingest_graph_data_valid_payload_with_primary_key_endpoints(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data(_graph_data())

    assert result["ok"] is True
    assert result["data"]["mutation_summary"] == {"vertices": 2, "edges": 1}


def test_ingest_graph_data_resolves_outv_inv_endpoint_shape(monkeypatch):
    schema = _live_schema()
    schema["schema"]["vertexlabels"][0].pop("primary_keys")
    schema["schema"]["vertexlabels"][0]["primaryKeys"] = ["name"]
    monkeypatch.setattr(ingest_graph_data_module, "_fetch_live_schema", lambda: schema)

    result = ingest_graph_data_module.ingest_graph_data(
        {
            "vertices": [
                {"label": "person", "properties": {"name": "Alice"}},
                {"label": "person", "properties": {"name": "Bob"}},
            ],
            "edges": [
                {
                    "label": "knows",
                    "outV": "1:Alice",
                    "outVLabel": "person",
                    "inV": "1:Bob",
                    "inVLabel": "person",
                }
            ],
        }
    )

    assert result["ok"] is True


def test_ingest_graph_data_rejects_duplicate_vertex_identity(monkeypatch):
    _mock_schema(monkeypatch)

    result = ingest_graph_data_module.ingest_graph_data(
        {
            "vertices": [
                {"label": "person", "properties": {"name": "Alice"}},
                {"label": "person", "properties": {"name": "Alice"}},
            ],
            "edges": [],
        }
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"


def test_ingest_graph_data_rejects_edge_label_mismatch(monkeypatch):
    _mock_schema(monkeypatch)

    bad_data = {
        "vertices": [{"label": "person", "properties": {"name": "Alice"}}],
        "edges": [
            {
                "label": "likes",
                "source_label": "person",
                "target_label": "person",
                "source": {"name": "Alice"},
                "target": {"name": "Bob"},
            },
            {
                "label": "knows",
                "source_label": "person",
                "target_label": "ghost",
                "source": {"name": "Alice"},
                "target": {"name": "Bob"},
            },
        ],
    }

    result = ingest_graph_data_module.ingest_graph_data(bad_data)

    assert result["ok"] is False
    assert result["error"]["type"] == "SCHEMA_MISMATCH"
    errors = result["error"]["details"]["errors"]
    assert any("edge 0 label 'likes' does not exist in schema" in e for e in errors)
    assert any("edge 1 target_label 'ghost'" in e for e in errors)
    assert any(
        "does not match edge label 'knows' target_label 'person'" in e for e in errors
    )


def test_ingest_graph_data_warns_for_labels_without_schema_index(monkeypatch):
    schema = _live_schema()
    schema["schema"]["indexlabels"] = [
        {"name": "personByName", "base_type": "VERTEX", "base_label": "person"},
    ]
    monkeypatch.setattr(ingest_graph_data_module, "_fetch_live_schema", lambda: schema)

    result = ingest_graph_data_module.ingest_graph_data(_graph_data())

    assert result["ok"] is True
    assert (
        "no edge index found in schema for label: knows" in result["data"]["warnings"]
    )


def test_ingest_graph_data_missing_confirm(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")

    result = ingest_graph_data_module.ingest_graph_data(
        _graph_data(),
        dry_run=False,
        confirm=False,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "CONFIRM_REQUIRED"


def test_ingest_graph_data_plan_hash_mismatch(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    graph_data = _graph_data()
    dry_run = ingest_graph_data_module.ingest_graph_data(graph_data)
    plan_ctx = dry_run["data"]["plan_context"]

    result = ingest_graph_data_module.ingest_graph_data(
        graph_data,
        dry_run=False,
        confirm=True,
        plan_hash="0000000000000000",
        nonce=plan_ctx["nonce"],
        expires_at=plan_ctx["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PLAN_HASH_MISMATCH"


def test_ingest_graph_data_plan_hash_expired(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    graph_data = _graph_data()
    dry_run = ingest_graph_data_module.ingest_graph_data(graph_data)
    plan_ctx = dry_run["data"]["plan_context"]

    result = ingest_graph_data_module.ingest_graph_data(
        graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_ctx["nonce"],
        expires_at=0,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "PLAN_EXPIRED"


def test_ingest_graph_data_readonly(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    result = ingest_graph_data_module.ingest_graph_data(
        _graph_data(),
        dry_run=False,
        confirm=True,
        plan_hash="0000000000000000",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "READONLY_VIOLATION"


def test_ingest_graph_data_readonly_preview_does_not_issue_plan(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")
    issue = Mock()
    monkeypatch.setattr(ingest_graph_data_module, "issue_plan", issue)

    result = ingest_graph_data_module.ingest_graph_data(_graph_data())

    assert result["ok"] is True
    assert result["data"]["confirmable"] is False
    assert result["data"]["readonly_preview_only"] is True
    issue.assert_not_called()


def test_ingest_graph_data_success(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock(
        return_value=envelope_ok(
            {"ok": True, "data": {"written": {"vertices": 2, "edges": 1}}}
        )
    )
    monkeypatch.setattr(ingest_graph_data_module, "post", post)
    graph_data = _graph_data()
    dry_run = ingest_graph_data_module.ingest_graph_data(graph_data)

    # M5: pass nonce and expires_at from dry_run plan_context
    plan_ctx = dry_run["data"]["plan_context"]
    result = ingest_graph_data_module.ingest_graph_data(
        graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_ctx["nonce"],
        expires_at=plan_ctx["expires_at"],
    )

    assert result["ok"] is True
    assert result["data"]["batch_id"].startswith("batch-")
    assert result["data"]["status"] == "success"
    assert result["data"]["planned"] == {"vertices": 2, "edges": 1}
    assert result["data"]["written"] == {"vertices": 2, "edges": 1}
    post.assert_called_once()
    assert post.call_args.args == ("/graph-import",)
    assert post.call_args.kwargs["json"]["schema"] == "hugegraph"
    import_payload = json.loads(post.call_args.kwargs["json"]["data"])
    assert import_payload["vertices"][0]["id"] == "1:Alice"
    assert import_payload["vertices"][1]["id"] == "1:Bob"
    assert import_payload["edges"][0]["outV"] == "1:Alice"
    assert import_payload["edges"][0]["outVLabel"] == "person"
    assert import_payload["edges"][0]["inV"] == "1:Bob"
    assert import_payload["edges"][0]["inVLabel"] == "person"
    assert import_payload["edges"][0]["properties"] == {}


def test_ingest_graph_data_replayed_confirmation_does_not_post_twice(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock(
        return_value=envelope_ok(
            {"ok": True, "data": {"written": {"vertices": 2, "edges": 1}}}
        )
    )
    monkeypatch.setattr(ingest_graph_data_module, "post", post)
    graph_data = _graph_data()
    dry_run = ingest_graph_data_module.ingest_graph_data(
        graph_data, nonce="ingest-replay"
    )
    context = dry_run["data"]["plan_context"]
    arguments = {
        "graph_data": graph_data,
        "dry_run": False,
        "confirm": True,
        "plan_hash": dry_run["data"]["plan_hash"],
        "nonce": context["nonce"],
        "expires_at": context["expires_at"],
    }

    first = ingest_graph_data_module.ingest_graph_data(**arguments)
    second = ingest_graph_data_module.ingest_graph_data(**arguments)

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["error"]["type"] == "PLAN_ALREADY_USED"
    assert "already been used" in second["error"]["message"]
    assert "Inspect the current target state" in second["error"]["suggestion"]
    post.assert_called_once()


def test_ingest_partial_apply_consumes_confirmation(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock(return_value=envelope_ok({"inserted": 2}))
    monkeypatch.setattr(ingest_graph_data_module, "post", post)
    graph_data = _graph_data()
    dry_run = ingest_graph_data_module.ingest_graph_data(
        graph_data, nonce="ingest-partial"
    )
    context = dry_run["data"]["plan_context"]
    arguments = {
        "graph_data": graph_data,
        "dry_run": False,
        "confirm": True,
        "plan_hash": dry_run["data"]["plan_hash"],
        "nonce": context["nonce"],
        "expires_at": context["expires_at"],
    }

    partial = ingest_graph_data_module.ingest_graph_data(**arguments)
    replay = ingest_graph_data_module.ingest_graph_data(**arguments)

    assert partial["ok"] is False
    assert partial["error"]["details"]["status"] == "partial"
    assert partial["error"]["retryable"] is False
    assert replay["ok"] is False
    assert replay["error"]["type"] == "PLAN_ALREADY_USED"
    post.assert_called_once()


def test_ingest_graph_data_degrades_when_ai_omits_counts(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock(return_value=envelope_ok({"message": "import finished"}))
    monkeypatch.setattr(ingest_graph_data_module, "post", post)
    graph_data = _graph_data()
    dry_run = ingest_graph_data_module.ingest_graph_data(graph_data)
    plan_ctx = dry_run["data"]["plan_context"]

    result = ingest_graph_data_module.ingest_graph_data(
        graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_ctx["nonce"],
        expires_at=plan_ctx["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "FLOW_EXECUTION_FAILED"
    details = result["error"]["details"]
    assert details["status"] == "degraded"
    assert details["written"] == {"vertices": 0, "edges": 0}
    assert result["error"]["retryable"] is False
    assert any("write outcome is unknown" in w for w in result["warnings"])


def test_ingest_graph_data_splits_total_written_count(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock(return_value=envelope_ok({"inserted": 2}))
    monkeypatch.setattr(ingest_graph_data_module, "post", post)
    graph_data = _graph_data()
    dry_run = ingest_graph_data_module.ingest_graph_data(graph_data)
    plan_ctx = dry_run["data"]["plan_context"]

    result = ingest_graph_data_module.ingest_graph_data(
        graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_ctx["nonce"],
        expires_at=plan_ctx["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["details"]["status"] == "partial"
    assert result["error"]["details"]["written"] == {"vertices": 2, "edges": 0}
    assert any("total written count" in w for w in result["warnings"])


def test_ingest_graph_data_does_not_promote_ai_failure_without_counts(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock(return_value=envelope_ok({"success": False, "status": "partial"}))
    monkeypatch.setattr(ingest_graph_data_module, "post", post)
    graph_data = _graph_data()
    dry_run = ingest_graph_data_module.ingest_graph_data(graph_data)
    plan_ctx = dry_run["data"]["plan_context"]

    result = ingest_graph_data_module.ingest_graph_data(
        graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_ctx["nonce"],
        expires_at=plan_ctx["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["details"]["status"] == "error"
    assert result["error"]["details"]["written"] == {"vertices": 0, "edges": 0}


def test_ingest_graph_data_does_not_promote_failed_items_without_counts(monkeypatch):
    _mock_schema(monkeypatch)
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    post = Mock(return_value=envelope_ok({"failed_items": [{"index": 0}]}))
    monkeypatch.setattr(ingest_graph_data_module, "post", post)
    graph_data = _graph_data()
    dry_run = ingest_graph_data_module.ingest_graph_data(graph_data)
    plan_ctx = dry_run["data"]["plan_context"]

    result = ingest_graph_data_module.ingest_graph_data(
        graph_data,
        dry_run=False,
        confirm=True,
        plan_hash=dry_run["data"]["plan_hash"],
        nonce=plan_ctx["nonce"],
        expires_at=plan_ctx["expires_at"],
    )

    assert result["ok"] is False
    assert result["error"]["details"]["status"] == "degraded"
    assert result["error"]["details"]["failed_items"] == [{"index": 0}]
