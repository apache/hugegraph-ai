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

import unittest
from unittest.mock import MagicMock, patch

from hugegraph_llm.indices.vector_index.base import VectorStoreBase
from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.operators.index_op.build_vector_index import BuildVectorIndex


class TestBuildVectorIndex(unittest.TestCase):
    def setUp(self):
        # Create a mock embedding model
        self.mock_embedding = MagicMock(spec=BaseEmbedding)
        self.mock_embedding.get_embedding_dim.return_value = 128

        # Create a mock vector store instance
        self.mock_vector_store = MagicMock(spec=VectorStoreBase)

        # Create a mock vector store class with from_name method
        self.mock_vector_store_class = MagicMock()
        self.mock_vector_store_class.from_name = MagicMock(return_value=self.mock_vector_store)

        # Patch huge_settings
        self.patcher_settings = patch("hugegraph_llm.operators.index_op.build_vector_index.huge_settings")
        self.mock_settings = self.patcher_settings.start()
        self.mock_settings.graph_name = "test_graph"

        # Patch get_embeddings_parallel
        self.patcher_embeddings = patch("hugegraph_llm.operators.index_op.build_vector_index.get_embeddings_parallel")
        self.mock_get_embeddings = self.patcher_embeddings.start()

    def tearDown(self):
        self.patcher_settings.stop()
        self.patcher_embeddings.stop()

    def test_init(self):
        # Create a builder
        builder = BuildVectorIndex(self.mock_embedding, self.mock_vector_store_class)

        # Check if the embedding and vector_index are set correctly
        self.assertEqual(builder.embedding, self.mock_embedding)
        self.assertEqual(builder.vector_index, self.mock_vector_store)

        # Check if from_name was called with correct parameters
        self.mock_vector_store_class.from_name.assert_called_once_with(128, "test_graph", "chunks")

    def test_run_with_chunks(self):
        # Mock get_embeddings_parallel to return embeddings
        mock_embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

        # Create a builder
        builder = BuildVectorIndex(self.mock_embedding, self.mock_vector_store_class)

        # Create a context with chunks
        chunks = ["chunk1", "chunk2"]
        context = {"chunks": chunks}

        # Mock asyncio.run to avoid actual async execution in test
        with patch('asyncio.run') as mock_asyncio_run:
            mock_asyncio_run.return_value = mock_embeddings

            # Run the builder
            result = builder.run(context)

            # Check if asyncio.run was called
            mock_asyncio_run.assert_called_once()

            # Check if add and save_index_by_name were called
            self.mock_vector_store.add.assert_called_once_with(mock_embeddings, chunks)
            self.mock_vector_store.save_index_by_name.assert_called_once_with("test_graph", "chunks")

            # Check if the context is returned unchanged
            self.assertEqual(result, context)

    def test_run_without_chunks(self):
        # Create a builder
        builder = BuildVectorIndex(self.mock_embedding, self.mock_vector_store_class)

        # Create a context without chunks
        context = {"other_key": "value"}

        # Run the builder and expect a ValueError
        with self.assertRaises(ValueError) as cm:
            builder.run(context)

        self.assertEqual(str(cm.exception), "chunks not found in context.")

    def test_run_with_empty_chunks(self):
        # Create a builder
        builder = BuildVectorIndex(self.mock_embedding, self.mock_vector_store_class)

        # Create a context with empty chunks
        context = {"chunks": []}

        # Mock asyncio.run
        with patch('asyncio.run') as mock_asyncio_run:
            mock_asyncio_run.return_value = []

            # Run the builder
            result = builder.run(context)

            # Check if add and save_index_by_name were not called
            self.mock_vector_store.add.assert_not_called()
            self.mock_vector_store.save_index_by_name.assert_not_called()

            # Check if the context is returned unchanged
            self.assertEqual(result, context)

    @patch('hugegraph_llm.operators.index_op.build_vector_index.log')
    def test_logging(self, mock_log):
        # Mock get_embeddings_parallel
        mock_embeddings = [[0.1, 0.2, 0.3]]

        # Create a builder
        builder = BuildVectorIndex(self.mock_embedding, self.mock_vector_store_class)

        # Create a context with chunks
        chunks = ["chunk1"]
        context = {"chunks": chunks}

        # Mock asyncio.run
        with patch('asyncio.run') as mock_asyncio_run:
            mock_asyncio_run.return_value = mock_embeddings

            # Run the builder
            builder.run(context)

            # Check if debug log was called
            mock_log.debug.assert_called_once_with("Building vector index for %s chunks...", 1)


if __name__ == "__main__":
    unittest.main()
