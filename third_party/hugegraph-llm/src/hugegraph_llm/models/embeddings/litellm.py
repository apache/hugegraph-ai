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

from litellm import APIConnectionError, APIError, RateLimitError, aembedding, embedding
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.utils.log import log


class LiteLLMEmbedding(BaseEmbedding):
    """Wrapper for LiteLLM Embedding that supports multiple LLM providers."""

    def __init__(
        self,
        embedding_dimension,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model_name: str = "openai/text-embedding-3-small",  # Can be any embedding model supported by LiteLLM
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base
        self.model = model_name
        self.embedding_dimension = embedding_dimension

    def get_embedding_dim(
        self,
    ) -> int:
        return self.embedding_dimension

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError, APIError)),
    )
    def get_text_embedding(self, text: str) -> List[float]:
        """Get embedding for a single text."""
        try:
            response = embedding(
                model=self.model,
                input=text,
                api_key=self.api_key,
                api_base=self.api_base,
            )
            log.info("Token usage: %s", response.usage)
            return response.data[0]["embedding"]
        except (RateLimitError, APIConnectionError, APIError) as e:
            log.error("Error in LiteLLM embedding call: %s", e)
            raise

    def get_texts_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Get embeddings for multiple texts with automatic batch splitting.

        Parameters
        ----------
        texts : List[str]
            A list of text strings to be embedded.
        batch_size : int, optional
            Maximum number of texts to process in a single API call (default: 32).

        Returns
        -------
        List[List[float]]
            A list of embedding vectors.
        """
        all_embeddings = []
        try:
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                response = embedding(
                    model=self.model,
                    input=batch,
                    api_key=self.api_key,
                    api_base=self.api_base,
                )
                log.info("Token usage: %s", response.usage)
                all_embeddings.extend([data["embedding"] for data in response.data])
            return all_embeddings
        except (RateLimitError, APIConnectionError, APIError) as e:
            log.error("Error in LiteLLM batch embedding call: %s", e)
            raise

    async def async_get_text_embedding(self, text: str) -> List[float]:
        """Get embedding for a single text asynchronously."""
        try:
            response = await aembedding(
                model=self.model,
                input=text,
                api_key=self.api_key,
                api_base=self.api_base,
            )
            log.info("Token usage: %s", response.usage)
            return response.data[0]["embedding"]
        except (RateLimitError, APIConnectionError, APIError) as e:
            log.error("Error in async LiteLLM embedding call: %s", e)
            raise

    async def async_get_texts_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Get embeddings for multiple texts asynchronously with automatic batch splitting.

        Parameters
        ----------
        texts : List[str]
            A list of text strings to be embedded.
        batch_size : int, optional
            Maximum number of texts to process in a single API call (default: 32).

        Returns
        -------
        List[List[float]]
            A list of embedding vectors.
        """
        all_embeddings = []
        try:
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                response = await aembedding(
                    model=self.model,
                    input=batch,
                    api_key=self.api_key,
                    api_base=self.api_base,
                )
                log.info("Token usage: %s", response.usage)
                all_embeddings.extend([data["embedding"] for data in response.data])
            return all_embeddings
        except (RateLimitError, APIConnectionError, APIError) as e:
            log.error("Error in async LiteLLM embedding call: %s", e)
            raise
