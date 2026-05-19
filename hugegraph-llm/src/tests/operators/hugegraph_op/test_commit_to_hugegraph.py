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

from pyhugegraph.utils.exceptions import CreateError, NotFoundError

from hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph import Commit2Graph
from hugegraph_llm.operators.llm_op.property_graph_extract import PropertyGraphExtract


class TestCommit2Graph(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        # Mock the PyHugeClient
        self.mock_client = MagicMock()
        self.mock_schema = MagicMock()
        self.mock_client.schema.return_value = self.mock_schema

        # Create a Commit2Graph instance with the mock client
        with patch(
            "hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.PyHugeClient", return_value=self.mock_client
        ):
            self.commit2graph = Commit2Graph()

        # Sample schema
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

        # Sample vertices and edges
        self.vertices = [
            {"type": "vertex", "label": "person", "properties": {"name": "Tom Hanks", "age": "67"}},
            {"type": "vertex", "label": "movie", "properties": {"title": "Forrest Gump", "year": "1994"}},
        ]

        self.edges = [
            {
                "type": "edge",
                "label": "acted_in",
                "properties": {"role": "Forrest Gump"},
                "source": {"label": "person", "properties": {"name": "Tom Hanks"}},
                "target": {"label": "movie", "properties": {"title": "Forrest Gump"}},
            }
        ]

        # Convert edges to the format expected by the implementation
        self.formatted_edges = [
            {
                "label": "acted_in",
                "properties": {"role": "Forrest Gump"},
                "outV": "person:Tom Hanks",  # This is a simplified ID format
                "inV": "movie:Forrest Gump",  # This is a simplified ID format
            }
        ]

    def test_init(self):
        """Test initialization of Commit2Graph."""
        self.assertEqual(self.commit2graph.client, self.mock_client)
        self.assertEqual(self.commit2graph.schema, self.mock_schema)

    def test_run_with_empty_data(self):
        """Test run method with empty data."""
        # Test with empty vertices and edges
        with self.assertRaises(ValueError):
            self.commit2graph.run({})

        # Test with empty vertices
        with self.assertRaises(ValueError):
            self.commit2graph.run({"vertices": [], "edges": []})

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph.load_into_graph")
    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph.init_schema_if_need")
    def test_run_with_schema(self, mock_init_schema, mock_load_into_graph):
        """Test run method with schema."""
        # Setup mocks
        mock_init_schema.return_value = None
        mock_load_into_graph.return_value = None

        # Create input data
        data = {"schema": self.schema, "vertices": self.vertices, "edges": self.edges}

        # Run the method
        result = self.commit2graph.run(data)

        # Verify that init_schema_if_need was called
        mock_init_schema.assert_called_once_with(self.schema)

        # Verify that load_into_graph was called
        mock_load_into_graph.assert_called_once_with(self.vertices, self.edges, self.schema)

        # Verify the results
        self.assertEqual(result, data)

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph.schema_free_mode")
    def test_run_without_schema(self, mock_schema_free_mode):
        """Test run method without schema."""
        # Setup mocks
        mock_schema_free_mode.return_value = None

        # Create input data
        data = {"vertices": self.vertices, "edges": self.edges, "triples": []}

        # Run the method
        result = self.commit2graph.run(data)

        # Verify that schema_free_mode was called
        mock_schema_free_mode.assert_called_once_with([])

        # Verify the results
        self.assertEqual(result, data)

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._check_property_data_type")
    def test_set_default_property(self, mock_check_property_data_type):
        """Test _set_default_property method."""
        # Mock _check_property_data_type to return True
        mock_check_property_data_type.return_value = True

        # Create property label map
        property_label_map = {
            "name": {"data_type": "TEXT", "cardinality": "SINGLE"},
            "age": {"data_type": "INT", "cardinality": "SINGLE"},
            "hobbies": {"data_type": "TEXT", "cardinality": "LIST"},
        }

        # Test with missing property (SINGLE cardinality)
        input_properties = {"name": "Tom Hanks"}
        self.commit2graph._set_default_property("age", input_properties, property_label_map)
        self.assertEqual(input_properties["age"], 0)

        # Test with missing property (LIST cardinality)
        input_properties_2 = {"name": "Tom Hanks"}
        self.commit2graph._set_default_property("hobbies", input_properties_2, property_label_map)
        self.assertEqual(input_properties_2["hobbies"], [])

    def test_handle_graph_creation_success(self):
        """Test _handle_graph_creation method with successful creation."""
        # Setup mocks
        mock_func = MagicMock()
        mock_func.return_value = "success"

        # Call the method
        result = self.commit2graph._handle_graph_creation(mock_func, "arg1", "arg2", kwarg1="value1")

        # Verify that the function was called with the correct arguments
        mock_func.assert_called_once_with("arg1", "arg2", kwarg1="value1")

        # Verify the result
        self.assertEqual(result, "success")

    def test_handle_graph_creation_not_found(self):
        """Test _handle_graph_creation method with NotFoundError."""
        # Setup mock function that raises NotFoundError
        mock_func = MagicMock(side_effect=NotFoundError("Not found"))

        # Call the method and verify it handles the exception
        result = self.commit2graph._handle_graph_creation(mock_func, "arg1", "arg2")

        # Verify behavior
        mock_func.assert_called_once_with("arg1", "arg2")
        self.assertIsNone(result)

    def test_handle_graph_creation_create_error(self):
        """Test _handle_graph_creation method with CreateError."""
        # Setup mock function that raises CreateError
        mock_func = MagicMock(side_effect=CreateError("Create error"))

        # Call the method and verify it handles the exception
        result = self.commit2graph._handle_graph_creation(mock_func, "arg1", "arg2")

        # Verify behavior
        mock_func.assert_called_once_with("arg1", "arg2")
        self.assertIsNone(result)

    def _setup_schema_mocks(self):
        """Helper method to set up common schema mocks."""
        # Create mock schema methods
        mock_property_key = MagicMock()
        mock_vertex_label = MagicMock()
        mock_edge_label = MagicMock()
        mock_index_label = MagicMock()

        self.commit2graph.schema.propertyKey = mock_property_key
        self.commit2graph.schema.vertexLabel = mock_vertex_label
        self.commit2graph.schema.edgeLabel = mock_edge_label
        self.commit2graph.schema.indexLabel = mock_index_label

        # Create mock builders
        mock_property_builder = MagicMock()
        mock_vertex_builder = MagicMock()
        mock_edge_builder = MagicMock()
        mock_index_builder = MagicMock()

        # Setup method chaining for property
        mock_property_key.return_value = mock_property_builder
        mock_property_builder.asText.return_value = mock_property_builder
        mock_property_builder.ifNotExist.return_value = mock_property_builder
        mock_property_builder.create.return_value = None

        # Setup method chaining for vertex
        mock_vertex_label.return_value = mock_vertex_builder
        mock_vertex_builder.properties.return_value = mock_vertex_builder
        mock_vertex_builder.nullableKeys.return_value = mock_vertex_builder
        mock_vertex_builder.usePrimaryKeyId.return_value = mock_vertex_builder
        mock_vertex_builder.useCustomizeStringId.return_value = mock_vertex_builder
        mock_vertex_builder.primaryKeys.return_value = mock_vertex_builder
        mock_vertex_builder.ifNotExist.return_value = mock_vertex_builder
        mock_vertex_builder.create.return_value = None

        # Setup method chaining for edge
        mock_edge_label.return_value = mock_edge_builder
        mock_edge_builder.sourceLabel.return_value = mock_edge_builder
        mock_edge_builder.targetLabel.return_value = mock_edge_builder
        mock_edge_builder.properties.return_value = mock_edge_builder
        mock_edge_builder.nullableKeys.return_value = mock_edge_builder
        mock_edge_builder.ifNotExist.return_value = mock_edge_builder
        mock_edge_builder.create.return_value = None

        # Setup method chaining for index
        mock_index_label.return_value = mock_index_builder
        mock_index_builder.onV.return_value = mock_index_builder
        mock_index_builder.onE.return_value = mock_index_builder
        mock_index_builder.by.return_value = mock_index_builder
        mock_index_builder.secondary.return_value = mock_index_builder
        mock_index_builder.ifNotExist.return_value = mock_index_builder
        mock_index_builder.create.return_value = None

        return {
            "property_key": mock_property_key,
            "vertex_label": mock_vertex_label,
            "edge_label": mock_edge_label,
            "index_label": mock_index_label,
        }

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._create_property")
    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._handle_graph_creation")
    def test_init_schema_if_need(self, mock_handle_graph_creation, mock_create_property):
        """Test init_schema_if_need method."""
        # Setup mocks
        mock_handle_graph_creation.return_value = None
        mock_create_property.return_value = None

        # Use helper method to set up schema mocks
        schema_mocks = self._setup_schema_mocks()

        # Call the method
        self.commit2graph.init_schema_if_need(self.schema)

        # Verify that _create_property was called for each property key
        self.assertEqual(mock_create_property.call_count, 5)  # 5 property keys

        # Verify that vertexLabel was called for each vertex label
        self.assertEqual(schema_mocks["vertex_label"].call_count, 2)  # 2 vertex labels

        # Verify that edgeLabel was called for each edge label
        self.assertEqual(schema_mocks["edge_label"].call_count, 1)  # 1 edge label

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._check_property_data_type")
    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._handle_graph_creation")
    def test_load_into_graph(self, mock_handle_graph_creation, mock_check_property_data_type):
        """Test load_into_graph method."""
        # Setup mocks
        mock_handle_graph_creation.return_value = MagicMock(id="vertex_id")
        mock_check_property_data_type.return_value = True

        # Create vertices with proper data types according to schema
        vertices = [
            {"label": "person", "properties": {"name": "Tom Hanks", "age": 67}},
            {"label": "movie", "properties": {"title": "Forrest Gump", "year": 1994}},
        ]

        edges = [
            {
                "label": "acted_in",
                "properties": {"role": "Forrest Gump"},
                "outV": "person:Tom Hanks",  # Use the format expected by the implementation
                "inV": "movie:Forrest Gump",  # Use the format expected by the implementation
            }
        ]

        # Call the method
        self.commit2graph.load_into_graph(vertices, edges, self.schema)

        # Verify that _handle_graph_creation was called for each vertex and edge
        self.assertEqual(mock_handle_graph_creation.call_count, 3)  # 2 vertices + 1 edge

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._handle_graph_creation")
    def test_load_into_graph_with_data_type_validation_success(self, mock_handle_graph_creation):
        """Test load_into_graph method with successful data type validation."""
        # Setup mocks
        mock_handle_graph_creation.return_value = MagicMock(id="vertex_id")

        # Create vertices with correct data types matching schema expectations
        vertices = [
            {"label": "person", "properties": {"name": "Tom Hanks", "age": 67}},  # age: INT -> int
            {"label": "movie", "properties": {"title": "Forrest Gump", "year": 1994}},  # year: INT -> int
        ]

        edges = [
            {
                "label": "acted_in",
                "properties": {"role": "Forrest Gump"},  # role: TEXT -> str
                "outV": "person:Tom Hanks",
                "inV": "movie:Forrest Gump",
            }
        ]

        # Call the method - should succeed with correct data types
        self.commit2graph.load_into_graph(vertices, edges, self.schema)

        # Verify that _handle_graph_creation was called for each vertex and edge
        self.assertEqual(mock_handle_graph_creation.call_count, 3)  # 2 vertices + 1 edge

    @patch("hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph.Commit2Graph._handle_graph_creation")
    def test_load_into_graph_maps_llm_vertex_ids_to_created_vertex_ids(self, mock_handle_graph_creation):
        """Test edges use server-created vertex ids when LLM ids differ."""
        mock_handle_graph_creation.side_effect = [
            MagicMock(id="1:Tom Hanks"),
            MagicMock(id="2:Forrest Gump"),
            MagicMock(id="edge_id"),
        ]

        vertices = [
            {
                "id": "person:Tom Hanks",
                "label": "person",
                "properties": {"name": "Tom Hanks", "age": 67},
            },
            {
                "id": "movie:Forrest Gump",
                "label": "movie",
                "properties": {"title": "Forrest Gump", "year": 1994},
            },
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
        edges = [
            {
                "label": "acted_in",
                "properties": {},
                "outV": "Tom Hanks",
                "inV": "Forrest Gump",
            }
        ]

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
    def test_load_into_graph_with_data_type_validation_failure(self, mock_handle_graph_creation):
        """Test load_into_graph method with data type validation failure."""
        # Setup mocks
        mock_handle_graph_creation.return_value = MagicMock(id="vertex_id")

        # Create vertices with incorrect data types (strings for INT fields)
        vertices = [
            {"label": "person", "properties": {"name": "Tom Hanks", "age": "67"}},  # age should be int, not str
            {"label": "movie", "properties": {"title": "Forrest Gump", "year": "1994"}},  # year should be int, not str
        ]

        edges = [
            {
                "label": "acted_in",
                "properties": {"role": "Forrest Gump"},
                "outV": "person:Tom Hanks",
                "inV": "movie:Forrest Gump",
            }
        ]

        # Call the method - should skip vertices due to data type validation failure
        self.commit2graph.load_into_graph(vertices, edges, self.schema)

        # Verify that _handle_graph_creation was called only for the edge (vertices were skipped)
        self.assertEqual(mock_handle_graph_creation.call_count, 1)  # Only 1 edge, vertices skipped

    def test_check_property_data_type_success(self):
        """Test _check_property_data_type method with valid data types."""
        # Test TEXT type
        self.assertTrue(self.commit2graph._check_property_data_type("TEXT", "SINGLE", "Tom Hanks"))

        # Test INT type
        self.assertTrue(self.commit2graph._check_property_data_type("INT", "SINGLE", 67))

        # Test LIST type with valid items
        self.assertTrue(self.commit2graph._check_property_data_type("TEXT", "LIST", ["hobby1", "hobby2"]))

    def test_check_property_data_type_failure(self):
        """Test _check_property_data_type method with invalid data types."""
        # Test INT type with string value (should fail)
        self.assertFalse(self.commit2graph._check_property_data_type("INT", "SINGLE", "67"))

        # Test TEXT type with int value (should fail)
        self.assertFalse(self.commit2graph._check_property_data_type("TEXT", "SINGLE", 67))

        # Test LIST type with non-list value (should fail)
        self.assertFalse(self.commit2graph._check_property_data_type("TEXT", "LIST", "not_a_list"))

        # Test LIST type with invalid item types (should fail)
        self.assertFalse(self.commit2graph._check_property_data_type("INT", "LIST", [1, "2", 3]))

    def test_check_property_data_type_edge_cases(self):
        """Test _check_property_data_type method with edge cases."""
        # Test BOOLEAN type
        self.assertTrue(self.commit2graph._check_property_data_type("BOOLEAN", "SINGLE", True))
        self.assertFalse(self.commit2graph._check_property_data_type("BOOLEAN", "SINGLE", "true"))

        # Test FLOAT/DOUBLE type
        self.assertTrue(self.commit2graph._check_property_data_type("FLOAT", "SINGLE", 3.14))
        self.assertTrue(self.commit2graph._check_property_data_type("DOUBLE", "SINGLE", 3.14))
        self.assertFalse(self.commit2graph._check_property_data_type("FLOAT", "SINGLE", "3.14"))

        # Test DATE type (format: yyyy-MM-dd)
        self.assertTrue(self.commit2graph._check_property_data_type("DATE", "SINGLE", "2024-01-01"))
        self.assertFalse(self.commit2graph._check_property_data_type("DATE", "SINGLE", "2024/01/01"))
        self.assertFalse(self.commit2graph._check_property_data_type("DATE", "SINGLE", "01-01-2024"))

        # Test empty LIST
        self.assertTrue(self.commit2graph._check_property_data_type("TEXT", "LIST", []))

        # Test unsupported data type
        with self.assertRaises(ValueError):
            self.commit2graph._check_property_data_type("UNSUPPORTED", "SINGLE", "value")

    def test_schema_free_mode(self):
        """Test schema_free_mode method."""
        # Use helper method to set up schema mocks
        schema_mocks = self._setup_schema_mocks()

        # Mock the client.graph() methods
        mock_graph = MagicMock()
        self.mock_client.graph.return_value = mock_graph
        mock_graph.addVertex.return_value = MagicMock(id="vertex_id")
        mock_graph.addEdge.return_value = MagicMock()

        # Create sample triples data in the correct format
        triples = [["Tom Hanks", "acted_in", "Forrest Gump"], ["Forrest Gump", "released_in", "1994"]]

        # Call the method
        self.commit2graph.schema_free_mode(triples)

        # Verify that schema methods were called
        schema_mocks["property_key"].assert_called_once_with("name")
        schema_mocks["vertex_label"].assert_called_once_with("vertex")
        schema_mocks["edge_label"].assert_called_once_with("edge")
        self.assertEqual(schema_mocks["index_label"].call_count, 2)

        # Verify that addVertex and addEdge were called for each triple
        self.assertEqual(mock_graph.addVertex.call_count, 4)  # 2 subjects + 2 objects
        self.assertEqual(mock_graph.addEdge.call_count, 2)  # 2 predicates

    def test_schema_free_mode_empty_triples(self):
        """Test schema_free_mode method with empty triples."""
        # Use helper method to set up schema mocks
        schema_mocks = self._setup_schema_mocks()

        # Mock the client.graph() methods
        mock_graph = MagicMock()
        self.mock_client.graph.return_value = mock_graph

        # Call the method with empty triples
        self.commit2graph.schema_free_mode([])

        # Verify that schema methods were still called (schema creation happens regardless)
        schema_mocks["property_key"].assert_called_once_with("name")
        schema_mocks["vertex_label"].assert_called_once_with("vertex")
        schema_mocks["edge_label"].assert_called_once_with("edge")
        self.assertEqual(schema_mocks["index_label"].call_count, 2)

        # Verify that graph operations were not called
        mock_graph.addVertex.assert_not_called()
        mock_graph.addEdge.assert_not_called()

    def test_schema_free_mode_single_triple(self):
        """Test schema_free_mode method with single triple."""
        # Use helper method to set up schema mocks
        schema_mocks = self._setup_schema_mocks()

        # Mock the client.graph() methods
        mock_graph = MagicMock()
        self.mock_client.graph.return_value = mock_graph
        mock_graph.addVertex.return_value = MagicMock(id="vertex_id")
        mock_graph.addEdge.return_value = MagicMock()

        # Create single triple
        triples = [["Alice", "knows", "Bob"]]

        # Call the method
        self.commit2graph.schema_free_mode(triples)

        # Verify that schema methods were called
        schema_mocks["property_key"].assert_called_once_with("name")
        schema_mocks["vertex_label"].assert_called_once_with("vertex")
        schema_mocks["edge_label"].assert_called_once_with("edge")
        self.assertEqual(schema_mocks["index_label"].call_count, 2)

        # Verify that addVertex and addEdge were called for single triple
        self.assertEqual(mock_graph.addVertex.call_count, 2)  # 1 subject + 1 object
        self.assertEqual(mock_graph.addEdge.call_count, 1)  # 1 predicate

    def test_schema_free_mode_with_whitespace(self):
        """Test schema_free_mode method with triples containing whitespace."""
        # Use helper method to set up schema mocks
        schema_mocks = self._setup_schema_mocks()

        # Mock the client.graph() methods
        mock_graph = MagicMock()
        self.mock_client.graph.return_value = mock_graph
        mock_graph.addVertex.return_value = MagicMock(id="vertex_id")
        mock_graph.addEdge.return_value = MagicMock()

        # Create triples with whitespace (should be stripped)
        triples = [["  Tom Hanks  ", "  acted_in  ", "  Forrest Gump  "]]

        # Call the method
        self.commit2graph.schema_free_mode(triples)

        # Verify that schema methods were called
        schema_mocks["property_key"].assert_called_once_with("name")
        schema_mocks["vertex_label"].assert_called_once_with("vertex")
        schema_mocks["edge_label"].assert_called_once_with("edge")
        self.assertEqual(schema_mocks["index_label"].call_count, 2)

        # Verify that addVertex was called with stripped strings
        mock_graph.addVertex.assert_any_call("vertex", {"name": "Tom Hanks"}, id="Tom Hanks")
        mock_graph.addVertex.assert_any_call("vertex", {"name": "Forrest Gump"}, id="Forrest Gump")

        # Verify that addEdge was called with stripped predicate
        mock_graph.addEdge.assert_called_once_with("edge", "vertex_id", "vertex_id", {"name": "acted_in"})

    def test_schema_free_mode_invalid_triple_format(self):
        """Test schema_free_mode method with invalid triple format."""
        # Use helper method to set up schema mocks
        schema_mocks = self._setup_schema_mocks()

        # Mock the client.graph() methods
        mock_graph = MagicMock()
        self.mock_client.graph.return_value = mock_graph
        mock_graph.addVertex.return_value = MagicMock(id="vertex_id")
        mock_graph.addEdge.return_value = MagicMock()

        # Create invalid triples (wrong length)
        invalid_triples = [["Alice", "knows"], ["Bob", "works_at", "Company", "extra"]]

        # Call the method - should raise ValueError due to unpacking
        with self.assertRaises(ValueError):
            self.commit2graph.schema_free_mode(invalid_triples)

        # Verify that schema methods were still called (schema creation happens first)
        schema_mocks["property_key"].assert_called_once_with("name")
        schema_mocks["vertex_label"].assert_called_once_with("vertex")
        schema_mocks["edge_label"].assert_called_once_with("edge")
        self.assertEqual(schema_mocks["index_label"].call_count, 2)


if __name__ == "__main__":
    unittest.main()
