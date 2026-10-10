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


import json
from typing import Any, AsyncGenerator, Callable, Dict, Generator, List, Optional

import httpx
import ollama
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.utils.log import log


class OllamaClient(BaseLLM):
    """LLM wrapper should take in a prompt and return a string."""

    def __init__(self, model: str, host: str = "127.0.0.1", port: int = 11434, **kwargs):
        self.model = model
        self.client = ollama.Client(host=f"http://{host}:{port}", **kwargs)
        self.async_client = ollama.AsyncClient(host=f"http://{host}:{port}", **kwargs)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((ollama.ResponseError, httpx.ConnectError, httpx.TimeoutException)),
    )
    def generate(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
    ) -> str:
        """Generate a response to the query messages/prompt."""
        if messages is None:
            assert prompt is not None, "Messages or prompt must be provided."
            messages = [{"role": "user", "content": prompt}]
        try:
            response = self.client.chat(
                model=self.model,
                messages=messages,
            )
            usage = {
                "prompt_tokens": response["prompt_eval_count"],
                "completion_tokens": response["eval_count"],
                "total_tokens": response["prompt_eval_count"] + response["eval_count"],
            }
            log.info("Token usage: %s", json.dumps(usage))
            return response["message"]["content"]
        except (ollama.ResponseError, httpx.ConnectError, httpx.TimeoutException) as e:
            log.error("Retrying LLM call %s", e)
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((ollama.ResponseError, httpx.ConnectError, httpx.TimeoutException)),
    )
    async def agenerate(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
    ) -> str:
        """Generate a response to the query messages/prompt asynchronously."""
        if messages is None:
            assert prompt is not None, "Messages or prompt must be provided."
            messages = [{"role": "user", "content": prompt}]
        try:
            response = await self.async_client.chat(
                model=self.model,
                messages=messages,
            )
            usage = {
                "prompt_tokens": response["prompt_eval_count"],
                "completion_tokens": response["eval_count"],
                "total_tokens": response["prompt_eval_count"] + response["eval_count"],
            }
            log.info("Token usage: %s", json.dumps(usage))
            return response["message"]["content"]
        except (ollama.ResponseError, httpx.ConnectError, httpx.TimeoutException) as e:
            log.error("Retrying LLM call %s", e)
            raise

    def generate_streaming(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
        on_token_callback: Optional[Callable] = None,
    ) -> Generator[str, None, None]:
        """Stream response tokens one by one."""
        if messages is None:
            assert prompt is not None, "Messages or prompt must be provided."
            messages = [{"role": "user", "content": prompt}]

        for chunk in self.client.chat(model=self.model, messages=messages, stream=True):
            if not chunk["message"]:
                log.debug("Received empty chunk['message'] in streaming chunk: %s", chunk)
                continue
            token = chunk["message"]["content"]
            if on_token_callback:
                on_token_callback(token)
            yield token

    async def agenerate_streaming(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
        on_token_callback: Optional[Callable] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens one by one."""
        if messages is None:
            assert prompt is not None, "Messages or prompt must be provided."
            messages = [{"role": "user", "content": prompt}]

        try:
            async_generator = await self.async_client.chat(model=self.model, messages=messages, stream=True)
            async for chunk in async_generator:
                token = chunk.get("message", {}).get("content", "")
                if on_token_callback:
                    on_token_callback(token)
                yield token
        except (ollama.ResponseError, httpx.ConnectError, httpx.TimeoutException) as e:
            log.error("Error in agenerate_streaming: %s", e)
            raise

    def num_tokens_from_string(
        self,
        string: str,
    ) -> int:
        """Given a string returns the number of tokens the given string consists of"""
        return len(string)

    def max_allowed_token_length(
        self,
    ) -> int:
        """Returns the maximum number of tokens the LLM can handle"""
        return 4096

    def get_llm_type(self) -> str:
        """Returns the type of the LLM"""
        return "ollama/local"
