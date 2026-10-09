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
from unittest.mock import MagicMock

import pytest

from hugegraph_llm.operators.hugegraph_op.fetch_graph_data import FetchGraphData

pytestmark = [pytest.mark.unit]


class TestFetchGraphData(unittest.TestCase):
    def setUp(self):
        # Create mock PyHugeClient
        self.mock_graph = MagicMock()
        self.mock_gremlin = MagicMock()
        self.mock_graph.gremlin.return_value = self.mock_gremlin

        # Create FetchGraphData instance
        self.fetcher = FetchGraphData(self.mock_graph)

        # Sample data for testing
        self.sample_result = {
            "data": [
                {"vertex_num": 100},
                {"edge_num": 200},
                {"vertices": ["v1", "v2", "v3"]},
                {"edges": ["e1", "e2"]},
                {"note": "Only ≤10000 VIDs and ≤ 200 EIDs for brief overview ."},
            ]
        }

    def test_init(self):
        """Test initialization of FetchGraphData class."""
        self.assertEqual(self.fetcher.graph, self.mock_graph)

    def test_run_with_none_graph_summary(self):
        """Test run method with None graph_summary."""
        # Setup mock
        self.mock_gremlin.exec.return_value = self.sample_result

        # Call the method
        result = self.fetcher.run(None)

        # Verify the result
        self.assertIn("vertex_num", result)
        self.assertEqual(result["vertex_num"], 100)
        self.assertIn("edge_num", result)
        self.assertEqual(result["edge_num"], 200)
        self.assertIn("vertices", result)
        self.assertEqual(result["vertices"], ["v1", "v2", "v3"])
        self.assertIn("edges", result)
        self.assertEqual(result["edges"], ["e1", "e2"])
        self.assertIn("note", result)

        # Verify that gremlin.exec was called with the correct Groovy code
        self.mock_gremlin.exec.assert_called_once()
        groovy_code = self.mock_gremlin.exec.call_args[0][0]
        self.assertIn("g.V().count().next()", groovy_code)
        self.assertIn("g.E().count().next()", groovy_code)
        self.assertIn("g.V().id().limit(10000).toList()", groovy_code)
        self.assertIn("g.E().id().limit(200).toList()", groovy_code)

    def test_run_with_legacy_ordered_single_field_dicts_result(self):
        """Test run method with legacy ordered single-field dict rows."""
        # Setup mock
        self.mock_gremlin.exec.return_value = self.sample_result

        # Call the method
        result = self.fetcher.run({})

        # Verify the result
        self.assertEqual(result["vertex_num"], 100)
        self.assertEqual(result["edge_num"], 200)
        self.assertEqual(result["vertices"], ["v1", "v2", "v3"])
        self.assertEqual(result["edges"], ["e1", "e2"])
        self.assertEqual(result["note"], "Only ≤10000 VIDs and ≤ 200 EIDs for brief overview .")

    def test_run_with_existing_graph_summary(self):
        """Test run method with existing graph_summary."""
        # Setup mock
        self.mock_gremlin.exec.return_value = self.sample_result

        # Create existing graph summary
        existing_summary = {"existing_key": "existing_value"}

        # Call the method
        result = self.fetcher.run(existing_summary)

        # Verify the result
        self.assertIn("existing_key", result)
        self.assertEqual(result["existing_key"], "existing_value")
        self.assertIn("vertex_num", result)
        self.assertEqual(result["vertex_num"], 100)
        self.assertIn("edge_num", result)
        self.assertEqual(result["edge_num"], 200)
        self.assertIn("vertices", result)
        self.assertEqual(result["vertices"], ["v1", "v2", "v3"])
        self.assertIn("edges", result)
        self.assertEqual(result["edges"], ["e1", "e2"])
        self.assertIn("note", result)

    def test_run_with_single_summary_dict_result(self):
        """Test run method with Gremlin map result wrapped as one data row."""
        # Setup mock
        self.mock_gremlin.exec.return_value = {
            "data": [
                {
                    "vertex_num": 100,
                    "edge_num": 200,
                    "vertices": ["v1", "v2", "v3"],
                    "edges": ["e1", "e2"],
                    "note": "Only ≤10000 VIDs and ≤ 200 EIDs for brief overview .",
                }
            ]
        }

        # Call the method
        result = self.fetcher.run({})

        # Verify the result
        self.assertEqual(result["vertex_num"], 100)
        self.assertEqual(result["edge_num"], 200)
        self.assertEqual(result["vertices"], ["v1", "v2", "v3"])
        self.assertEqual(result["edges"], ["e1", "e2"])
        self.assertEqual(result["note"], "Only ≤10000 VIDs and ≤ 200 EIDs for brief overview .")

    def test_run_with_partial_single_summary_dict_result(self):
        """Test run method handles a single Gremlin map with missing summary fields."""
        # Setup mock
        self.mock_gremlin.exec.return_value = {
            "data": [
                {
                    "vertex_num": 100,
                    "vertices": ["v1", "v2", "v3"],
                }
            ]
        }

        # Call the method
        result = self.fetcher.run({})

        # Verify the result
        self.assertEqual(result["vertex_num"], 100)
        self.assertIsNone(result["edge_num"])
        self.assertEqual(result["vertices"], ["v1", "v2", "v3"])
        self.assertIsNone(result["edges"])
        self.assertIsNone(result["note"])

    def test_run_with_empty_single_summary_dict_result(self):
        """Test run method treats one empty dict as a summary row."""
        # Setup mock
        self.mock_gremlin.exec.return_value = {"data": [{}]}

        # Call the method
        result = self.fetcher.run({})

        # Verify the result
        self.assertIsNone(result["vertex_num"])
        self.assertIsNone(result["edge_num"])
        self.assertIsNone(result["vertices"])
        self.assertIsNone(result["edges"])
        self.assertIsNone(result["note"])

    def test_run_reraises_gremlin_exec_exception(self):
        """Test run method does not hide Gremlin execution failures."""
        # Setup mock
        self.mock_gremlin.exec.side_effect = RuntimeError("Gremlin endpoint unavailable")

        # Call the method and verify the original failure is visible
        with self.assertRaisesRegex(RuntimeError, "Gremlin endpoint unavailable"):
            self.fetcher.run({})

    def test_run_with_empty_result(self):
        """Test run method with empty result from gremlin."""
        # Setup mock
        self.mock_gremlin.exec.return_value = {"data": []}

        # Call the method
        result = self.fetcher.run({})

        # Verify the result
        self.assertEqual(result, {})

    def test_run_with_non_list_result(self):
        """Test run method with non-list result from gremlin."""
        # Setup mock
        self.mock_gremlin.exec.return_value = {"data": "not a list"}

        # Call the method
        result = self.fetcher.run({})

        # Verify the result
        self.assertEqual(result, {})

    def test_run_with_partial_result(self):
        """Test run method with partial result from gremlin."""
        # Setup mock to return partial result (missing some keys)
        partial_result = {
            "data": [
                {"vertex_num": 100},
                {"edge_num": 200},
                {},  # Missing vertices
                {},  # Missing edges
                {"note": "Only ≤10000 VIDs and ≤ 200 EIDs for brief overview ."},
            ]
        }
        self.mock_gremlin.exec.return_value = partial_result

        # Call the method
        result = self.fetcher.run({})

        # Verify the result - should handle missing keys gracefully
        self.assertIn("vertex_num", result)
        self.assertEqual(result["vertex_num"], 100)
        self.assertIn("edge_num", result)
        self.assertEqual(result["edge_num"], 200)
        self.assertIn("vertices", result)
        self.assertIsNone(result["vertices"])  # Should be None for missing key
        self.assertIn("edges", result)
        self.assertIsNone(result["edges"])  # Should be None for missing key
        self.assertIn("note", result)
        self.assertEqual(result["note"], "Only ≤10000 VIDs and ≤ 200 EIDs for brief overview .")


if __name__ == "__main__":
    unittest.main()
