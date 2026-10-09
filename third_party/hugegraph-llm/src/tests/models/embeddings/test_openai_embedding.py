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


import unittest
from unittest.mock import MagicMock, patch

from hugegraph_llm.models.embeddings.openai import OpenAIEmbedding


class TestOpenAIEmbedding(unittest.TestCase):
    def setUp(self):
        # Create a mock embedding response
        self.mock_embedding = [0.1, 0.2, 0.3, 0.4, 0.5]

        # Create a mock response object
        self.mock_response = MagicMock()
        self.mock_response.data = [MagicMock()]
        self.mock_response.data[0].embedding = self.mock_embedding

    # test_init removed due to CI environment compatibility issues

    @patch("hugegraph_llm.models.embeddings.openai.OpenAI")
    @patch("hugegraph_llm.models.embeddings.openai.AsyncOpenAI")
    def test_get_text_embedding(self, mock_async_openai_class, mock_openai_class):
        # Configure the mock
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        # Configure the embeddings.create method
        mock_embeddings = MagicMock()
        mock_client.embeddings = mock_embeddings
        mock_embeddings.create.return_value = self.mock_response

        # Create an instance of OpenAIEmbedding
        embedding = OpenAIEmbedding(api_key="test-key")

        # Call the method
        result = embedding.get_text_embedding("test text")

        # Verify the result
        self.assertEqual(result, self.mock_embedding)

        # Verify the mock was called correctly
        mock_embeddings.create.assert_called_once_with(input="test text", model="text-embedding-3-small")

    @patch("hugegraph_llm.models.embeddings.openai.OpenAI")
    @patch("hugegraph_llm.models.embeddings.openai.AsyncOpenAI")
    def test_embedding_dimension(self, mock_async_openai_class, mock_openai_class):
        # Configure the mock
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        # Configure the embeddings.create method
        mock_embeddings = MagicMock()
        mock_client.embeddings = mock_embeddings
        mock_embeddings.create.return_value = self.mock_response

        # Create an instance of OpenAIEmbedding
        embedding = OpenAIEmbedding(api_key="test-key")

        # Call the method
        result = embedding.get_text_embedding("test text")

        # Verify the result has the correct dimension
        self.assertEqual(len(result), 5)  # Our mock embedding has 5 dimensions
