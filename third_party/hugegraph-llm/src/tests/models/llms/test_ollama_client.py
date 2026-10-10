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
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import ollama
import pytest
from tenacity import RetryError, wait_none

from hugegraph_llm.models.llms.ollama import OllamaClient

pytestmark = pytest.mark.contract

# Minimal dict response matching the structure ollama.Client.chat() returns
_MOCK_RESPONSE = {
    "prompt_eval_count": 10,
    "eval_count": 5,
    "message": {"content": "Paris"},
}


class TestOllamaClientRetryPolicy(unittest.TestCase):
    """Mock-based contract tests for the Tenacity retry policy in OllamaClient.

    These tests do not require a running Ollama service.  They verify:
      - retryable exceptions (ollama.ResponseError, httpx.ConnectError,
        httpx.TimeoutException) trigger the configured number of attempts;
      - non-retryable exceptions (e.g. ValueError) are NOT retried;
      - a transient failure followed by success resolves correctly.
    """

    def setUp(self):
        # Zero out exponential wait so retry tests complete in milliseconds.
        # Tenacity exposes the Retrying object on the decorated function via
        # the .retry attribute; its .wait field is mutable.
        self._orig_generate_wait = OllamaClient.generate.retry.wait
        self._orig_agenerate_wait = OllamaClient.agenerate.retry.wait
        OllamaClient.generate.retry.wait = wait_none()
        OllamaClient.agenerate.retry.wait = wait_none()

    def tearDown(self):
        OllamaClient.generate.retry.wait = self._orig_generate_wait
        OllamaClient.agenerate.retry.wait = self._orig_agenerate_wait

    # ------------------------------------------------------------------ #
    # generate()                                                           #
    # ------------------------------------------------------------------ #

    @patch("hugegraph_llm.models.llms.ollama.ollama.Client")
    def test_generate_returns_content_on_success(self, mock_client_class):
        """Happy path: generate() returns the message content string."""
        mock_client = MagicMock()
        mock_client.chat.return_value = _MOCK_RESPONSE
        mock_client_class.return_value = mock_client

        result = OllamaClient(model="llama3").generate(prompt="hello")

        self.assertEqual(result, "Paris")
        mock_client.chat.assert_called_once()

    @patch("hugegraph_llm.models.llms.ollama.ollama.Client")
    def test_generate_retries_response_error_exhausts_all_attempts(self, mock_client_class):
        """ollama.ResponseError is retryable; all 3 attempts are made."""
        mock_client = MagicMock()
        mock_client.chat.side_effect = ollama.ResponseError("model not found")
        mock_client_class.return_value = mock_client

        with self.assertRaises(RetryError):
            OllamaClient(model="llama3").generate(prompt="hello")

        self.assertEqual(mock_client.chat.call_count, 3)

    @patch("hugegraph_llm.models.llms.ollama.ollama.Client")
    def test_generate_retries_connect_error_exhausts_all_attempts(self, mock_client_class):
        """httpx.ConnectError is retryable; all 3 attempts are made."""
        mock_client = MagicMock()
        mock_client.chat.side_effect = httpx.ConnectError("connection refused")
        mock_client_class.return_value = mock_client

        with self.assertRaises(RetryError):
            OllamaClient(model="llama3").generate(prompt="hello")

        self.assertEqual(mock_client.chat.call_count, 3)

    @patch("hugegraph_llm.models.llms.ollama.ollama.Client")
    def test_generate_does_not_retry_non_retriable_error(self, mock_client_class):
        """ValueError is not in the retry predicate; only 1 attempt is made."""
        mock_client = MagicMock()
        mock_client.chat.side_effect = ValueError("unexpected")
        mock_client_class.return_value = mock_client

        with self.assertRaises(ValueError):
            OllamaClient(model="llama3").generate(prompt="hello")

        mock_client.chat.assert_called_once()

    @patch("hugegraph_llm.models.llms.ollama.ollama.Client")
    def test_generate_succeeds_on_second_attempt(self, mock_client_class):
        """Transient ResponseError on attempt 1, success on attempt 2."""
        mock_client = MagicMock()
        mock_client.chat.side_effect = [
            ollama.ResponseError("transient"),
            _MOCK_RESPONSE,
        ]
        mock_client_class.return_value = mock_client

        result = OllamaClient(model="llama3").generate(prompt="hello")

        self.assertEqual(result, "Paris")
        self.assertEqual(mock_client.chat.call_count, 2)

    # ------------------------------------------------------------------ #
    # agenerate()                                                          #
    # ------------------------------------------------------------------ #

    @patch("hugegraph_llm.models.llms.ollama.ollama.AsyncClient")
    def test_agenerate_retries_connect_error_exhausts_all_attempts(self, mock_async_client_class):
        """httpx.ConnectError is retryable in agenerate(); all 3 attempts made."""
        mock_async_client = MagicMock()
        mock_async_client.chat = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_async_client_class.return_value = mock_async_client

        async def run():
            with self.assertRaises(RetryError):
                await OllamaClient(model="llama3").agenerate(prompt="hello")
            self.assertEqual(mock_async_client.chat.call_count, 3)

        asyncio.run(run())

    @patch("hugegraph_llm.models.llms.ollama.ollama.AsyncClient")
    def test_agenerate_retries_timeout_exception_exhausts_all_attempts(self, mock_async_client_class):
        """httpx.TimeoutException is retryable in agenerate(); all 3 attempts made."""
        mock_async_client = MagicMock()
        mock_async_client.chat = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_async_client_class.return_value = mock_async_client

        async def run():
            with self.assertRaises(RetryError):
                await OllamaClient(model="llama3").agenerate(prompt="hello")
            self.assertEqual(mock_async_client.chat.call_count, 3)

        asyncio.run(run())

    @patch("hugegraph_llm.models.llms.ollama.ollama.AsyncClient")
    def test_agenerate_does_not_retry_non_retriable_error(self, mock_async_client_class):
        """ValueError is not retryable in agenerate(); only 1 attempt is made."""
        mock_async_client = MagicMock()
        mock_async_client.chat = AsyncMock(side_effect=ValueError("unexpected"))
        mock_async_client_class.return_value = mock_async_client

        async def run():
            with self.assertRaises(ValueError):
                await OllamaClient(model="llama3").agenerate(prompt="hello")
            mock_async_client.chat.assert_called_once()

        asyncio.run(run())

    @patch("hugegraph_llm.models.llms.ollama.ollama.AsyncClient")
    def test_agenerate_succeeds_on_second_attempt(self, mock_async_client_class):
        """Transient ResponseError on attempt 1, success on attempt 2."""
        mock_async_client = MagicMock()
        mock_async_client.chat = AsyncMock(side_effect=[ollama.ResponseError("transient"), _MOCK_RESPONSE])
        mock_async_client_class.return_value = mock_async_client

        async def run():
            result = await OllamaClient(model="llama3").agenerate(prompt="hello")
            self.assertEqual(result, "Paris")
            self.assertEqual(mock_async_client.chat.call_count, 2)

        asyncio.run(run())


class TestOllamaClientExternalService(unittest.TestCase):
    """Integration tests that require a live Ollama service.

    Skipped in CI via SKIP_EXTERNAL_SERVICES=true (set in conftest.py).
    """

    def setUp(self):
        self.skip_external = os.getenv("SKIP_EXTERNAL_SERVICES", "false").lower() == "true"

    @unittest.skipIf(
        os.getenv("SKIP_EXTERNAL_SERVICES", "false").lower() == "true",
        "Skipping external service tests",
    )
    def test_generate(self):
        ollama_client = OllamaClient(model="llama3:8b-instruct-fp16")
        response = ollama_client.generate(prompt="What is the capital of France?")
        print(response)

    @unittest.skipIf(
        os.getenv("SKIP_EXTERNAL_SERVICES", "false").lower() == "true",
        "Skipping external service tests",
    )
    def test_stream_generate(self):
        ollama_client = OllamaClient(model="llama3:8b-instruct-fp16")

        def on_token_callback(chunk):
            print(chunk, end="", flush=True)

        ollama_client.generate_streaming(
            prompt="What is the capital of France?",
            on_token_callback=on_token_callback,
        )


if __name__ == "__main__":
    unittest.main()
