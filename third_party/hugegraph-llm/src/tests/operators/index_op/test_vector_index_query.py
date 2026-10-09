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

# pylint: disable=unused-argument

import unittest
from unittest.mock import MagicMock, patch

from hugegraph_llm.operators.index_op.vector_index_query import VectorIndexQuery

# FIXME: add a flow-to-operator contract test proving topk and
# vector_dis_threshold are passed through instead of hard-coded.


class TestVectorIndexQuery(unittest.TestCase):
    def setUp(self):
        # Create mock embedding model
        self.mock_embedding = MagicMock()
        self.mock_embedding.get_embedding_dim.return_value = 4
        self.mock_embedding.get_texts_embeddings.return_value = [[1.0, 0.0, 0.0, 0.0]]

        # Create mock vector store class
        self.mock_vector_store_class = MagicMock()
        self.mock_vector_index = MagicMock()
        self.mock_vector_store_class.from_name.return_value = self.mock_vector_index
        self.mock_vector_index.search.return_value = ["doc1", "doc2"]

    @patch("hugegraph_llm.operators.index_op.vector_index_query.huge_settings")
    def test_init(self, mock_settings):
        """Test VectorIndexQuery initialization"""
        # Configure mock settings
        mock_settings.graph_name = "test_graph"

        # Create VectorIndexQuery instance
        query = VectorIndexQuery(vector_index=self.mock_vector_store_class, embedding=self.mock_embedding, topk=3)

        # Verify initialization
        self.assertEqual(query.embedding, self.mock_embedding)
        self.assertEqual(query.topk, 3)
        self.assertEqual(query.vector_index, self.mock_vector_index)

        # Verify vector store was initialized correctly
        self.mock_vector_store_class.from_name.assert_called_once_with(4, "test_graph", "chunks")

    @patch("hugegraph_llm.operators.index_op.vector_index_query.huge_settings")
    def test_run_with_query(self, mock_settings):
        """Test run method with valid query"""
        # Configure mock settings
        mock_settings.graph_name = "test_graph"

        # Create VectorIndexQuery instance
        query = VectorIndexQuery(vector_index=self.mock_vector_store_class, embedding=self.mock_embedding, topk=2)

        # Prepare context with query
        context = {"query": "test query"}

        # Run the query
        result_context = query.run(context)

        # Verify results
        self.assertIn("vector_result", result_context)
        self.assertEqual(result_context["vector_result"], ["doc1", "doc2"])

        # Verify embedding was called correctly
        self.mock_embedding.get_texts_embeddings.assert_called_once_with(["test query"])

        # Verify vector search was called correctly
        self.mock_vector_index.search.assert_called_once_with([1.0, 0.0, 0.0, 0.0], 2, dis_threshold=2)

    @patch("hugegraph_llm.operators.index_op.vector_index_query.huge_settings")
    def test_run_with_none_query(self, mock_settings):
        """Test run method when query is None"""
        # Configure mock settings
        mock_settings.graph_name = "test_graph"

        # Create VectorIndexQuery instance
        query = VectorIndexQuery(vector_index=self.mock_vector_store_class, embedding=self.mock_embedding, topk=2)

        # Prepare context without query or with None query
        context = {"query": None}

        # Run the query
        result_context = query.run(context)

        # Verify results
        self.assertIn("vector_result", result_context)
        self.assertEqual(result_context["vector_result"], ["doc1", "doc2"])

        # Verify embedding was called with None
        self.mock_embedding.get_texts_embeddings.assert_called_once_with([None])

    @patch("hugegraph_llm.operators.index_op.vector_index_query.huge_settings")
    def test_run_with_empty_context(self, mock_settings):
        """Test run method with empty context"""
        # Configure mock settings
        mock_settings.graph_name = "test_graph"

        # Create VectorIndexQuery instance
        query = VectorIndexQuery(vector_index=self.mock_vector_store_class, embedding=self.mock_embedding, topk=2)

        # Prepare empty context
        context = {}

        # Run the query
        result_context = query.run(context)

        # Verify results
        self.assertIn("vector_result", result_context)
        self.assertEqual(result_context["vector_result"], ["doc1", "doc2"])

        # Verify embedding was called with None (default value from context.get)
        self.mock_embedding.get_texts_embeddings.assert_called_once_with([None])

    @patch("hugegraph_llm.operators.index_op.vector_index_query.huge_settings")
    def test_run_with_different_topk(self, mock_settings):
        """Test run method with different topk value"""
        # Configure mock settings
        mock_settings.graph_name = "test_graph"

        # Configure different search results
        self.mock_vector_index.search.return_value = ["doc1", "doc2", "doc3", "doc4", "doc5"]

        # Create VectorIndexQuery instance with different topk
        query = VectorIndexQuery(vector_index=self.mock_vector_store_class, embedding=self.mock_embedding, topk=5)

        # Prepare context
        context = {"query": "test query"}

        # Run the query
        result_context = query.run(context)

        # Verify results
        self.assertEqual(result_context["vector_result"], ["doc1", "doc2", "doc3", "doc4", "doc5"])

        # Verify vector search was called with correct topk
        self.mock_vector_index.search.assert_called_once_with([1.0, 0.0, 0.0, 0.0], 5, dis_threshold=2)

    @patch("hugegraph_llm.operators.index_op.vector_index_query.huge_settings")
    def test_run_with_different_embedding_result(self, mock_settings):
        """Test run method with different embedding result"""
        # Configure mock settings
        mock_settings.graph_name = "test_graph"

        # Configure different embedding result
        self.mock_embedding.get_texts_embeddings.return_value = [[0.0, 1.0, 0.0, 0.0]]

        # Create VectorIndexQuery instance
        query = VectorIndexQuery(vector_index=self.mock_vector_store_class, embedding=self.mock_embedding, topk=2)

        # Prepare context
        context = {"query": "another query"}

        # Run the query
        _ = query.run(context)

        # Verify vector search was called with correct embedding
        self.mock_vector_index.search.assert_called_once_with([0.0, 1.0, 0.0, 0.0], 2, dis_threshold=2)

    @patch("hugegraph_llm.operators.index_op.vector_index_query.huge_settings")
    def test_context_preservation(self, mock_settings):
        """Test that existing context data is preserved"""
        # Configure mock settings
        mock_settings.graph_name = "test_graph"

        # Create VectorIndexQuery instance
        query = VectorIndexQuery(vector_index=self.mock_vector_store_class, embedding=self.mock_embedding, topk=2)

        # Prepare context with existing data
        context = {"query": "test query", "existing_key": "existing_value", "another_key": 123}

        # Run the query
        result_context = query.run(context)

        # Verify that existing context data is preserved
        self.assertEqual(result_context["existing_key"], "existing_value")
        self.assertEqual(result_context["another_key"], 123)
        self.assertEqual(result_context["query"], "test query")
        self.assertIn("vector_result", result_context)

    @patch("hugegraph_llm.operators.index_op.vector_index_query.huge_settings")
    def test_init_with_custom_parameters(self, mock_settings):
        """Test initialization with custom parameters"""
        # Configure mock settings
        mock_settings.graph_name = "custom_graph"

        # Create mock embedding with different dimensions
        custom_embedding = MagicMock()
        custom_embedding.get_embedding_dim.return_value = 256

        # Create VectorIndexQuery instance with custom parameters
        query = VectorIndexQuery(vector_index=self.mock_vector_store_class, embedding=custom_embedding, topk=10)

        # Verify initialization with custom parameters
        self.assertEqual(query.topk, 10)
        self.assertEqual(query.embedding, custom_embedding)

        # Verify vector store was initialized with custom parameters
        self.mock_vector_store_class.from_name.assert_called_once_with(256, "custom_graph", "chunks")


if __name__ == "__main__":
    unittest.main()
