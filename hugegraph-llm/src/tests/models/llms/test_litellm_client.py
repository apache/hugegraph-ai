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
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from litellm.exceptions import APIError, BudgetExceededError

from hugegraph_llm.models.llms.litellm import LiteLLMClient

pytestmark = pytest.mark.contract


class TestLiteLLMClient(unittest.TestCase):
    def test_generate_returns_message_content(self):
        client = LiteLLMClient(model_name="openai/gpt-4.1-mini")
        response = MagicMock()
        response.usage = {"prompt_tokens": 1}
        response.choices = [MagicMock(message=MagicMock(content="hello"))]

        with patch("hugegraph_llm.models.llms.litellm.completion", return_value=response) as mock_completion:
            result = client.generate(prompt="hello")

        self.assertEqual(result, "hello")
        mock_completion.assert_called_once()

    def test_generate_malformed_sdk_response_raises_attribute_error(self):
        client = LiteLLMClient(model_name="openai/gpt-4.1-mini")

        with patch("hugegraph_llm.models.llms.litellm.completion", return_value=object()):
            with self.assertRaises(AttributeError):
                client.generate(prompt="hello")

    def test_budget_exceeded_error_is_not_retried(self):
        client = LiteLLMClient(model_name="openai/gpt-4.1-mini")
        error = BudgetExceededError(current_cost=2.0, max_budget=1.0)

        with patch("hugegraph_llm.models.llms.litellm.completion", side_effect=error) as mock_completion:
            with self.assertRaises(BudgetExceededError):
                client.generate(prompt="hello")

        mock_completion.assert_called_once()

    def test_generate_retries_api_error_and_reraises_original_exception(self):
        client = LiteLLMClient(model_name="openai/gpt-4.1-mini")
        error = APIError(status_code=500, message="upstream failed", llm_provider="openai", model="gpt-4.1-mini")

        with patch("hugegraph_llm.models.llms.litellm.completion", side_effect=error) as mock_completion:
            with self.assertRaises(APIError):
                client.generate(prompt="hello")

        self.assertEqual(mock_completion.call_count, 2)

    def test_generate_streaming_reraises_api_error(self):
        client = LiteLLMClient(model_name="openai/gpt-4.1-mini")
        error = APIError(status_code=500, message="upstream failed", llm_provider="openai", model="gpt-4.1-mini")

        with patch("hugegraph_llm.models.llms.litellm.completion", side_effect=error):
            with self.assertRaises(APIError):
                client.generate_streaming(prompt="hello")

    def test_agenerate_retries_api_error_and_reraises_original_exception(self):
        client = LiteLLMClient(model_name="openai/gpt-4.1-mini")
        error = APIError(status_code=500, message="upstream failed", llm_provider="openai", model="gpt-4.1-mini")

        async def run_async_test():
            with patch("hugegraph_llm.models.llms.litellm.acompletion", new=AsyncMock(side_effect=error)) as mock_call:
                with self.assertRaises(APIError):
                    await client.agenerate(prompt="hello")

            self.assertEqual(mock_call.call_count, 2)

        asyncio.run(run_async_test())

    def test_agenerate_streaming_reraises_api_error(self):
        client = LiteLLMClient(model_name="openai/gpt-4.1-mini")
        error = APIError(status_code=500, message="upstream failed", llm_provider="openai", model="gpt-4.1-mini")

        async def run_async_test():
            with patch("hugegraph_llm.models.llms.litellm.acompletion", new=AsyncMock(side_effect=error)):
                with self.assertRaises(APIError):
                    async for _ in client.agenerate_streaming(prompt="hello"):
                        pass

        asyncio.run(run_async_test())


if __name__ == "__main__":
    unittest.main()
