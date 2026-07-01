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

import unittest
from unittest.mock import MagicMock, patch

import pytest

from hugegraph_llm.operators.hugegraph_op.schema_manager import SchemaManager

pytestmark = [pytest.mark.unit]


class TestSchemaManager(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        # Setup mock client
        self.mock_client = MagicMock()
        self.mock_schema = MagicMock()
        self.mock_client.schema.return_value = self.mock_schema

        # Create SchemaManager instance
        self.graph_name = "test_graph"
        with patch("hugegraph_llm.operators.hugegraph_op.schema_manager.PyHugeClient") as mock_client_class:
            mock_client_class.return_value = self.mock_client
            self.schema_manager = SchemaManager(self.graph_name)

        # Sample schema data for testing
        self.sample_schema = {
            "vertexlabels": [
                {
                    "id": 1,
                    "name": "person",
                    "properties": ["name", "age"],
                    "primary_keys": ["name"],
                    "nullable_keys": [],
                    "index_labels": [],
                },
                {
                    "id": 2,
                    "name": "software",
                    "properties": ["name", "lang"],
                    "primary_keys": ["name"],
                    "nullable_keys": [],
                    "index_labels": [],
                },
            ],
            "edgelabels": [
                {
                    "id": 3,
                    "name": "created",
                    "source_label": "person",
                    "target_label": "software",
                    "frequency": "SINGLE",
                    "properties": ["weight"],
                    "sort_keys": [],
                    "nullable_keys": [],
                    "index_labels": [],
                },
                {
                    "id": 4,
                    "name": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "frequency": "SINGLE",
                    "properties": ["weight"],
                    "sort_keys": [],
                    "nullable_keys": [],
                    "index_labels": [],
                },
            ],
        }

    def test_init(self):
        """Test initialization of SchemaManager class."""
        self.assertEqual(self.schema_manager.graph_name, self.graph_name)
        self.assertEqual(self.schema_manager.client, self.mock_client)
        self.assertEqual(self.schema_manager.schema, self.mock_schema)

    @patch("hugegraph_llm.operators.hugegraph_op.schema_manager.PyHugeClient")
    @patch("hugegraph_llm.operators.hugegraph_op.schema_manager.huge_settings")
    def test_init_uses_request_local_connection_settings(self, mock_settings, mock_client_class):
        mock_settings.graph_url = "default:8080"
        mock_settings.graph_user = "default_user"
        mock_settings.graph_pwd = "default_pwd"
        mock_settings.graph_space = "default_space"

        SchemaManager(
            "custom_graph",
            connection={
                "url": "10.0.0.1:8080",
                "user": "admin",
                "pwd": "secret",
                "graphspace": "space_a",
            },
        )

        mock_client_class.assert_called_once_with(
            url="10.0.0.1:8080",
            graph="custom_graph",
            user="admin",
            pwd="secret",
            graphspace="space_a",
        )

    @patch("hugegraph_llm.operators.hugegraph_op.schema_manager.PyHugeClient")
    @patch("hugegraph_llm.operators.hugegraph_op.schema_manager.huge_settings")
    def test_init_request_config_falls_back_for_none_graphspace(self, mock_settings, mock_client_class):
        mock_settings.graph_url = "default:8080"
        mock_settings.graph_user = "default_user"
        mock_settings.graph_pwd = "default_pwd"
        mock_settings.graph_space = "global_space"

        SchemaManager(
            "custom_graph",
            connection={
                "url": "10.0.0.1:8080",
                "user": "admin",
                "pwd": "secret",
                "graphspace": None,
            },
        )

        _, kwargs = mock_client_class.call_args
        assert kwargs["graphspace"] == "global_space"
        assert kwargs["url"] == "10.0.0.1:8080"

    @patch("hugegraph_llm.operators.hugegraph_op.schema_manager.PyHugeClient")
    @patch("hugegraph_llm.operators.hugegraph_op.schema_manager.huge_settings")
    def test_init_request_config_preserves_explicit_empty_graphspace(self, mock_settings, mock_client_class):
        mock_settings.graph_url = "default:8080"
        mock_settings.graph_user = "default_user"
        mock_settings.graph_pwd = "default_pwd"
        mock_settings.graph_space = "global_space"

        SchemaManager(
            "custom_graph",
            connection={
                "url": "10.0.0.1:8080",
                "user": "admin",
                "pwd": "secret",
                "graphspace": "",
            },
        )

        _, kwargs = mock_client_class.call_args
        assert kwargs["graphspace"] == ""
        assert kwargs["url"] == "10.0.0.1:8080"

    @patch("hugegraph_llm.operators.hugegraph_op.schema_manager.PyHugeClient")
    @patch("hugegraph_llm.operators.hugegraph_op.schema_manager.huge_settings")
    def test_init_falls_back_to_globals_without_connection(self, mock_settings, mock_client_class):
        mock_settings.graph_url = "default:8080"
        mock_settings.graph_user = "default_user"
        mock_settings.graph_pwd = "default_pwd"
        mock_settings.graph_space = "global_space"

        SchemaManager("custom_graph")

        mock_client_class.assert_called_once_with(
            url="default:8080",
            graph="custom_graph",
            user="default_user",
            pwd="default_pwd",
            graphspace="global_space",
        )

    def test_simple_schema_with_full_schema(self):
        """Test simple_schema method with a full schema."""
        # Call the method
        simple_schema = self.schema_manager.simple_schema(self.sample_schema)

        # Verify the result
        self.assertIn("vertexlabels", simple_schema)
        self.assertIn("edgelabels", simple_schema)

        # Check vertex labels
        self.assertEqual(len(simple_schema["vertexlabels"]), 2)
        for vertex in simple_schema["vertexlabels"]:
            self.assertIn("id", vertex)
            self.assertIn("name", vertex)
            self.assertIn("properties", vertex)
            self.assertNotIn("primary_keys", vertex)
            self.assertNotIn("nullable_keys", vertex)
            self.assertNotIn("index_labels", vertex)

        # Check edge labels
        self.assertEqual(len(simple_schema["edgelabels"]), 2)
        for edge in simple_schema["edgelabels"]:
            self.assertIn("name", edge)
            self.assertIn("source_label", edge)
            self.assertIn("target_label", edge)
            self.assertIn("properties", edge)
            self.assertNotIn("id", edge)
            self.assertNotIn("frequency", edge)
            self.assertNotIn("sort_keys", edge)
            self.assertNotIn("nullable_keys", edge)
            self.assertNotIn("index_labels", edge)

    def test_simple_schema_with_empty_schema(self):
        """Test simple_schema method with an empty schema."""
        empty_schema = {}
        simple_schema = self.schema_manager.simple_schema(empty_schema)
        self.assertEqual(simple_schema, {})

    def test_simple_schema_with_partial_schema(self):
        """Test simple_schema method with a partial schema."""
        partial_schema = {"vertexlabels": [{"id": 1, "name": "person", "properties": ["name", "age"]}]}
        simple_schema = self.schema_manager.simple_schema(partial_schema)
        self.assertIn("vertexlabels", simple_schema)
        self.assertNotIn("edgelabels", simple_schema)
        self.assertEqual(len(simple_schema["vertexlabels"]), 1)

    def test_run_with_valid_schema(self):
        """Test run method with a valid schema."""
        # Setup mock to return the sample schema
        self.mock_schema.getSchema.return_value = self.sample_schema

        # Call the run method
        context = {}
        result = self.schema_manager.run(context)

        # Verify the result
        self.assertIn("schema", result)
        self.assertIn("simple_schema", result)
        self.assertEqual(result["schema"], self.sample_schema)

    def test_run_with_empty_schema(self):
        """Test run method with an empty schema."""
        # Setup mock to return empty schema
        empty_schema = {"vertexlabels": [], "edgelabels": []}
        self.mock_schema.getSchema.return_value = empty_schema

        # Call the run method and expect an exception
        with self.assertRaises(Exception) as cm:
            self.schema_manager.run({})

        # Verify the exception message
        self.assertIn(f"Cannot get {self.graph_name}'s schema from HugeGraph!", str(cm.exception))

    def test_run_with_existing_context(self):
        """Test run method with an existing context."""
        # Setup mock to return the sample schema
        self.mock_schema.getSchema.return_value = self.sample_schema

        # Call the run method with an existing context
        existing_context = {"existing_key": "existing_value"}
        result = self.schema_manager.run(existing_context)

        # Verify the result
        self.assertIn("existing_key", result)
        self.assertEqual(result["existing_key"], "existing_value")
        self.assertIn("schema", result)
        self.assertIn("simple_schema", result)

    def test_run_with_none_context(self):
        """Test run method with None context."""
        # Setup mock to return the sample schema
        self.mock_schema.getSchema.return_value = self.sample_schema

        # Call the run method with None context
        result = self.schema_manager.run(None)

        # Verify the result
        self.assertIn("schema", result)
        self.assertIn("simple_schema", result)


if __name__ == "__main__":
    unittest.main()
