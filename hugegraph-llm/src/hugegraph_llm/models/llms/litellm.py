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

from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

import tiktoken
from litellm import acompletion, completion
from litellm.exceptions import APIError, BudgetExceededError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from hugegraph_llm.models.llms.base import BaseLLM, LLMOutputTruncatedError
from hugegraph_llm.utils.log import log


class LiteLLMClient(BaseLLM):
    """Wrapper for LiteLLM Client that supports multiple LLM providers."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model_name: str = "openai/gpt-4.1-mini",  # Can be any model supported by LiteLLM
        max_tokens: Optional[int] = 8192,
        temperature: float = 0.01,
        raise_on_truncation: bool = False,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base
        self.model = model_name
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.raise_on_truncation = raise_on_truncation

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=5),
        retry=retry_if_exception_type((RateLimitError, APIError)),
        reraise=True,
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
            response = completion(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                **({"max_tokens": self.max_tokens} if self.max_tokens is not None else {}),
                api_key=self.api_key,
                base_url=self.api_base,
            )
            log.info("Token usage: %s", response.usage)
            if self.raise_on_truncation and response.choices[0].finish_reason == "length":
                raise LLMOutputTruncatedError()
            return response.choices[0].message.content
        except (RateLimitError, BudgetExceededError, APIError) as e:
            log.error("LiteLLM call failed (%s)", type(e).__name__)
            raise

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=5),
        retry=retry_if_exception_type((RateLimitError, APIError)),
        reraise=True,
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
            response = await acompletion(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                **({"max_tokens": self.max_tokens} if self.max_tokens is not None else {}),
                api_key=self.api_key,
                base_url=self.api_base,
            )
            log.info("Token usage: %s", response.usage)
            if self.raise_on_truncation and response.choices[0].finish_reason == "length":
                raise LLMOutputTruncatedError()
            return response.choices[0].message.content
        except (RateLimitError, BudgetExceededError, APIError) as e:
            log.error("Async LiteLLM call failed (%s)", type(e).__name__)
            raise

    def generate_streaming(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
        on_token_callback: Callable = None,
    ) -> str:
        """Generate a response to the query messages/prompt in streaming mode."""
        if messages is None:
            assert prompt is not None, "Messages or prompt must be provided."
            messages = [{"role": "user", "content": prompt}]
        try:
            response = completion(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                **({"max_tokens": self.max_tokens} if self.max_tokens is not None else {}),
                api_key=self.api_key,
                base_url=self.api_base,
                stream=True,
            )
            result = ""
            for chunk in response:
                if not chunk.choices:
                    log.debug("Received empty choices in streaming chunk")
                    continue
                if self.raise_on_truncation and chunk.choices[0].finish_reason == "length":
                    raise LLMOutputTruncatedError()
                if chunk.choices[0].delta.content:
                    result += chunk.choices[0].delta.content
                if on_token_callback:
                    on_token_callback(chunk)
            return result
        except (RateLimitError, BudgetExceededError, APIError) as e:
            log.error("Streaming LiteLLM call failed (%s)", type(e).__name__)
            raise

    async def agenerate_streaming(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
        on_token_callback: Optional[Callable] = None,
    ) -> AsyncGenerator[str, None]:
        """Generate a response to the query messages/prompt in async streaming mode."""
        if messages is None:
            assert prompt is not None, "Messages or prompt must be provided."
            messages = [{"role": "user", "content": prompt}]
        try:
            response = await acompletion(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                **({"max_tokens": self.max_tokens} if self.max_tokens is not None else {}),
                api_key=self.api_key,
                base_url=self.api_base,
                stream=True,
            )
            async for chunk in response:
                if not chunk.choices:
                    log.debug("Received empty choices in streaming chunk")
                    continue
                if self.raise_on_truncation and chunk.choices[0].finish_reason == "length":
                    raise LLMOutputTruncatedError()
                if chunk.choices[0].delta.content:
                    if on_token_callback:
                        on_token_callback(chunk)
                    yield chunk.choices[0].delta.content
        except (RateLimitError, BudgetExceededError, APIError) as e:
            log.error("Async streaming LiteLLM call failed (%s)", type(e).__name__)
            raise

    def num_tokens_from_string(self, string: str) -> int:
        """Get token count from string."""
        try:
            encoding = tiktoken.encoding_for_model(self.model)
            num_tokens = len(encoding.encode(string))
            return num_tokens
        except (ValueError, TypeError) as _:  # Handle unused variable
            # Fallback for models not supported by tiktoken
            # Rough estimate: 1 token ≈ 4 characters
            return len(string) // 4

    def max_allowed_token_length(self) -> int:
        """Get max-allowed token length based on the model."""
        return 4096  # Default to 4096 if model not found

    def get_llm_type(self) -> str:
        return "litellm"
