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

from hugegraph_llm.indices.vector_index.base import VectorStoreBase
from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.operators.index_op.build_gremlin_example_index import BuildGremlinExampleIndex


class TestBuildGremlinExampleIndex(unittest.TestCase):
    def setUp(self):
        # Mock embedding model
        self.mock_embedding = MagicMock(spec=BaseEmbedding)

        # Prepare test examples
        self.examples = [
            {"query": "g.V().hasLabel('person')", "description": "Find all persons"},
            {"query": "g.V().hasLabel('movie')", "description": "Find all movies"},
        ]

        # Mock vector store instance
        self.mock_vector_store_instance = MagicMock(spec=VectorStoreBase)

        # Mock vector store class - 正确设置 from_name 方法
        self.mock_vector_store_class = MagicMock()
        self.mock_vector_store_class.from_name = MagicMock(return_value=self.mock_vector_store_instance)

        # Create instance
        self.index_builder = BuildGremlinExampleIndex(
            embedding=self.mock_embedding, examples=self.examples, vector_index=self.mock_vector_store_class
        )

    def test_init(self):
        """Test initialization of BuildGremlinExampleIndex"""
        self.assertEqual(self.index_builder.embedding, self.mock_embedding)
        self.assertEqual(self.index_builder.examples, self.examples)
        self.assertEqual(self.index_builder.vector_index, self.mock_vector_store_class)
        self.assertEqual(self.index_builder.vector_index_name, "gremlin_examples")

    @patch('asyncio.run')
    @patch(
        'hugegraph_llm.operators.index_op.build_gremlin_example_index.get_embeddings_parallel',
        new_callable=MagicMock,
    )
    def test_run_with_examples(self, mock_get_embeddings_parallel, mock_asyncio_run):
        """Test run method with examples"""
        # Setup mocks
        test_embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_asyncio_run.return_value = test_embeddings

        # Run the method
        context = {}
        result = self.index_builder.run(context)

        # Verify asyncio.run was called
        mock_asyncio_run.assert_called_once()

        # Verify vector store operations
        self.mock_vector_store_class.from_name.assert_called_once_with(3, "gremlin_examples")
        self.mock_vector_store_instance.add.assert_called_once_with(test_embeddings, self.examples)
        self.mock_vector_store_instance.save_index_by_name.assert_called_once_with("gremlin_examples")

        # Verify context update
        self.assertEqual(result["embed_dim"], 3)
        self.assertEqual(context["embed_dim"], 3)

    @patch('asyncio.run')
    @patch(
        'hugegraph_llm.operators.index_op.build_gremlin_example_index.get_embeddings_parallel',
        new_callable=MagicMock,
    )
    def test_run_with_empty_examples(self, mock_get_embeddings_parallel, mock_asyncio_run):
        """Test run method with empty examples"""
        # Create new mocks for this test
        mock_vector_store_instance = MagicMock(spec=VectorStoreBase)
        mock_vector_store_class = MagicMock()
        mock_vector_store_class.from_name = MagicMock(return_value=mock_vector_store_instance)

        # Create instance with empty examples
        empty_index_builder = BuildGremlinExampleIndex(
            embedding=self.mock_embedding, examples=[], vector_index=mock_vector_store_class
        )

        # Run the method
        context = {}

        # Empty examples should be handled gracefully without building vector index.
        result = empty_index_builder.run(context)

        mock_asyncio_run.assert_not_called()
        mock_get_embeddings_parallel.assert_not_called()
        mock_vector_store_class.clean.assert_not_called()
        mock_vector_store_class.from_name.assert_not_called()
        mock_vector_store_instance.add.assert_not_called()
        mock_vector_store_instance.save_index_by_name.assert_not_called()

        self.assertEqual(result["embed_dim"], 0)
        self.assertEqual(context["embed_dim"], 0)

    @patch('asyncio.run')
    @patch(
        'hugegraph_llm.operators.index_op.build_gremlin_example_index.get_embeddings_parallel',
        new_callable=MagicMock,
    )
    def test_run_with_empty_embeddings(self, mock_get_embeddings_parallel, mock_asyncio_run):
        """Test run method when embedding returns no vectors"""
        mock_asyncio_run.return_value = []

        context = {}
        with self.assertRaisesRegex(ValueError, "Embedding service returned empty result"):
            self.index_builder.run(context)

        mock_asyncio_run.assert_called_once()
        mock_get_embeddings_parallel.assert_called_once()
        self.mock_vector_store_class.clean.assert_not_called()
        self.mock_vector_store_class.from_name.assert_not_called()
        self.mock_vector_store_instance.add.assert_not_called()
        self.mock_vector_store_instance.save_index_by_name.assert_not_called()
        self.assertNotIn("embed_dim", context)

    @patch('asyncio.run')
    @patch(
        'hugegraph_llm.operators.index_op.build_gremlin_example_index.get_embeddings_parallel',
        new_callable=MagicMock,
    )
    def test_run_single_example(self, mock_get_embeddings_parallel, mock_asyncio_run):
        """Test run method with single example"""
        # Create new mocks for this test
        mock_vector_store_instance = MagicMock(spec=VectorStoreBase)
        mock_vector_store_class = MagicMock()
        mock_vector_store_class.from_name = MagicMock(return_value=mock_vector_store_instance)

        # Create instance with single example
        single_example = [{"query": "g.V().count()", "description": "Count all vertices"}]
        single_index_builder = BuildGremlinExampleIndex(
            embedding=self.mock_embedding, examples=single_example, vector_index=mock_vector_store_class
        )

        # Setup mocks
        test_embeddings = [[0.7, 0.8, 0.9, 0.1]]  # 4-dimensional embedding
        mock_asyncio_run.return_value = test_embeddings

        # Run the method
        context = {}
        result = single_index_builder.run(context)

        # Verify operations
        mock_vector_store_class.from_name.assert_called_once_with(4, "gremlin_examples")
        mock_vector_store_instance.add.assert_called_once_with(test_embeddings, single_example)
        mock_vector_store_instance.save_index_by_name.assert_called_once_with("gremlin_examples")

        # Verify context
        self.assertEqual(result["embed_dim"], 4)

    @patch('asyncio.run')
    @patch(
        'hugegraph_llm.operators.index_op.build_gremlin_example_index.get_embeddings_parallel',
        new_callable=MagicMock,
    )
    def test_run_preserves_existing_context(self, mock_get_embeddings_parallel, mock_asyncio_run):
        """Test that run method preserves existing context data"""
        # Setup mocks
        test_embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_asyncio_run.return_value = test_embeddings

        # Run with existing context
        context = {"existing_key": "existing_value", "another_key": 123}
        result = self.index_builder.run(context)

        # Verify existing context is preserved
        self.assertEqual(result["existing_key"], "existing_value")
        self.assertEqual(result["another_key"], 123)
        self.assertEqual(result["embed_dim"], 3)

        # Verify original context is modified
        self.assertEqual(context["embed_dim"], 3)


if __name__ == '__main__':
    unittest.main()
