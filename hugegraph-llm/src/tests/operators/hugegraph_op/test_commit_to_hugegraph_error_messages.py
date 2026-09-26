# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

from unittest.mock import MagicMock, patch

import pytest

from hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph import Commit2Graph

pytestmark = [pytest.mark.unit]


def _commit_operator():
    mock_client = MagicMock()
    mock_client.schema.return_value = MagicMock()
    with patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.PyHugeClient", return_value=mock_client):
        return Commit2Graph()


def _schema():
    return {
        "propertykeys": [
            {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
            {"name": "title", "data_type": "TEXT", "cardinality": "SINGLE"},
            {"name": "role", "data_type": "TEXT", "cardinality": "SINGLE"},
            {"name": "age", "data_type": "INT", "cardinality": "SINGLE"},
            {"name": "score", "data_type": "DOUBLE", "cardinality": "SINGLE"},
        ],
        "vertexlabels": [
            {
                "name": "person",
                "properties": ["name", "age", "score"],
                "primary_keys": ["name"],
                "nullable_keys": ["age", "score"],
                "id_strategy": "PRIMARY_KEY",
            },
            {
                "name": "movie",
                "properties": ["title"],
                "primary_keys": ["title"],
                "nullable_keys": [],
                "id_strategy": "PRIMARY_KEY",
            },
        ],
        "edgelabels": [{"name": "acted_in", "properties": ["role"], "source_label": "person", "target_label": "movie"}],
    }


def test_import_errors_do_not_include_raw_vertex_or_edge_payloads():
    commit2graph = _commit_operator()
    vertices = [{"label": "person", "properties": {"name": "Tom Hanks"}}]
    edges = [
        {
            "label": "acted_in",
            "properties": {"role": "Forrest Gump"},
            "outV": "person:Tom Hanks",
            "outVLabel": "person",
            "inV": "movie:Forrest Gump",
            "inVLabel": "movie",
        }
    ]

    with patch.object(commit2graph, "_handle_graph_creation", return_value=None):
        result = commit2graph.load_into_graph(vertices, edges, _schema())

    assert result["errors"] == [
        {"kind": "vertex", "index": 0, "reason": "create_failed", "label": "person"},
        {
            "kind": "edge",
            "index": 0,
            "reason": "endpoint_vertex_failed",
            "label": "acted_in",
            "key": "outV",
        },
    ]
    error_text = str(result["errors"])
    assert "Tom Hanks" not in error_text
    assert "Forrest Gump" not in error_text


def test_primary_key_import_error_identifies_key_label_and_index_only():
    commit2graph = _commit_operator()
    vertices = [{"label": "person", "properties": {"name": ""}}]

    result = commit2graph.load_into_graph(vertices, [], _schema())

    assert result["errors"] == [
        {"kind": "vertex", "index": 0, "reason": "missing_primary_key", "label": "person", "key": "name"}
    ]
    assert "{'label':" not in str(result["errors"])


def test_schema_free_import_errors_do_not_include_raw_triple_payloads():
    commit2graph = _commit_operator()
    triples = [["Alice Sensitive", "knows", "Bob Sensitive"]]

    with patch.object(commit2graph, "_handle_graph_creation", return_value=None):
        result = commit2graph.schema_free_mode(triples)

    assert result["errors"] == [{"kind": "triple", "index": 0, "reason": "create_vertices_failed"}]
    error_text = str(result["errors"])
    assert "Alice Sensitive" not in error_text
    assert "Bob Sensitive" not in error_text


def test_import_rejects_edge_endpoint_label_mismatch_before_writing():
    commit2graph = _commit_operator()
    edges = [
        {
            "label": "acted_in",
            "properties": {"role": "Forrest Gump"},
            "outV": "person:Tom Hanks",
            "outVLabel": "movie",
            "inV": "movie:Forrest Gump",
            "inVLabel": "movie",
        }
    ]

    with patch.object(commit2graph, "_handle_graph_creation") as mock_handle_graph_creation:
        result = commit2graph.load_into_graph([], edges, _schema())

    assert result["edges_created"] == 0
    assert result["edges_skipped"] == 1
    assert result["errors"] == [
        {
            "kind": "edge",
            "index": 0,
            "reason": "source_label_mismatch",
            "label": "acted_in",
            "key": "outVLabel",
        }
    ]
    mock_handle_graph_creation.assert_not_called()


def test_import_rejects_unknown_vertex_property_without_raw_payload():
    commit2graph = _commit_operator()
    vertices = [{"label": "person", "properties": {"name": "Tom Hanks", "secret": "raw user data"}}]

    with patch.object(commit2graph, "_handle_graph_creation") as mock_handle_graph_creation:
        result = commit2graph.load_into_graph(vertices, [], _schema())

    assert result["vertices_created"] == 0
    assert result["vertices_skipped"] == 1
    assert result["errors"] == [
        {"kind": "vertex", "index": 0, "reason": "unknown_property", "label": "person", "key": "secret"}
    ]
    assert "Tom Hanks" not in str(result["errors"])
    assert "raw user data" not in str(result["errors"])
    mock_handle_graph_creation.assert_not_called()


def test_import_rejects_unknown_edge_property_before_writing():
    commit2graph = _commit_operator()
    edges = [
        {
            "label": "acted_in",
            "properties": {"secret": "raw edge data"},
            "outV": "person:Tom Hanks",
            "outVLabel": "person",
            "inV": "movie:Forrest Gump",
            "inVLabel": "movie",
        }
    ]

    with patch.object(commit2graph, "_handle_graph_creation") as mock_handle_graph_creation:
        result = commit2graph.load_into_graph([], edges, _schema())

    assert result["edges_created"] == 0
    assert result["edges_skipped"] == 1
    assert result["errors"] == [
        {"kind": "edge", "index": 0, "reason": "unknown_property", "label": "acted_in", "key": "secret"}
    ]
    assert "raw edge data" not in str(result["errors"])
    mock_handle_graph_creation.assert_not_called()


def test_import_rejects_invalid_edge_property_type_before_writing():
    commit2graph = _commit_operator()
    edges = [
        {
            "label": "acted_in",
            "properties": {"role": 123},
            "outV": "person:Tom Hanks",
            "outVLabel": "person",
            "inV": "movie:Forrest Gump",
            "inVLabel": "movie",
        }
    ]

    with patch.object(commit2graph, "_handle_graph_creation") as mock_handle_graph_creation:
        result = commit2graph.load_into_graph([], edges, _schema())

    assert result["edges_created"] == 0
    assert result["edges_skipped"] == 1
    assert result["errors"] == [
        {"kind": "edge", "index": 0, "reason": "invalid_property_type", "label": "acted_in", "key": "role"}
    ]
    mock_handle_graph_creation.assert_not_called()


def test_import_skips_edge_when_batch_endpoint_vertex_failed():
    commit2graph = _commit_operator()
    vertices = [{"label": "person", "properties": {"name": "Tom Hanks", "secret": "raw user data"}}]
    edges = [
        {
            "label": "acted_in",
            "properties": {"role": "Forrest Gump"},
            "outV": "person:Tom Hanks",
            "outVLabel": "person",
            "inV": "movie:Forrest Gump",
            "inVLabel": "movie",
        }
    ]

    with patch.object(commit2graph, "_handle_graph_creation") as mock_handle_graph_creation:
        result = commit2graph.load_into_graph(vertices, edges, _schema())

    assert result["vertices_created"] == 0
    assert result["vertices_skipped"] == 1
    assert result["edges_created"] == 0
    assert result["edges_skipped"] == 1
    assert result["errors"] == [
        {"kind": "vertex", "index": 0, "reason": "unknown_property", "label": "person", "key": "secret"},
        {
            "kind": "edge",
            "index": 0,
            "reason": "endpoint_vertex_failed",
            "label": "acted_in",
            "key": "outV",
        },
    ]
    assert "Tom Hanks" not in str(result["errors"])
    assert "raw user data" not in str(result["errors"])
    mock_handle_graph_creation.assert_not_called()


def test_import_keeps_raw_endpoint_fallback_for_existing_vertices():
    commit2graph = _commit_operator()
    edges = [
        {
            "label": "acted_in",
            "properties": {"role": "Forrest Gump"},
            "outV": "person:Tom Hanks",
            "outVLabel": "person",
            "inV": "movie:Forrest Gump",
            "inVLabel": "movie",
        }
    ]

    with patch.object(commit2graph, "_handle_graph_creation", return_value=MagicMock(id="edge_id")) as mock_create:
        result = commit2graph.load_into_graph([], edges, _schema())

    assert result["edges_created"] == 1
    assert result["edges_skipped"] == 0
    assert result["errors"] == []
    mock_create.assert_called_once_with(
        commit2graph.client.graph().addEdge,
        "acted_in",
        "person:Tom Hanks",
        "movie:Forrest Gump",
        {"role": "Forrest Gump"},
    )


def test_import_rejects_bool_for_int_property_before_writing():
    commit2graph = _commit_operator()
    vertices = [{"label": "person", "properties": {"name": "Tom Hanks", "age": True}}]

    with patch.object(commit2graph, "_handle_graph_creation") as mock_handle_graph_creation:
        result = commit2graph.load_into_graph(vertices, [], _schema())

    assert result["vertices_created"] == 0
    assert result["vertices_skipped"] == 1
    assert result["errors"] == [
        {"kind": "vertex", "index": 0, "reason": "invalid_property_type", "label": "person", "key": "age"}
    ]
    mock_handle_graph_creation.assert_not_called()


def test_import_accepts_integer_for_double_property():
    commit2graph = _commit_operator()
    vertices = [{"label": "person", "properties": {"name": "Tom Hanks", "score": 1}}]

    with patch.object(commit2graph, "_handle_graph_creation", return_value=MagicMock(id="person:Tom Hanks")):
        result = commit2graph.load_into_graph(vertices, [], _schema())

    assert result["vertices_created"] == 1
    assert result["vertices_skipped"] == 0
    assert result["errors"] == []
