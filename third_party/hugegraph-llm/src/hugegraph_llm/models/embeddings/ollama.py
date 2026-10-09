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


from typing import List

import ollama

from .base import BaseEmbedding


class OllamaEmbedding(BaseEmbedding):
    def __init__(
        self,
        model: str = "quentinz/bge-large-zh-v1.5",
        embedding_dimension: int = 1024,
        host: str = "127.0.0.1",
        port: int = 11434,
        **kwargs,
    ):
        self.model = model
        self.client = ollama.Client(host=f"http://{host}:{port}", **kwargs)
        self.async_client = ollama.AsyncClient(host=f"http://{host}:{port}", **kwargs)
        self.embedding_dimension = embedding_dimension

    def get_embedding_dim(
        self,
    ) -> int:
        return self.embedding_dimension

    def get_text_embedding(self, text: str) -> List[float]:
        """Comment"""
        return list(self.client.embed(model=self.model, input=[text])["embeddings"][0])

    def get_texts_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Get embeddings for multiple texts with automatic batch splitting.

        This method efficiently processes multiple texts by splitting them into
        smaller batches to respect API rate limits and batch size constraints.

        Parameters
        ----------
        texts : List[str]
            A list of text strings to be embedded.
        batch_size : int, optional
            Maximum number of texts to process in a single API call (default: 32).

        Returns
        -------
        List[List[float]]
            A list of embedding vectors, where each vector is a list of floats.
            The order of embeddings matches the order of input texts.
        """
        if not hasattr(self.client, "embed"):
            error_message = (
                "The required 'embed' method was not found on the Ollama client. "
                "Please ensure your ollama library is up-to-date and supports batch embedding. "
            )
            raise AttributeError(error_message)

        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = self.client.embed(model=self.model, input=batch)
            all_embeddings.extend(self._get_embeddings_from_response(response))
        return all_embeddings

    def _get_embeddings_from_response(self, response) -> List[List[float]]:
        if "embeddings" not in response:
            raise ValueError("Ollama embedding response missing 'embeddings'.")
        embeddings = response["embeddings"]
        if not embeddings:
            raise ValueError("Ollama embedding response returned no embeddings.")
        return [list(inner_sequence) for inner_sequence in embeddings]

    async def async_get_text_embedding(self, text: str) -> List[float]:
        """Get embedding for a single text asynchronously."""
        if not hasattr(self.async_client, "embed"):
            error_message = (
                "The required 'embed' method was not found on the Ollama async client. "
                "Please ensure your ollama library is up-to-date and supports batch embedding. "
            )
            raise AttributeError(error_message)

        response = await self.async_client.embed(model=self.model, input=[text])
        return self._get_embeddings_from_response(response)[0]

    async def async_get_texts_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        if not hasattr(self.async_client, "embed"):
            error_message = (
                "The required 'embed' method was not found on the Ollama async client. "
                "Please ensure your ollama library is up-to-date and supports batch embedding. "
            )
            raise AttributeError(error_message)

        results: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = await self.async_client.embed(model=self.model, input=batch)
            results.extend(self._get_embeddings_from_response(response))
        return results
