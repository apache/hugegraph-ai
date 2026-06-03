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

# pylint: disable=protected-access,no-member
import unittest
from unittest.mock import MagicMock, patch

import pytest

from hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph import Commit2Graph
from hugegraph_llm.operators.llm_op.property_graph_extract import PropertyGraphExtract

pytestmark = [pytest.mark.unit]


class TestCommit2GraphLoadIntoGraph(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_schema = MagicMock()
        self.mock_client.schema.return_value = self.mock_schema

        with patch(
            "hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.PyHugeClient", return_value=self.mock_client
        ):
            self.commit2graph = Commit2Graph()

        self.schema = {
            "propertykeys": [
                {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
                {"name": "age", "data_type": "INT", "cardinality": "SINGLE"},
                {"name": "title", "data_type": "TEXT", "cardinality": "SINGLE"},
                {"name": "year", "data_type": "INT", "cardinality": "SINGLE"},
                {"name": "role", "data_type": "TEXT", "cardinality": "SINGLE"},
            ],
            "vertexlabels": [
                {
                    "id": 1,
                    "name": "person",
                    "properties": ["name", "age"],
                    "primary_keys": ["name"],
                    "nullable_keys": ["age"],
                    "id_strategy": "PRIMARY_KEY",
                },
                {
                    "id": 2,
                    "name": "movie",
                    "properties": ["title", "year"],
                    "primary_keys": ["title"],
                    "nullable_keys": ["year"],
                    "id_strategy": "PRIMARY_KEY",
                },
            ],
            "edgelabels": [
                {"name": "acted_in", "properties": ["role"], "source_label": "person", "target_label": "movie"}
            ],
        }

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._check_property_data_type")
    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._handle_graph_creation")
    def test_load_into_graph(self, mock_handle_graph_creation, mock_check_property_data_type):
        """Test load_into_graph method."""
        mock_handle_graph_creation.return_value = MagicMock(id="vertex_id")
        mock_check_property_data_type.return_value = True

        vertices = [
            {"label": "person", "properties": {"name": "Tom Hanks", "age": 67}},
            {"label": "movie", "properties": {"title": "Forrest Gump", "year": 1994}},
        ]
        edges = [
            {
                "label": "acted_in",
                "properties": {"role": "Forrest Gump"},
                "outV": "person:Tom Hanks",
                "inV": "movie:Forrest Gump",
            }
        ]

        self.commit2graph.load_into_graph(vertices, edges, self.schema)

        self.assertEqual(mock_handle_graph_creation.call_count, 3)

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._handle_graph_creation")
    def test_load_into_graph_with_data_type_validation_success(self, mock_handle_graph_creation):
        """Test load_into_graph method with successful data type validation."""
        mock_handle_graph_creation.return_value = MagicMock(id="vertex_id")

        vertices = [
            {"label": "person", "properties": {"name": "Tom Hanks", "age": 67}},
            {"label": "movie", "properties": {"title": "Forrest Gump", "year": 1994}},
        ]
        edges = [
            {
                "label": "acted_in",
                "properties": {"role": "Forrest Gump"},
                "outV": "person:Tom Hanks",
                "inV": "movie:Forrest Gump",
            }
        ]

        self.commit2graph.load_into_graph(vertices, edges, self.schema)

        self.assertEqual(mock_handle_graph_creation.call_count, 3)

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._handle_graph_creation")
    def test_load_into_graph_maps_llm_vertex_ids_to_created_vertex_ids(self, mock_handle_graph_creation):
        """Test edges use server-created vertex ids when LLM ids differ."""
        mock_handle_graph_creation.side_effect = [
            MagicMock(id="1:Tom Hanks"),
            MagicMock(id="2:Forrest Gump"),
            MagicMock(id="edge_id"),
        ]

        vertices = [
            {"id": "person:Tom Hanks", "label": "person", "properties": {"name": "Tom Hanks", "age": 67}},
            {"id": "movie:Forrest Gump", "label": "movie", "properties": {"title": "Forrest Gump", "year": 1994}},
        ]
        edges = [
            {
                "label": "acted_in",
                "properties": {"role": "Forrest Gump"},
                "outV": "person:Tom Hanks",
                "inV": "movie:Forrest Gump",
            }
        ]

        self.commit2graph.load_into_graph(vertices, edges, self.schema)

        self.assertEqual(vertices[0]["id"], "1:Tom Hanks")
        self.assertEqual(vertices[1]["id"], "2:Forrest Gump")
        mock_handle_graph_creation.assert_any_call(
            self.commit2graph.client.graph().addEdge,
            "acted_in",
            "1:Tom Hanks",
            "2:Forrest Gump",
            {"role": "Forrest Gump"},
        )

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._handle_graph_creation")
    def test_load_into_graph_maps_multiple_primary_keys_to_created_vertex_ids(self, mock_handle_graph_creation):
        mock_handle_graph_creation.side_effect = [
            MagicMock(id="1:Tom!Hanks"),
            MagicMock(id="2:Forrest Gump"),
            MagicMock(id="edge_id"),
        ]
        schema = {
            "propertykeys": [
                {"name": "first", "data_type": "TEXT", "cardinality": "SINGLE"},
                {"name": "last", "data_type": "TEXT", "cardinality": "SINGLE"},
                {"name": "title", "data_type": "TEXT", "cardinality": "SINGLE"},
            ],
            "vertexlabels": [
                {
                    "id": 1,
                    "name": "person",
                    "properties": ["first", "last"],
                    "primary_keys": ["first", "last"],
                    "nullable_keys": [],
                    "id_strategy": "PRIMARY_KEY",
                },
                {
                    "id": 2,
                    "name": "movie",
                    "properties": ["title"],
                    "primary_keys": ["title"],
                    "nullable_keys": [],
                    "id_strategy": "PRIMARY_KEY",
                },
            ],
            "edgelabels": [{"name": "acted_in", "properties": [], "source_label": "person", "target_label": "movie"}],
        }
        vertices = [
            {"label": "person", "properties": {"first": "Tom", "last": "Hanks"}},
            {"label": "movie", "properties": {"title": "Forrest Gump"}},
        ]
        edges = [
            {
                "label": "acted_in",
                "properties": {},
                "outV": "person:Tom!Hanks",
                "inV": "movie:Forrest Gump",
            }
        ]

        self.commit2graph.load_into_graph(vertices, edges, schema)

        mock_handle_graph_creation.assert_any_call(
            self.commit2graph.client.graph().addEdge,
            "acted_in",
            "1:Tom!Hanks",
            "2:Forrest Gump",
            {},
        )

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._handle_graph_creation")
    def test_load_into_graph_uses_explicit_customize_string_ids(self, mock_handle_graph_creation):
        """Test custom string ids are passed to HugeGraph when schema requires them."""
        mock_handle_graph_creation.side_effect = [
            MagicMock(id="Tom Hanks"),
            MagicMock(id="Forrest Gump"),
            MagicMock(id="edge_id"),
        ]
        schema = {
            "propertykeys": [
                {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
                {"name": "title", "data_type": "TEXT", "cardinality": "SINGLE"},
            ],
            "vertexlabels": [
                {
                    "id": 7,
                    "name": "person",
                    "id_strategy": "CUSTOMIZE_STRING",
                    "primary_keys": ["name"],
                    "properties": ["name"],
                    "nullable_keys": [],
                },
                {
                    "id": 8,
                    "name": "movie",
                    "id_strategy": "CUSTOMIZE_STRING",
                    "primary_keys": ["title"],
                    "properties": ["title"],
                    "nullable_keys": [],
                },
            ],
            "edgelabels": [{"name": "acted_in", "properties": [], "source_label": "person", "target_label": "movie"}],
        }
        vertices = [
            {"id": "Tom Hanks", "label": "person", "properties": {"name": "Tom Hanks"}},
            {"id": "Forrest Gump", "label": "movie", "properties": {"title": "Forrest Gump"}},
        ]
        edges = [{"label": "acted_in", "properties": {}, "outV": "Tom Hanks", "inV": "Forrest Gump"}]

        self.commit2graph.load_into_graph(vertices, edges, schema)

        mock_handle_graph_creation.assert_any_call(
            self.commit2graph.client.graph().addVertex,
            "person",
            {"name": "Tom Hanks"},
            id="Tom Hanks",
        )
        mock_handle_graph_creation.assert_any_call(
            self.commit2graph.client.graph().addVertex,
            "movie",
            {"title": "Forrest Gump"},
            id="Forrest Gump",
        )
        mock_handle_graph_creation.assert_any_call(
            self.commit2graph.client.graph().addEdge,
            "acted_in",
            "Tom Hanks",
            "Forrest Gump",
            {},
        )

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._handle_graph_creation")
    def test_load_into_graph_accepts_normalized_extraction_without_item_type(self, mock_handle_graph_creation):
        """Test normalized LLM output without type fields can be committed."""
        mock_handle_graph_creation.side_effect = [
            MagicMock(id="1:Tom Hanks"),
            MagicMock(id="2:Forrest Gump"),
            MagicMock(id="edge_id"),
        ]
        llm_output = """{
            "vertices": [
            {
                "id": "person:Tom Hanks",
                "label": "person",
                "properties": {
                    "name": "Tom Hanks",
                    "age": 67
                }
            },
            {
                "id": "movie:Forrest Gump",
                "label": "movie",
                "properties": {
                    "title": "Forrest Gump",
                    "year": 1994
                }
            }
            ],
            "edges": [
            {
                "label": "acted_in",
                "outV": "person:Tom Hanks",
                "outVLabel": "person",
                "inV": "movie:Forrest Gump",
                "inVLabel": "movie",
                "properties": {
                    "role": "Forrest Gump"
                }
            }
            ]
        }"""

        items = PropertyGraphExtract(llm=MagicMock())._extract_and_filter_label(self.schema, llm_output)
        vertices = [item for item in items if item["type"] == "vertex"]
        edges = [item for item in items if item["type"] == "edge"]
        self.assertEqual(edges[0]["outV"], "1:Tom Hanks")
        self.assertEqual(edges[0]["inV"], "2:Forrest Gump")

        self.commit2graph.load_into_graph(vertices, edges, self.schema)

        mock_handle_graph_creation.assert_any_call(
            self.commit2graph.client.graph().addEdge,
            "acted_in",
            "1:Tom Hanks",
            "2:Forrest Gump",
            {"role": "Forrest Gump"},
        )

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._handle_graph_creation")
    def test_load_into_graph_raises_explicit_error_when_vertex_creation_fails(self, mock_handle_graph_creation):
        """Test failed vertex creation is reported before edge creation."""
        mock_handle_graph_creation.return_value = None

        vertices = [{"label": "person", "properties": {"name": "Tom Hanks", "age": 67}}]
        edges = [
            {
                "label": "acted_in",
                "properties": {"role": "Forrest Gump"},
                "outV": "person:Tom Hanks",
                "inV": "movie:Forrest Gump",
            }
        ]

        with self.assertRaisesRegex(ValueError, "Failed to create vertex"):
            self.commit2graph.load_into_graph(vertices, edges, self.schema)

        mock_handle_graph_creation.assert_called_once()

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._handle_graph_creation")
    def test_load_into_graph_with_data_type_validation_failure(self, mock_handle_graph_creation):
        """Test load_into_graph method with data type validation failure."""
        mock_handle_graph_creation.return_value = MagicMock(id="vertex_id")

        vertices = [
            {"label": "person", "properties": {"name": "Tom Hanks", "age": "67"}},
            {"label": "movie", "properties": {"title": "Forrest Gump", "year": "1994"}},
        ]
        edges = [
            {
                "label": "acted_in",
                "properties": {"role": "Forrest Gump"},
                "outV": "person:Tom Hanks",
                "inV": "movie:Forrest Gump",
            }
        ]

        self.commit2graph.load_into_graph(vertices, edges, self.schema)

        self.assertEqual(mock_handle_graph_creation.call_count, 1)
