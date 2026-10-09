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
from unittest.mock import MagicMock, Mock, patch

import pandas as pd

from hugegraph_llm.operators.index_op.gremlin_example_index_query import GremlinExampleIndexQuery


class TestGremlinExampleIndexQuery(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for testing
        self.test_dir = tempfile.mkdtemp()

        # Create sample vectors and properties for the index
        self.embed_dim = 4
        self.vectors = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
        self.properties = [
            {"query": "find all persons", "gremlin": "g.V().hasLabel('person')"},
            {"query": "count movies", "gremlin": "g.V().hasLabel('movie').count()"},
        ]

    def tearDown(self):
        # Clean up the temporary directory
        shutil.rmtree(self.test_dir)

    def test_init_with_existing_index(self):
        """Test initialization when index already exists"""
        # Create mock embedding
        mock_embedding = Mock()
        mock_embedding.get_embedding_dim.return_value = self.embed_dim
        mock_embedding.get_texts_embeddings.return_value = [self.vectors[0]]
        mock_embedding.get_text_embedding.return_value = self.vectors[0]

        # Create mock vector index class and instance
        mock_vector_index_class = MagicMock()
        mock_index_instance = MagicMock()

        # Configure the mock vector index class
        mock_vector_index_class.exist.return_value = True
        mock_vector_index_class.from_name.return_value = mock_index_instance

        # Create a GremlinExampleIndexQuery instance
        query = GremlinExampleIndexQuery(vector_index=mock_vector_index_class, embedding=mock_embedding, num_examples=2)

        # Verify the instance was initialized correctly
        self.assertEqual(query.embedding, mock_embedding)
        self.assertEqual(query.num_examples, 2)
        self.assertEqual(query.vector_index, mock_index_instance)

        # Verify that exist() and from_name() were called
        mock_vector_index_class.exist.assert_called_once_with("gremlin_examples")
        mock_vector_index_class.from_name.assert_called_once_with(self.embed_dim, "gremlin_examples")

    @patch("hugegraph_llm.operators.index_op.gremlin_example_index_query.resource_path", "/mock/path")
    @patch("pandas.read_csv")
    @patch("concurrent.futures.ThreadPoolExecutor")
    @patch("hugegraph_llm.operators.index_op.gremlin_example_index_query.tqdm")
    @patch("hugegraph_llm.operators.index_op.gremlin_example_index_query.log")
    @patch("os.path.join")
    def test_init_without_existing_index(self, mock_join, mock_log, mock_tqdm, mock_thread_pool, mock_read_csv):
        """Test initialization when index doesn't exist and needs to be built"""
        # Create mock embedding
        mock_embedding = Mock()
        mock_embedding.get_embedding_dim.return_value = self.embed_dim
        mock_embedding.get_text_embedding.side_effect = lambda x: self.vectors[0] if "persons" in x else self.vectors[1]

        # Create mock vector index class and instance
        mock_vector_index_class = MagicMock()
        mock_index_instance = MagicMock()

        # Configure mocks
        mock_vector_index_class.exist.return_value = False
        mock_vector_index_class.from_name.return_value = mock_index_instance
        mock_join.return_value = "/mock/path/demo/text2gremlin.csv"

        # Mock CSV data
        mock_df = pd.DataFrame(self.properties)
        mock_read_csv.return_value = mock_df

        # Mock thread pool execution
        mock_executor = MagicMock()
        mock_thread_pool.return_value.__enter__.return_value = mock_executor
        mock_executor.map.return_value = self.vectors
        mock_tqdm.return_value = self.vectors

        # Create a GremlinExampleIndexQuery instance
        GremlinExampleIndexQuery(vector_index=mock_vector_index_class, embedding=mock_embedding, num_examples=1)

        # Verify that the index was built
        mock_vector_index_class.exist.assert_called_once_with("gremlin_examples")
        mock_vector_index_class.from_name.assert_called_once_with(self.embed_dim, "gremlin_examples")
        mock_index_instance.add.assert_called_once_with(self.vectors, self.properties)
        mock_index_instance.save_index_by_name.assert_called_once_with("gremlin_examples")
        mock_log.warning.assert_called_once_with("No gremlin example index found, will generate one.")

    def test_run_with_query(self):
        """Test run method with a valid query"""
        # Create mock embedding
        mock_embedding = Mock()
        mock_embedding.get_embedding_dim.return_value = self.embed_dim
        mock_embedding.get_texts_embeddings.return_value = [self.vectors[0]]

        # Create mock vector index class and instance
        mock_vector_index_class = MagicMock()
        mock_index_instance = MagicMock()

        # Configure mocks
        mock_vector_index_class.exist.return_value = True
        mock_vector_index_class.from_name.return_value = mock_index_instance
        mock_index_instance.search.return_value = [self.properties[0]]

        # Create a context with a query
        context = {"query": "find all persons"}

        # Create a GremlinExampleIndexQuery instance
        query = GremlinExampleIndexQuery(vector_index=mock_vector_index_class, embedding=mock_embedding, num_examples=1)

        # Run the query
        result_context = query.run(context)

        # Verify the results
        self.assertIn("match_result", result_context)
        self.assertEqual(result_context["match_result"], [self.properties[0]])

        # Verify the mock was called correctly
        mock_index_instance.search.assert_called_once()
        args, kwargs = mock_index_instance.search.call_args
        self.assertEqual(args[0], self.vectors[0])  # embedding
        self.assertEqual(args[1], 1)  # num_examples
        self.assertEqual(kwargs.get("dis_threshold"), 1.8)

    def test_run_with_query_embedding(self):
        """Test run method with pre-computed query embedding"""
        # Create mock embedding
        mock_embedding = Mock()
        mock_embedding.get_embedding_dim.return_value = self.embed_dim

        # Create mock vector index class and instance
        mock_vector_index_class = MagicMock()
        mock_index_instance = MagicMock()

        # Configure mocks
        mock_vector_index_class.exist.return_value = True
        mock_vector_index_class.from_name.return_value = mock_index_instance
        mock_index_instance.search.return_value = [self.properties[0]]

        # Create a context with a pre-computed query embedding
        context = {"query": "find all persons", "query_embedding": [1.0, 0.0, 0.0, 0.0]}

        # Create a GremlinExampleIndexQuery instance
        query = GremlinExampleIndexQuery(vector_index=mock_vector_index_class, embedding=mock_embedding, num_examples=1)

        # Run the query
        result_context = query.run(context)

        # Verify the results
        self.assertIn("match_result", result_context)
        self.assertEqual(result_context["match_result"], [self.properties[0]])

        # Verify the mock was called with the pre-computed embedding
        # Should NOT call embedding.get_texts_embeddings since query_embedding is provided
        mock_index_instance.search.assert_called_once()
        args, _ = mock_index_instance.search.call_args
        self.assertEqual(args[0], [1.0, 0.0, 0.0, 0.0])

        # Verify that get_texts_embeddings was NOT called
        mock_embedding.get_texts_embeddings.assert_not_called()

    def test_run_with_zero_examples(self):
        """Test run method with num_examples=0"""
        # Create mock embedding
        mock_embedding = Mock()
        mock_embedding.get_embedding_dim.return_value = self.embed_dim

        # Create mock vector index class and instance
        mock_vector_index_class = MagicMock()
        mock_index_instance = MagicMock()

        # Configure mocks
        mock_vector_index_class.exist.return_value = True
        mock_vector_index_class.from_name.return_value = mock_index_instance

        # Create a context with a query
        context = {"query": "find all persons"}

        # Create a GremlinExampleIndexQuery instance with num_examples=0
        query = GremlinExampleIndexQuery(vector_index=mock_vector_index_class, embedding=mock_embedding, num_examples=0)

        # Run the query
        result_context = query.run(context)

        # Verify the results
        self.assertIn("match_result", result_context)
        self.assertEqual(result_context["match_result"], [])

        # Verify the mock was not called
        mock_index_instance.search.assert_not_called()

    def test_run_without_query(self):
        """Test run method without query raises ValueError"""
        # Create mock embedding
        mock_embedding = Mock()
        mock_embedding.get_embedding_dim.return_value = self.embed_dim

        # Create mock vector index class and instance
        mock_vector_index_class = MagicMock()
        mock_index_instance = MagicMock()

        # Configure mocks
        mock_vector_index_class.exist.return_value = True
        mock_vector_index_class.from_name.return_value = mock_index_instance

        # Create a context without a query
        context = {}

        # Create a GremlinExampleIndexQuery instance
        query = GremlinExampleIndexQuery(vector_index=mock_vector_index_class, embedding=mock_embedding, num_examples=1)

        # Run the query and expect a ValueError
        with self.assertRaises(ValueError) as cm:
            query.run(context)

        self.assertEqual(str(cm.exception), "query is required")

    @patch("hugegraph_llm.operators.index_op.gremlin_example_index_query.Embeddings")
    def test_init_with_default_embedding(self, mock_embeddings_class):
        """Test initialization with default embedding"""
        # Create mock vector index class and instance
        mock_vector_index_class = MagicMock()
        mock_index_instance = MagicMock()

        # Configure mocks
        mock_vector_index_class.exist.return_value = True
        mock_vector_index_class.from_name.return_value = mock_index_instance

        mock_embedding_instance = Mock()
        mock_embedding_instance.get_embedding_dim.return_value = self.embed_dim
        mock_embeddings_class.return_value.get_embedding.return_value = mock_embedding_instance

        # Create instance without embedding parameter
        query = GremlinExampleIndexQuery(vector_index=mock_vector_index_class, num_examples=1)

        # Verify default embedding was used
        self.assertEqual(query.embedding, mock_embedding_instance)
        mock_embeddings_class.assert_called_once()
        mock_embeddings_class.return_value.get_embedding.assert_called_once()

    def test_run_with_negative_examples(self):
        """Test run method with negative num_examples"""
        # Create mock embedding
        mock_embedding = Mock()
        mock_embedding.get_embedding_dim.return_value = self.embed_dim

        # Create mock vector index class and instance
        mock_vector_index_class = MagicMock()
        mock_index_instance = MagicMock()

        # Configure mocks
        mock_vector_index_class.exist.return_value = True
        mock_vector_index_class.from_name.return_value = mock_index_instance

        # Create a context with a query
        context = {"query": "find all persons"}

        # Create a GremlinExampleIndexQuery instance with negative num_examples
        query = GremlinExampleIndexQuery(
            vector_index=mock_vector_index_class, embedding=mock_embedding, num_examples=-1
        )

        # Run the query
        result_context = query.run(context)

        # Verify the results - should return empty list for negative examples
        self.assertIn("match_result", result_context)
        self.assertEqual(result_context["match_result"], [])

        # Verify the mock was not called
        mock_index_instance.search.assert_not_called()

    def test_get_match_result_with_non_list_embedding(self):
        """Test _get_match_result when query_embedding is not a list"""
        # Create mock embedding
        mock_embedding = Mock()
        mock_embedding.get_embedding_dim.return_value = self.embed_dim
        mock_embedding.get_texts_embeddings.return_value = [self.vectors[0]]

        # Create mock vector index class and instance
        mock_vector_index_class = MagicMock()
        mock_index_instance = MagicMock()

        # Configure mocks
        mock_vector_index_class.exist.return_value = True
        mock_vector_index_class.from_name.return_value = mock_index_instance
        mock_index_instance.search.return_value = [self.properties[0]]

        # Create a GremlinExampleIndexQuery instance
        query = GremlinExampleIndexQuery(vector_index=mock_vector_index_class, embedding=mock_embedding, num_examples=1)

        # Test with non-list query_embedding (should use embedding service)
        context = {"query": "find all persons", "query_embedding": "not_a_list"}
        result_context = query.run(context)

        # Verify the results
        self.assertIn("match_result", result_context)
        self.assertEqual(result_context["match_result"], [self.properties[0]])

        # Verify that get_texts_embeddings was called since query_embedding wasn't a list
        mock_embedding.get_texts_embeddings.assert_called_once_with(["find all persons"])
