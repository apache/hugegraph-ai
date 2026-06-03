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
import unittest
from unittest.mock import AsyncMock, MagicMock

import pytest

from hugegraph_llm.models.embeddings.base import SimilarityMode
from hugegraph_llm.models.embeddings.ollama import OllamaEmbedding


class TestOllamaEmbedding(unittest.TestCase):
    def setUp(self):
        self.skip_external = os.getenv("SKIP_EXTERNAL_SERVICES", "false").lower() == "true"

    @pytest.mark.external
    @unittest.skipIf(os.getenv("SKIP_EXTERNAL_SERVICES", "false").lower() == "true", "Skipping external service tests")
    def test_get_text_embedding(self):
        ollama_embedding = OllamaEmbedding(model_name="quentinz/bge-large-zh-v1.5")
        embedding = ollama_embedding.get_text_embedding("hello world")
        print(embedding)

    @pytest.mark.external
    @unittest.skipIf(os.getenv("SKIP_EXTERNAL_SERVICES", "false").lower() == "true", "Skipping external service tests")
    def test_get_cosine_similarity(self):
        ollama_embedding = OllamaEmbedding(model_name="quentinz/bge-large-zh-v1.5")
        embedding1 = ollama_embedding.get_text_embedding("hello world")
        embedding2 = ollama_embedding.get_text_embedding("bye world")
        similarity = OllamaEmbedding.similarity(embedding1, embedding2, SimilarityMode.DEFAULT)
        print(similarity)

    @pytest.mark.contract
    def test_async_get_texts_embeddings_preserves_batch_order(self):
        ollama_embedding = OllamaEmbedding(model="test-model")
        ollama_embedding.async_client = AsyncMock()
        ollama_embedding.async_client.embed.side_effect = [
            {"embeddings": [[1.0], [2.0]]},
            {"embeddings": [[3.0]]},
        ]

        async def run_async_test():
            result = await ollama_embedding.async_get_texts_embeddings(["a", "b", "c"], batch_size=2)
            self.assertEqual(result, [[1.0], [2.0], [3.0]])
            self.assertEqual(ollama_embedding.async_client.embed.call_count, 2)
            ollama_embedding.async_client.embed.assert_any_call(model="test-model", input=["a", "b"])
            ollama_embedding.async_client.embed.assert_any_call(model="test-model", input=["c"])

        import asyncio

        asyncio.run(run_async_test())

    @pytest.mark.contract
    def test_async_get_text_embedding_requires_embeddings_key(self):
        ollama_embedding = OllamaEmbedding(model="test-model")
        ollama_embedding.async_client = AsyncMock()
        ollama_embedding.async_client.embed.return_value = {}

        async def run_async_test():
            with self.assertRaisesRegex(ValueError, "missing 'embeddings'"):
                await ollama_embedding.async_get_text_embedding("a")

        import asyncio

        asyncio.run(run_async_test())

    @pytest.mark.contract
    def test_get_texts_embeddings_requires_embeddings_key(self):
        ollama_embedding = OllamaEmbedding(model="test-model")
        ollama_embedding.client = MagicMock()
        ollama_embedding.client.embed.return_value = {}

        with self.assertRaisesRegex(ValueError, "missing 'embeddings'"):
            ollama_embedding.get_texts_embeddings(["a"])

    @pytest.mark.contract
    def test_get_texts_embeddings_requires_embed_method(self):
        ollama_embedding = OllamaEmbedding(model="test-model")
        ollama_embedding.client = object()

        with self.assertRaisesRegex(AttributeError, "required 'embed' method"):
            ollama_embedding.get_texts_embeddings(["a"])

    @pytest.mark.contract
    def test_get_texts_embeddings_requires_non_empty_embeddings(self):
        ollama_embedding = OllamaEmbedding(model="test-model")
        ollama_embedding.client = MagicMock()
        ollama_embedding.client.embed.return_value = {"embeddings": []}

        with self.assertRaisesRegex(ValueError, "returned no embeddings"):
            ollama_embedding.get_texts_embeddings(["a"])

    @pytest.mark.contract
    def test_async_get_text_embedding_requires_non_empty_embeddings(self):
        ollama_embedding = OllamaEmbedding(model="test-model")
        ollama_embedding.async_client = AsyncMock()
        ollama_embedding.async_client.embed.return_value = {"embeddings": []}

        async def run_async_test():
            with self.assertRaisesRegex(ValueError, "returned no embeddings"):
                await ollama_embedding.async_get_text_embedding("a")

        import asyncio

        asyncio.run(run_async_test())

    @pytest.mark.contract
    def test_async_get_text_embedding_requires_embed_method(self):
        ollama_embedding = OllamaEmbedding(model="test-model")
        ollama_embedding.async_client = object()

        async def run_async_test():
            with self.assertRaisesRegex(AttributeError, "required 'embed' method"):
                await ollama_embedding.async_get_text_embedding("a")

        import asyncio

        asyncio.run(run_async_test())
