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

from typing import Any, AsyncGenerator, Callable, Dict, Generator, List, Optional

import openai
import tiktoken
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, OpenAI, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from hugegraph_llm.models.llms.base import BaseLLM, LLMOutputTruncatedError
from hugegraph_llm.utils.log import log


class OpenAIClient(BaseLLM):
    """Wrapper for OpenAI Client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model_name: str = "gpt-4.1-mini",
        max_tokens: Optional[int] = 8092,
        temperature: float = 0.01,
        raise_on_truncation: bool = False,
    ) -> None:
        api_key = api_key or ""
        self.client = OpenAI(api_key=api_key, base_url=api_base)
        self.aclient = AsyncOpenAI(api_key=api_key, base_url=api_base)
        self.model = model_name
        self.max_tokens = max_tokens
        self.temperature = temperature
        # Reviewed extraction also needs provider errors instead of legacy error text.
        self.raise_on_truncation = raise_on_truncation

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError, APITimeoutError)),
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
            completions = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                **({"max_tokens": self.max_tokens} if self.max_tokens is not None else {}),
                messages=messages,
            )
            if not completions.choices:
                raise RuntimeError(f"Empty choices in LLM response: {str(completions)[:200]}")
            if completions.usage:
                log.info("Token usage: %s", completions.usage.model_dump_json())
            if self.raise_on_truncation and completions.choices[0].finish_reason == "length":
                raise LLMOutputTruncatedError()
            return completions.choices[0].message.content
        # catch context length / do not retry
        except openai.BadRequestError as e:
            if self.raise_on_truncation:
                raise
            log.critical("Fatal: %s", e)
            return str(f"Error: {e}")
        # catch authorization errors / do not retry
        except openai.AuthenticationError:
            if self.raise_on_truncation:
                raise
            log.critical("The provided OpenAI API key is invalid")
            return "Error: The provided OpenAI API key is invalid"
        except LLMOutputTruncatedError:
            raise
        except Exception as e:
            log.error("Retrying LLM call %s", e)
            raise e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError, APITimeoutError)),
    )
    async def agenerate(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
    ) -> str:
        """Generate a response to the query messages/prompt."""
        if messages is None:
            assert prompt is not None, "Messages or prompt must be provided."
            messages = [{"role": "user", "content": prompt}]
        try:
            completions = await self.aclient.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                **({"max_tokens": self.max_tokens} if self.max_tokens is not None else {}),
                messages=messages,
            )
            if not completions.choices:
                raise RuntimeError(f"Empty choices in LLM response: {str(completions)[:200]}")
            if completions.usage:
                log.info("Token usage: %s", completions.usage.model_dump_json())
            if self.raise_on_truncation and completions.choices[0].finish_reason == "length":
                raise LLMOutputTruncatedError()
            return completions.choices[0].message.content
        # catch context length / do not retry
        except openai.BadRequestError as e:
            if self.raise_on_truncation:
                raise
            log.critical("Fatal: %s", e)
            return str(f"Error: {e}")
        # catch authorization errors / do not retry
        except openai.AuthenticationError:
            if self.raise_on_truncation:
                raise
            log.critical("The provided OpenAI API key is invalid")
            return "Error: The provided OpenAI API key is invalid"
        except LLMOutputTruncatedError:
            raise
        except Exception as e:
            log.error("Retrying LLM call %s", e)
            raise e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError, APITimeoutError)),
    )
    def generate_streaming(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
        on_token_callback: Optional[Callable[[str], None]] = None,
    ) -> Generator[str, None, None]:
        """Generate a response to the query messages/prompt in streaming mode.

        Yields:
            Accumulated response string after each new token.
        """
        if messages is None:
            assert prompt is not None, "Messages or prompt must be provided."
            messages = [{"role": "user", "content": prompt}]

        try:
            completions = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                **({"max_tokens": self.max_tokens} if self.max_tokens is not None else {}),
                messages=messages,
                stream=True,
            )

            for chunk in completions:
                if not chunk.choices:
                    log.debug("Received empty choices in streaming chunk: %s", chunk)
                    continue
                if self.raise_on_truncation and chunk.choices[0].finish_reason == "length":
                    raise LLMOutputTruncatedError()
                delta = chunk.choices[0].delta
                if delta.content:
                    token = delta.content
                    if on_token_callback:
                        on_token_callback(token)
                    yield token

        except openai.BadRequestError as e:
            if self.raise_on_truncation:
                raise
            log.critical("Fatal: %s", e)
            yield str(f"Error: {e}")
        except openai.AuthenticationError:
            if self.raise_on_truncation:
                raise
            log.critical("The provided API key is invalid")
            yield "Error: The provided API key is invalid"
        except Exception as e:
            log.error("Error in streaming: %s", e)
            raise e

    async def agenerate_streaming(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
        on_token_callback: Optional[Callable] = None,
    ) -> AsyncGenerator[str, None]:
        """Comment"""
        if messages is None:
            assert prompt is not None, "Messages or prompt must be provided."
            messages = [{"role": "user", "content": prompt}]

        try:
            completions = await self.aclient.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                **({"max_tokens": self.max_tokens} if self.max_tokens is not None else {}),
                messages=messages,
                stream=True,
            )
            async for chunk in completions:
                if not chunk.choices:
                    log.debug("Received empty choices in streaming chunk: %s", chunk)
                    continue
                if self.raise_on_truncation and chunk.choices[0].finish_reason == "length":
                    raise LLMOutputTruncatedError()
                delta = chunk.choices[0].delta
                if delta.content:
                    token = delta.content
                    if on_token_callback:
                        on_token_callback(token)
                    yield token
            # TODO: log.info("Token usage: %s", completions.usage.model_dump_json())
        # catch context length / do not retry
        except openai.BadRequestError as e:
            if self.raise_on_truncation:
                raise
            log.critical("Fatal: %s", e)
            yield str(f"Error: {e}")
        # catch authorization errors / do not retry
        except openai.AuthenticationError:
            if self.raise_on_truncation:
                raise
            log.critical("The provided OpenAI API key is invalid")
            yield "Error: The provided OpenAI API key is invalid"
        except LLMOutputTruncatedError:
            raise
        except Exception as e:
            log.error("Retrying LLM call %s", e)
            raise e

    def num_tokens_from_string(self, string: str) -> int:
        """Get token count from a string."""
        encoding = tiktoken.encoding_for_model(self.model)
        num_tokens = len(encoding.encode(string))
        return num_tokens

    def max_allowed_token_length(self) -> int:
        """Get max-allowed token length"""
        # TODO: list all models and their max tokens from api
        return 8192

    def get_llm_type(self) -> str:
        return "openai"
