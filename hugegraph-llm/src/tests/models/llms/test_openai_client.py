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

from hugegraph_llm.models.llms.openai import OpenAIClient

pytestmark = pytest.mark.contract


class TestOpenAIClient(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures and common mock objects."""
        # Create mock completion response
        self.mock_completion_response = MagicMock()
        self.mock_completion_response.choices = [MagicMock(message=MagicMock(content="Paris"))]
        self.mock_completion_response.usage = MagicMock()
        self.mock_completion_response.usage.model_dump_json.return_value = (
            '{"prompt_tokens": 10, "completion_tokens": 5}'
        )

        # Create mock streaming chunks
        self.mock_streaming_chunks = [
            MagicMock(choices=[MagicMock(delta=MagicMock(content="Pa"))]),
            MagicMock(choices=[MagicMock(delta=MagicMock(content="ris"))]),
            MagicMock(choices=[MagicMock(delta=MagicMock(content=""))]),  # Empty content
        ]

    @patch("hugegraph_llm.models.llms.openai.OpenAI")
    def test_generate(self, mock_openai_class):
        """Test generate method with mocked OpenAI client."""
        # Setup mock client
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self.mock_completion_response
        mock_openai_class.return_value = mock_client

        # Test the method
        openai_client = OpenAIClient(model_name="gpt-3.5-turbo")
        response = openai_client.generate(prompt="What is the capital of France?")

        # Verify the response
        self.assertIsInstance(response, str)
        self.assertEqual(response, "Paris")

        # Verify the API was called with correct parameters
        mock_client.chat.completions.create.assert_called_once_with(
            model="gpt-3.5-turbo",
            temperature=0.01,
            max_tokens=8092,
            messages=[{"role": "user", "content": "What is the capital of France?"}],
        )

    @patch("hugegraph_llm.models.llms.openai.OpenAI")
    def test_generate_with_messages(self, mock_openai_class):
        """Test generate method with messages parameter."""
        # Setup mock client
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self.mock_completion_response
        mock_openai_class.return_value = mock_client

        # Test the method
        openai_client = OpenAIClient(model_name="gpt-3.5-turbo")
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is the capital of France?"},
        ]
        response = openai_client.generate(messages=messages)

        # Verify the response
        self.assertIsInstance(response, str)
        self.assertEqual(response, "Paris")

        # Verify the API was called with correct parameters
        mock_client.chat.completions.create.assert_called_once_with(
            model="gpt-3.5-turbo",
            temperature=0.01,
            max_tokens=8092,
            messages=messages,
        )

    @patch("hugegraph_llm.models.llms.openai.OpenAI")
    def test_generate_raises_runtime_error_with_empty_choices(self, mock_openai_class):
        """Test generate method with an empty choices response."""
        # Setup mock client
        mock_client = MagicMock()
        empty_response = MagicMock()
        empty_response.choices = []
        empty_response.usage = None
        mock_client.chat.completions.create.return_value = empty_response
        mock_openai_class.return_value = mock_client

        # Test the method
        openai_client = OpenAIClient(model_name="gpt-3.5-turbo")

        with self.assertRaisesRegex(RuntimeError, "Empty choices in LLM response"):
            openai_client.generate(prompt="What is the capital of France?")

    @patch("hugegraph_llm.models.llms.openai.OpenAI")
    def test_generate_malformed_sdk_response_raises_attribute_error(self, mock_openai_class):
        """Test malformed SDK responses surface the missing contract."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = object()
        mock_openai_class.return_value = mock_client

        openai_client = OpenAIClient(model_name="gpt-3.5-turbo")

        with self.assertRaises(AttributeError):
            openai_client.generate(prompt="What is the capital of France?")

    @patch("hugegraph_llm.models.llms.openai.AsyncOpenAI")
    def test_agenerate(self, mock_async_openai_class):
        """Test agenerate method with mocked async OpenAI client."""
        # Setup mock async client
        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(return_value=self.mock_completion_response)
        mock_async_openai_class.return_value = mock_async_client

        # Test the method
        openai_client = OpenAIClient(model_name="gpt-3.5-turbo")

        async def run_async_test():
            response = await openai_client.agenerate(prompt="What is the capital of France?")
            self.assertIsInstance(response, str)
            self.assertEqual(response, "Paris")

            # Verify the API was called with correct parameters
            mock_async_client.chat.completions.create.assert_called_once_with(
                model="gpt-3.5-turbo",
                temperature=0.01,
                max_tokens=8092,
                messages=[{"role": "user", "content": "What is the capital of France?"}],
            )

        asyncio.run(run_async_test())

    @patch("hugegraph_llm.models.llms.openai.AsyncOpenAI")
    def test_agenerate_raises_runtime_error_with_empty_choices(self, mock_async_openai_class):
        """Test agenerate method with an empty choices response."""
        # Setup mock async client
        mock_async_client = MagicMock()
        empty_response = MagicMock()
        empty_response.choices = []
        empty_response.usage = None
        mock_async_client.chat.completions.create = AsyncMock(return_value=empty_response)
        mock_async_openai_class.return_value = mock_async_client

        # Test the method
        openai_client = OpenAIClient(model_name="gpt-3.5-turbo")

        async def run_async_test():
            with self.assertRaisesRegex(RuntimeError, "Empty choices in LLM response"):
                await openai_client.agenerate(prompt="What is the capital of France?")

        asyncio.run(run_async_test())

    @patch("hugegraph_llm.models.llms.openai.OpenAI")
    def test_stream_generate(self, mock_openai_class):
        """Test generate_streaming method with mocked OpenAI client."""
        # Setup mock client with streaming response
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = iter(self.mock_streaming_chunks)
        mock_openai_class.return_value = mock_client

        # Test the method
        openai_client = OpenAIClient(model_name="gpt-3.5-turbo")
        collected_tokens = []

        def on_token_callback(chunk):
            collected_tokens.append(chunk)

        # Collect all tokens from the generator
        tokens = list(
            openai_client.generate_streaming(
                prompt="What is the capital of France?", on_token_callback=on_token_callback
            )
        )

        # Verify the response
        self.assertEqual(tokens, ["Pa", "ris"])
        self.assertEqual(collected_tokens, ["Pa", "ris"])

        # Verify the API was called with correct parameters
        mock_client.chat.completions.create.assert_called_once_with(
            model="gpt-3.5-turbo",
            temperature=0.01,
            max_tokens=8092,
            messages=[{"role": "user", "content": "What is the capital of France?"}],
            stream=True,
        )

    @patch("hugegraph_llm.models.llms.openai.AsyncOpenAI")
    def test_agenerate_streaming(self, mock_async_openai_class):
        """Test agenerate_streaming method with mocked async OpenAI client."""
        # Setup mock async client with streaming response
        mock_async_client = MagicMock()

        # Create async generator for streaming chunks
        async def async_streaming_chunks():
            for chunk in self.mock_streaming_chunks:
                yield chunk

        mock_async_client.chat.completions.create = AsyncMock(return_value=async_streaming_chunks())
        mock_async_openai_class.return_value = mock_async_client

        # Test the method
        openai_client = OpenAIClient(model_name="gpt-3.5-turbo")

        async def run_async_streaming_test():
            collected_tokens = []

            def on_token_callback(chunk):
                collected_tokens.append(chunk)

            # Collect all tokens from the async generator
            tokens = []
            async for token in openai_client.agenerate_streaming(
                prompt="What is the capital of France?", on_token_callback=on_token_callback
            ):
                tokens.append(token)

            # Verify the response
            self.assertEqual(tokens, ["Pa", "ris"])
            self.assertEqual(collected_tokens, ["Pa", "ris"])

            # Verify the API was called with correct parameters
            mock_async_client.chat.completions.create.assert_called_once_with(
                model="gpt-3.5-turbo",
                temperature=0.01,
                max_tokens=8092,
                messages=[{"role": "user", "content": "What is the capital of France?"}],
                stream=True,
            )

        asyncio.run(run_async_streaming_test())

    @patch("hugegraph_llm.models.llms.openai.OpenAI")
    def test_generate_authentication_error(self, mock_openai_class):
        """Test generate method with authentication error."""
        # Setup mock client to raise OpenAI 的认证错误
        from openai import AuthenticationError

        mock_client = MagicMock()

        # Create a properly formatted AuthenticationError
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.headers = {}

        auth_error = AuthenticationError(
            message="Invalid API key", response=mock_response, body={"error": {"message": "Invalid API key"}}
        )
        mock_client.chat.completions.create.side_effect = auth_error
        mock_openai_class.return_value = mock_client

        # Test the method
        openai_client = OpenAIClient(model_name="gpt-3.5-turbo")

        # 调用后应返回认证失败的错误消息
        result = openai_client.generate(prompt="What is the capital of France?")
        self.assertEqual(result, "Error: The provided OpenAI API key is invalid")

    @patch("hugegraph_llm.models.llms.openai.tiktoken.encoding_for_model")
    def test_num_tokens_from_string(self, mock_encoding_for_model):
        """Test num_tokens_from_string method with mocked tiktoken."""
        # Setup mock encoding
        mock_encoding = MagicMock()
        mock_encoding.encode.return_value = [1, 2, 3, 4, 5]  # 5 tokens
        mock_encoding_for_model.return_value = mock_encoding

        # Test the method
        openai_client = OpenAIClient(model_name="gpt-3.5-turbo")
        token_count = openai_client.num_tokens_from_string("Hello, world!")

        # Verify the response
        self.assertIsInstance(token_count, int)
        self.assertEqual(token_count, 5)

        # Verify the encoding was called correctly
        mock_encoding_for_model.assert_called_once_with("gpt-3.5-turbo")
        mock_encoding.encode.assert_called_once_with("Hello, world!")

    def test_max_allowed_token_length(self):
        """Test max_allowed_token_length method."""
        openai_client = OpenAIClient(model_name="gpt-3.5-turbo")
        max_tokens = openai_client.max_allowed_token_length()
        self.assertIsInstance(max_tokens, int)
        self.assertEqual(max_tokens, 8192)

    def test_get_llm_type(self):
        """Test get_llm_type method."""
        openai_client = OpenAIClient()
        llm_type = openai_client.get_llm_type()
        self.assertEqual(llm_type, "openai")


if __name__ == "__main__":
    unittest.main()
