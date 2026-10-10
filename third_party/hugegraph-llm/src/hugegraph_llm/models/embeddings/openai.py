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


from typing import List, Optional

from openai import AsyncOpenAI, OpenAI

from hugegraph_llm.models.embeddings.base import BaseEmbedding


class OpenAIEmbedding(BaseEmbedding):
    def __init__(
        self,
        embedding_dimension: int = 1536,
        model_name: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
    ):
        api_key = api_key or ""
        self.client = OpenAI(api_key=api_key, base_url=api_base)
        self.aclient = AsyncOpenAI(api_key=api_key, base_url=api_base)
        self.model = model_name
        self.embedding_dimension = embedding_dimension

    def get_embedding_dim(
        self,
    ) -> int:
        return self.embedding_dimension

    def get_text_embedding(self, text: str) -> List[float]:
        """Comment"""
        response = self.client.embeddings.create(input=text, model=self.model)
        return response.data[0].embedding

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
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = self.client.embeddings.create(input=batch, model=self.model)
            all_embeddings.extend([data.embedding for data in response.data])
        return all_embeddings

    async def async_get_texts_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Get embeddings for multiple texts with automatic batch splitting (async).

        This method should efficiently process multiple texts at once by leveraging
        the embedding model's batching capabilities, which is typically more efficient
        than processing texts individually.

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
            The order of embeddings should match the order of input texts.
        """
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = await self.aclient.embeddings.create(input=batch, model=self.model)
            all_embeddings.extend([data.embedding for data in response.data])
        return all_embeddings

    async def async_get_text_embedding(self, text: str) -> List[float]:
        response = await self.aclient.embeddings.create(input=[text], model=self.model)
        return response.data[0].embedding
