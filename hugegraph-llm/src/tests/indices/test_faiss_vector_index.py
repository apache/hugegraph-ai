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


import os
import shutil
import tempfile
import unittest
from pprint import pprint

from hugegraph_llm.indices.vector_index.faiss_vector_store import FaissVectorIndex
from hugegraph_llm.models.embeddings.ollama import OllamaEmbedding

# FIXME: add cross-backend vector-store contract tests for Qdrant/Milvus/Faiss
# threshold semantics instead of covering only the Faiss implementation.


class TestVectorIndex(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for testing
        self.test_dir = tempfile.mkdtemp()
        # Create sample vectors and properties
        self.embed_dim = 4  # Small dimension for testing
        self.vectors = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
        self.properties = ["doc1", "doc2", "doc3", "doc4"]

    def tearDown(self):
        # Clean up the temporary directory
        shutil.rmtree(self.test_dir)

    def test_init(self):
        """Test initialization of VectorIndex"""
        index = FaissVectorIndex(self.embed_dim)
        self.assertEqual(index.index.d, self.embed_dim)
        self.assertEqual(index.index.ntotal, 0)
        self.assertEqual(len(index.properties), 0)

    def test_add(self):
        """Test adding vectors to the index"""
        index = FaissVectorIndex(self.embed_dim)
        index.add(self.vectors, self.properties)

        self.assertEqual(index.index.ntotal, 4)
        self.assertEqual(len(index.properties), 4)
        self.assertEqual(index.properties, self.properties)

    def test_add_empty(self):
        """Test adding empty vectors list"""
        index = FaissVectorIndex(self.embed_dim)
        index.add([], [])

        self.assertEqual(index.index.ntotal, 0)
        self.assertEqual(len(index.properties), 0)

    def test_search(self):
        """Test searching vectors in the index"""
        index = FaissVectorIndex(self.embed_dim)
        index.add(self.vectors, self.properties)

        # Search for a vector similar to the first one
        query_vector = [0.9, 0.1, 0.0, 0.0]
        results = index.search(query_vector, top_k=2)

        # We don't assert the exact number of results because it depends on the distance threshold
        # Instead, we check that we get at least one result and it's the expected one
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0], "doc1")  # Most similar to first vector

    def test_search_empty_index(self):
        """Test searching in an empty index"""
        index = FaissVectorIndex(self.embed_dim)
        query_vector = [1.0, 0.0, 0.0, 0.0]
        results = index.search(query_vector, top_k=2)

        self.assertEqual(len(results), 0)

    def test_search_dimension_mismatch(self):
        """Test searching with mismatched dimensions"""
        index = FaissVectorIndex(self.embed_dim)
        index.add(self.vectors, self.properties)

        # Query vector with wrong dimension
        query_vector = [1.0, 0.0, 0.0]

        with self.assertRaises(ValueError):
            index.search(query_vector, top_k=2)

    def test_remove(self):
        """Test removing vectors from the index"""
        index = FaissVectorIndex(self.embed_dim)
        index.add(self.vectors, self.properties)

        # Remove two properties
        removed = index.remove(["doc1", "doc3"])

        self.assertEqual(removed, 2)
        self.assertEqual(index.index.ntotal, 2)
        self.assertEqual(len(index.properties), 2)
        self.assertEqual(index.properties, ["doc2", "doc4"])

    def test_remove_nonexistent(self):
        """Test removing nonexistent properties"""
        index = FaissVectorIndex(self.embed_dim)
        index.add(self.vectors, self.properties)

        # Remove nonexistent property
        removed = index.remove(["nonexistent"])

        self.assertEqual(removed, 0)
        self.assertEqual(index.index.ntotal, 4)
        self.assertEqual(len(index.properties), 4)

    def test_save_load(self):
        """Test saving and loading the index"""
        # Create and populate an index
        index = FaissVectorIndex(self.embed_dim)
        index.add(self.vectors, self.properties)

        # Save the index
        index.save_index_by_name(self.test_dir)

        # Load the index
        loaded_index = FaissVectorIndex.from_name(self.embed_dim, self.test_dir)

        # Verify the loaded index
        self.assertEqual(loaded_index.index.d, self.embed_dim)
        self.assertEqual(loaded_index.index.ntotal, 4)
        self.assertEqual(len(loaded_index.properties), 4)
        self.assertEqual(loaded_index.properties, self.properties)

        # Test search on loaded index
        query_vector = [0.9, 0.1, 0.0, 0.0]
        results = loaded_index.search(query_vector, top_k=1)
        self.assertEqual(results[0], "doc1")

    def test_load_nonexistent(self):
        """Test loading from a nonexistent directory"""
        nonexistent_dir = os.path.join(self.test_dir, "nonexistent")
        loaded_index = FaissVectorIndex.from_name(1024, nonexistent_dir)

        # Should create a new index
        self.assertEqual(loaded_index.index.d, 1024)  # Default dimension
        self.assertEqual(loaded_index.index.ntotal, 0)
        self.assertEqual(len(loaded_index.properties), 0)

    def test_clean(self):
        """Test cleaning index files"""
        # Create and save an index
        index = FaissVectorIndex(self.embed_dim)
        index.add(self.vectors, self.properties)
        index.save_index_by_name(self.test_dir)

        # Verify files exist
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "index.faiss")))
        self.assertTrue(os.path.exists(os.path.join(self.test_dir, "properties.pkl")))

        # Clean the index
        FaissVectorIndex.clean(self.test_dir)

        # Verify files are removed
        self.assertFalse(os.path.exists(os.path.join(self.test_dir, "index.faiss")))
        self.assertFalse(os.path.exists(os.path.join(self.test_dir, "properties.pkl")))

    @unittest.skip("Requires Ollama service to be running")
    def test_vector_index(self):
        embedder = OllamaEmbedding("quentinz/bge-large-zh-v1.5")
        data = [
            "腾讯的合伙人有字节跳动",
            "谷歌和微软是竞争关系",
            "美团的合伙人有字节跳动",
        ]
        data_embedding = [embedder.get_text_embedding(d) for d in data]
        index = FaissVectorIndex(1024)
        index.add(data_embedding, data)
        query = "腾讯的合伙人有哪些？"
        query_vector = embedder.get_text_embedding(query)
        results = index.search(query_vector, 2)
        pprint(results)
