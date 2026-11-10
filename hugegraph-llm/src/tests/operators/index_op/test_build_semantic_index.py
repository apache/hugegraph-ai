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

# pylint: disable=protected-access

import asyncio
import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from hugegraph_llm.indices.vector_index.base import VectorStoreBase
from hugegraph_llm.indices.vector_index.faiss_vector_store import FaissVectorIndex
from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.operators.index_op.build_semantic_index import BuildSemanticIndex


class TestBuildSemanticIndex(unittest.TestCase):
    def setUp(self):
        # Create a mock embedding model
        self.mock_embedding = MagicMock(spec=BaseEmbedding)
        self.mock_embedding.get_embedding_dim.return_value = 384
        self.mock_embedding.get_texts_embeddings.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

        # Create a temporary directory for testing
        self.temp_dir = tempfile.mkdtemp()

        # Mock huge_settings
        self.patcher1 = patch("hugegraph_llm.operators.index_op.build_semantic_index.huge_settings")
        self.mock_settings = self.patcher1.start()
        self.mock_settings.graph_name = "test_graph"

        # Mock VectorStoreBase and its subclass
        self.mock_vector_store = MagicMock(spec=VectorStoreBase)
        self.mock_vector_store.get_all_properties.return_value = ["vertex1", "vertex2"]
        self.mock_vector_store.remove.return_value = 0
        self.mock_vector_store.add.return_value = None
        self.mock_vector_store.save_index_by_name.return_value = None

        # Mock the vector store class
        self.mock_vector_store_class = MagicMock()
        self.mock_vector_store_class.from_name.return_value = self.mock_vector_store

        # Mock SchemaManager
        self.patcher2 = patch("hugegraph_llm.operators.index_op.build_semantic_index.SchemaManager")
        self.mock_schema_manager_class = self.patcher2.start()
        self.mock_schema_manager = MagicMock()
        self.mock_schema_manager_class.return_value = self.mock_schema_manager
        self.mock_schema_manager.schema.get_schema.return_value = {
            "vertexlabels": [{"id_strategy": "PRIMARY_KEY"}, {"id_strategy": "PRIMARY_KEY"}]
        }

    def tearDown(self):
        # Remove the temporary directory
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

        # Stop the patchers
        self.patcher1.stop()
        self.patcher2.stop()

    def test_init(self):
        # Create a builder
        builder = BuildSemanticIndex(self.mock_embedding, self.mock_vector_store_class)

        # Check if the embedding and vector store are set correctly
        self.assertEqual(builder.embedding, self.mock_embedding)
        self.assertEqual(builder.vid_index, self.mock_vector_store)

        # Verify from_name was called with correct parameters
        self.mock_vector_store_class.from_name.assert_called_once_with(384, "test_graph", "graph_vids")

    def test_extract_names(self):
        # Create a builder
        builder = BuildSemanticIndex(self.mock_embedding, self.mock_vector_store_class)

        # Test _extract_names method
        vertices = ["label1:name1", "label2:name2", "label3:name3"]
        result = builder._extract_names(vertices)

        # Check if the names are extracted correctly
        self.assertEqual(result, ["name1", "name2", "name3"])

    def test_run_preserves_embedding_alignment_across_batches(self):
        vertices = [f"person:vid{i}" for i in range(1001)]
        self.mock_embedding.get_embedding_dim.return_value = 1

        for strategy in ("PRIMARY_KEY", "CUSTOMIZE"):
            with self.subTest(strategy=strategy):
                self.mock_settings.graph_name = os.path.join(self.temp_dir, strategy)
                self.mock_schema_manager.schema.get_schema.return_value = {"vertexlabels": [{"id_strategy": strategy}]}
                second_batch_completed = threading.Event()

                def embed_batch(batch):
                    # get_embeddings_parallel batches by 500, so the two full batches
                    # block until the trailing partial batch reports completion.
                    if len(batch) == 500:
                        if not second_batch_completed.wait(timeout=5):
                            raise RuntimeError("The concurrent batch did not complete")
                    return [[float(vid.rsplit("vid", 1)[1])] for vid in batch]

                async def async_embed_batch(batch):
                    loop = asyncio.get_running_loop()
                    return await loop.run_in_executor(None, embed_batch, batch)

                self.mock_embedding.async_get_texts_embeddings.side_effect = async_embed_batch
                builder = BuildSemanticIndex(self.mock_embedding, FaissVectorIndex)

                with patch("hugegraph_llm.utils.embedding_utils.tqdm") as mock_tqdm:
                    progress = mock_tqdm.return_value.__enter__.return_value
                    # Release the full batches only after the trailing batch reports completion.
                    progress.update.side_effect = lambda _: second_batch_completed.set()
                    result = builder.run({"vertices": vertices})

                self.assertEqual(result["added_vid_vector_num"], len(vertices))
                self.assertEqual(progress.update.call_count, 3)
                loaded_index = FaissVectorIndex.from_name(1, self.mock_settings.graph_name, "graph_vids")
                for i in (0, 500, 1000):
                    self.assertEqual(loaded_index.search([float(i)], top_k=1), [f"person:vid{i}"])

    def test_run_with_primary_key_strategy(self):
        # Create a builder
        builder = BuildSemanticIndex(self.mock_embedding, self.mock_vector_store_class)

        async def fake_embeddings(embedding, vids):
            return [[0.1, 0.2], [0.3, 0.4]]

        with patch(
            "hugegraph_llm.operators.index_op.build_semantic_index.get_embeddings_parallel",
            side_effect=fake_embeddings,
        ):
            # Create a context with new vertices
            context = {"vertices": ["label1:vertex3", "label2:vertex4"]}

            # Run the builder
            result = builder.run(context)

            # Check if the context is updated correctly
            expected_context = {
                "vertices": ["label1:vertex3", "label2:vertex4"],
                "removed_vid_vector_num": 0,
                "added_vid_vector_num": 2,
            }
            self.assertEqual(result, expected_context)

            # Verify that add and save_index_by_name were called
            self.mock_vector_store.add.assert_called_once()
            self.mock_vector_store.save_index_by_name.assert_called_once_with("test_graph", "graph_vids")

    def test_run_without_primary_key_strategy(self):
        # Change schema to non-PRIMARY_KEY strategy
        self.mock_schema_manager.schema.get_schema.return_value = {
            "vertexlabels": [{"id_strategy": "AUTOMATIC"}, {"id_strategy": "CUSTOMIZE"}]
        }

        # Create a builder
        builder = BuildSemanticIndex(self.mock_embedding, self.mock_vector_store_class)

        async def fake_embeddings(embedding, vids):
            return [[0.1, 0.2], [0.3, 0.4]]

        with patch(
            "hugegraph_llm.operators.index_op.build_semantic_index.get_embeddings_parallel",
            side_effect=fake_embeddings,
        ):
            # Create a context with new vertices
            context = {"vertices": ["vertex3", "vertex4"]}

            # Run the builder
            result = builder.run(context)

            # Check if the context is updated correctly
            expected_context = {
                "vertices": ["vertex3", "vertex4"],
                "removed_vid_vector_num": 0,
                "added_vid_vector_num": 2,
            }
            self.assertEqual(result, expected_context)

    def test_run_with_no_new_vertices(self):
        # Create a builder
        builder = BuildSemanticIndex(self.mock_embedding, self.mock_vector_store_class)

        # Create a context with vertices that are already in the index
        context = {"vertices": ["vertex1", "vertex2"]}

        # Run the builder
        result = builder.run(context)

        # Check if add and save_index_by_name were not called
        self.mock_vector_store.add.assert_not_called()
        self.mock_vector_store.save_index_by_name.assert_not_called()

        # Check if the context is updated correctly
        expected_context = {
            "vertices": ["vertex1", "vertex2"],
            "removed_vid_vector_num": 0,
            "added_vid_vector_num": 0,
        }
        self.assertEqual(result, expected_context)

    def test_run_with_removed_vertices(self):
        # Set up existing vertices that are not in the new context
        self.mock_vector_store.get_all_properties.return_value = ["vertex1", "vertex2", "vertex3"]
        self.mock_vector_store.remove.return_value = 1  # One vertex removed

        # Create a builder
        builder = BuildSemanticIndex(self.mock_embedding, self.mock_vector_store_class)

        # Create a context with fewer vertices (vertex3 will be removed)
        context = {"vertices": ["vertex1", "vertex2"]}

        # Run the builder
        result = builder.run(context)

        # Check if remove was called
        self.mock_vector_store.remove.assert_called_once()

        # Check if the context is updated correctly
        expected_context = {
            "vertices": ["vertex1", "vertex2"],
            "removed_vid_vector_num": 1,
            "added_vid_vector_num": 0,
        }
        self.assertEqual(result, expected_context)


if __name__ == "__main__":
    unittest.main()
