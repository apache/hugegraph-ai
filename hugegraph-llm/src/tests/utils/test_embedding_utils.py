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

import asyncio
import threading
import time
import unittest
from typing import List

import pytest

from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.utils.embedding_utils import get_embeddings_parallel

pytestmark = pytest.mark.unit


class _TrackingEmbedding(BaseEmbedding):
    """Minimal embedding that records batch sizes and tracks in-flight calls."""

    def __init__(self, batch_delay: float = 0.0) -> None:
        self.batch_sizes: List[int] = []
        self.async_batch_sizes: List[int] = []
        self.batch_delay = batch_delay
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

    def get_text_embedding(self, text: str) -> List[float]:
        return [float(text)]

    def get_embedding_dim(self) -> int:
        return 1

    def _record(self, texts: List[str]) -> List[List[float]]:
        with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self.batch_sizes.append(len(texts))
        try:
            time.sleep(self.batch_delay)
            return [[float(text)] for text in texts]
        finally:
            with self._lock:
                self.in_flight -= 1

    def get_texts_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        return self._record(texts)

    async def async_get_texts_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        self.async_batch_sizes.append(len(texts))
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._record, texts)


class TestGetEmbeddingsParallel(unittest.TestCase):
    def test_preserves_order_across_batches(self):
        embedding = _TrackingEmbedding()
        texts = [str(i) for i in range(1200)]

        embeddings = asyncio.run(get_embeddings_parallel(embedding, texts))

        self.assertEqual(embeddings, [[float(i)] for i in range(1200)])
        self.assertEqual(embedding.batch_sizes, [500, 500, 200])

    def test_bounds_concurrent_batches(self):
        embedding = _TrackingEmbedding(batch_delay=0.01)
        texts = [str(i) for i in range(15000)]  # 30 batches

        embeddings = asyncio.run(get_embeddings_parallel(embedding, texts))

        self.assertEqual(len(embeddings), 15000)
        self.assertGreater(embedding.max_in_flight, 1)  # batches overlap in time
        self.assertLessEqual(embedding.max_in_flight, 10)  # but stay bounded

    def test_handles_empty_input(self):
        embedding = _TrackingEmbedding()

        self.assertEqual(asyncio.run(get_embeddings_parallel(embedding, [])), [])
        self.assertEqual(embedding.batch_sizes, [])

    def test_propagates_batch_errors(self):
        class _FailingEmbedding(_TrackingEmbedding):
            def get_texts_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
                raise RuntimeError("embedding failed")

            async def async_get_texts_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
                raise RuntimeError("embedding failed")

        with self.assertRaisesRegex(RuntimeError, "embedding failed"):
            asyncio.run(get_embeddings_parallel(_FailingEmbedding(), ["1"]))

    def test_fetch_avoids_loop_bound_async_clients(self):
        # Callers run this helper on a fresh event loop per index update (asyncio.run),
        # while an instance-owned async client keeps its pooled connections bound to the
        # loop that first used them. The fetch must drive the loop-agnostic sync client.
        embedding = _TrackingEmbedding()

        self.assertEqual(asyncio.run(get_embeddings_parallel(embedding, ["1", "2"])), [[1.0], [2.0]])
        self.assertEqual(embedding.batch_sizes, [2])
        self.assertEqual(embedding.async_batch_sizes, [])


if __name__ == "__main__":
    unittest.main()
