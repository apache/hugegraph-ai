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

# pylint: disable=unused-argument,unused-variable

import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from hugegraph_llm.operators.index_op.semantic_id_query import SemanticIdQuery
from tests.utils.mock import MockEmbedding


class MockVectorStore:
    """Mock VectorStore for testing"""

    def __init__(self):
        self.search = MagicMock()

    @classmethod
    def from_name(cls, dim, graph_name, index_name):
        return cls()


class MockPyHugeClient:
    """Mock PyHugeClient for testing"""

    def __init__(self, *args, **kwargs):
        self._schema = MagicMock()
        self._schema.getVertexLabels.return_value = ["person", "movie"]
        self._gremlin = MagicMock()
        self._gremlin.exec.return_value = {
            "data": [
                {"id": "1:keyword1", "properties": {"name": "keyword1"}},
                {"id": "2:keyword2", "properties": {"name": "keyword2"}},
            ]
        }

    def schema(self):
        return self._schema

    def gremlin(self):
        return self._gremlin


class TestSemanticIdQuery(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.embedding = MockEmbedding()
        self.mock_vector_store_class = MockVectorStore

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    @patch("hugegraph_llm.operators.index_op.semantic_id_query.resource_path")
    @patch("hugegraph_llm.operators.index_op.semantic_id_query.huge_settings")
    @patch("hugegraph_llm.operators.index_op.semantic_id_query.PyHugeClient", new=MockPyHugeClient)
    def test_init(self, mock_settings, mock_resource_path):
        # Configure mocks
        mock_settings.graph_name = "test_graph"
        mock_settings.topk_per_keyword = 5
        mock_settings.vector_dis_threshold = 1.5

        with patch("os.path.join", return_value=self.test_dir):
            query = SemanticIdQuery(
                self.embedding,
                self.mock_vector_store_class,  # Pass the vector_index parameter.
                by="query",
                topk_per_query=3,
            )

            # Verify the instance was initialized correctly
            self.assertEqual(query.embedding, self.embedding)
            self.assertEqual(query.by, "query")
            self.assertEqual(query.topk_per_query, 3)
            self.assertIsInstance(query.vector_index, MockVectorStore)

    @patch("hugegraph_llm.operators.index_op.semantic_id_query.resource_path")
    @patch("hugegraph_llm.operators.index_op.semantic_id_query.huge_settings")
    @patch("hugegraph_llm.operators.index_op.semantic_id_query.PyHugeClient", new=MockPyHugeClient)
    def test_run_by_query(self, mock_settings, mock_resource_path):
        # Configure mocks
        mock_settings.graph_name = "test_graph"
        mock_settings.topk_per_keyword = 5
        mock_settings.vector_dis_threshold = 1.5

        context = {"query": "query1"}

        with patch("os.path.join", return_value=self.test_dir):
            query = SemanticIdQuery(self.embedding, self.mock_vector_store_class, by="query", topk_per_query=2)

            # Mock the search result
            query.vector_index.search.return_value = ["1:vid1", "2:vid2"]

            result_context = query.run(context)

            # Verify the results
            self.assertIn("match_vids", result_context)
            self.assertEqual(set(result_context["match_vids"]), {"1:vid1", "2:vid2"})

            # Verify the search was called
            query.vector_index.search.assert_called_once_with([1.0, 0.0, 0.0, 0.0], top_k=2)

    @patch("hugegraph_llm.operators.index_op.semantic_id_query.resource_path")
    @patch("hugegraph_llm.operators.index_op.semantic_id_query.huge_settings")
    @patch("hugegraph_llm.operators.index_op.semantic_id_query.PyHugeClient", new=MockPyHugeClient)
    def test_run_by_keywords_with_exact_match(self, mock_settings, mock_resource_path):
        mock_settings.graph_name = "test_graph"
        mock_settings.topk_per_keyword = 2
        mock_settings.vector_dis_threshold = 1.5

        context = {"keywords": ["keyword1", "keyword2"]}

        with patch("os.path.join", return_value=self.test_dir):
            query = SemanticIdQuery(self.embedding, self.mock_vector_store_class, by="keywords", topk_per_keyword=2)

            result_context = query.run(context)

            # Should find exact matches from the mock client
            self.assertIn("match_vids", result_context)
            expected_vids = {"1:keyword1", "2:keyword2"}
            self.assertTrue(expected_vids.issubset(set(result_context["match_vids"])))

    @patch("hugegraph_llm.operators.index_op.semantic_id_query.resource_path")
    @patch("hugegraph_llm.operators.index_op.semantic_id_query.huge_settings")
    @patch("hugegraph_llm.operators.index_op.semantic_id_query.PyHugeClient", new=MockPyHugeClient)
    def test_run_with_empty_keywords(self, mock_settings, mock_resource_path):
        mock_settings.graph_name = "test_graph"
        mock_settings.topk_per_keyword = 5
        mock_settings.vector_dis_threshold = 1.5

        context = {"keywords": []}

        with patch("os.path.join", return_value=self.test_dir):
            query = SemanticIdQuery(self.embedding, self.mock_vector_store_class, by="keywords")

            result_context = query.run(context)

            self.assertIn("match_vids", result_context)
            self.assertEqual(result_context["match_vids"], [])

            # Verify search was not called for empty keywords
            query.vector_index.search.assert_not_called()
