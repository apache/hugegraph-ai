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
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from hugegraph_llm.indices.vector_index.faiss_vector_store import FaissVectorIndex
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
    @patch("hugegraph_llm.operators.index_op.gremlin_example_index_query.log")
    @patch("os.path.join")
    def test_init_without_existing_index(self, mock_join, mock_log, mock_read_csv):
        """Test initialization when index doesn't exist and needs to be built"""
        # Create mock embedding
        mock_embedding = Mock()
        mock_embedding.get_embedding_dim.return_value = self.embed_dim
        mock_embedding.get_texts_embeddings.return_value = self.vectors

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

        # Create a GremlinExampleIndexQuery instance
        GremlinExampleIndexQuery(vector_index=mock_vector_index_class, embedding=mock_embedding, num_examples=1)

        mock_embedding.get_texts_embeddings.assert_called_once_with([row["query"] for row in self.properties])
        mock_embedding.get_text_embedding.assert_not_called()

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


class TestDefaultExampleBatching(unittest.TestCase):
    def test_batch_limit_and_order(self):
        from hugegraph_llm.models.embeddings.openai import OpenAIEmbedding

        embedding = OpenAIEmbedding(api_key="test")
        rows = [{"query": str(i), "gremlin": "g.V()"} for i in range(23)]
        batches = []

        def respond(**kwargs):
            texts = kwargs["input"]
            self.assertLessEqual(len(texts), 10)
            batches.append(len(texts))
            return SimpleNamespace(data=[SimpleNamespace(embedding=[float(text)]) for text in texts])

        operator = object.__new__(GremlinExampleIndexQuery)
        operator.embedding = embedding
        operator.vector_index = Mock()
        try:
            with (
                patch("pandas.read_csv", return_value=pd.DataFrame(rows)),
                patch.object(embedding.client.embeddings, "create", side_effect=respond),
            ):
                operator._build_default_example_index()
            self.assertEqual(batches, [10, 10, 3])
            operator.vector_index.add.assert_called_once_with([[float(i)] for i in range(23)], rows)
            operator.vector_index.save_index_by_name.assert_called_once_with("gremlin_examples")
        finally:
            embedding.client.close()

    def test_embedding_failure_does_not_save_index(self):
        operator = object.__new__(GremlinExampleIndexQuery)
        operator.embedding = Mock()
        operator.embedding.get_texts_embeddings.side_effect = RuntimeError("provider unavailable")
        operator.vector_index = Mock()
        with patch("pandas.read_csv", return_value=pd.DataFrame([{"query": "test"}])):
            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                operator._build_default_example_index()
        operator.vector_index.add.assert_not_called()
        operator.vector_index.save_index_by_name.assert_not_called()


@pytest.mark.parametrize("failed_batch", [0, 1, 2], ids=["first", "middle", "last"])
@pytest.mark.parametrize("response_kind", ["short", "empty", "extra"])
def test_invalid_batch_count_does_not_mutate_or_save_index(tmp_path, failed_batch, response_kind):
    rows = [{"query": str(i), "gremlin": "g.V()"} for i in range(23)]
    batches = []

    def respond(texts):
        batches.append(texts)
        data = [[float(text)] for text in texts]
        if len(batches) == failed_batch + 1:
            if response_kind == "short":
                data = data[:-1]
            elif response_kind == "empty":
                data = []
            else:
                data.append([999.0])
        return data

    operator = object.__new__(GremlinExampleIndexQuery)
    operator.embedding = Mock()
    operator.embedding.get_texts_embeddings.side_effect = respond
    operator.vector_index = FaissVectorIndex(1)
    with (
        patch("pandas.read_csv", return_value=pd.DataFrame(rows)),
        patch("hugegraph_llm.indices.vector_index.faiss_vector_store.resource_path", str(tmp_path)),
        patch.object(operator.vector_index, "add", wraps=operator.vector_index.add) as add,
        patch.object(
            operator.vector_index, "save_index_by_name", wraps=operator.vector_index.save_index_by_name
        ) as save,
    ):
        with pytest.raises(ValueError, match="Embedding batch returned"):
            operator._build_default_example_index()

    expected_batches = [[str(i) for i in range(start, min(start + 10, 23))] for start in (0, 10, 20)]
    assert batches == expected_batches[: failed_batch + 1]
    add.assert_not_called()
    save.assert_not_called()
    assert operator.vector_index.index.ntotal == 0
    assert operator.vector_index.properties == []
    assert not (tmp_path / "gremlin_examples").exists()
