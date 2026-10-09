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

import os
from unittest.mock import MagicMock, patch

from hugegraph_llm.document import Document

from .utils.mock import VectorIndex


# Check if external service tests should be skipped
def should_skip_external():
    return os.environ.get("SKIP_EXTERNAL_SERVICES") == "true"


# Create mock Ollama embedding response
def mock_ollama_embedding(dimension=1024):
    return {"embedding": [0.1] * dimension}


# Create mock OpenAI embedding response
def mock_openai_embedding(dimension=1536):
    class MockResponse:
        def __init__(self, data):
            self.data = data

    return MockResponse([{"embedding": [0.1] * dimension, "index": 0}])


# Create mock OpenAI chat response
def mock_openai_chat_response(text="Mock OpenAI response"):
    class MockResponse:
        def __init__(self, content):
            self.choices = [MagicMock()]
            self.choices[0].message.content = content

    return MockResponse(text)


# Create mock Ollama chat response
def mock_ollama_chat_response(text="Mock Ollama response"):
    return {"message": {"content": text}}


# Decorator for mocking Ollama embedding
def with_mock_ollama_embedding(func):
    @patch("ollama._client.Client._request_raw")
    def wrapper(self, mock_request, *args, **kwargs):
        mock_request.return_value.json.return_value = mock_ollama_embedding()
        return func(self, *args, **kwargs)

    return wrapper


# Decorator for mocking OpenAI embedding
def with_mock_openai_embedding(func):
    @patch("openai.resources.embeddings.Embeddings.create")
    def wrapper(self, mock_create, *args, **kwargs):
        mock_create.return_value = mock_openai_embedding()
        return func(self, *args, **kwargs)

    return wrapper


# Decorator for mocking Ollama LLM client
def with_mock_ollama_client(func):
    @patch("ollama._client.Client._request_raw")
    def wrapper(self, mock_request, *args, **kwargs):
        mock_request.return_value.json.return_value = mock_ollama_chat_response()
        return func(self, *args, **kwargs)

    return wrapper


# Decorator for mocking OpenAI LLM client
def with_mock_openai_client(func):
    @patch("openai.resources.chat.completions.Completions.create")
    def wrapper(self, mock_create, *args, **kwargs):
        mock_create.return_value = mock_openai_chat_response()
        return func(self, *args, **kwargs)

    return wrapper


# Helper function to download NLTK resources
def ensure_nltk_resources():
    import nltk

    try:
        nltk.data.find("corpora/stopwords")
    except LookupError:
        nltk.download("stopwords", quiet=True)


# Helper function to create test document
def create_test_document(content="This is a test document"):
    return Document(content=content, metadata={"source": "test"})


# Helper function to create test vector index
def create_test_vector_index(dimension=1536):
    index = VectorIndex(dimension)
    return index
