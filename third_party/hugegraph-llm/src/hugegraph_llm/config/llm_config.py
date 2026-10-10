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
from typing import Literal, Optional

from .models import BaseConfig


class LLMConfig(BaseConfig):
    """LLM settings"""

    language: Literal["EN", "CN"] = "EN"
    chat_llm_type: Literal["openai", "litellm", "ollama/local"] = "openai"
    extract_llm_type: Literal["openai", "litellm", "ollama/local"] = "openai"
    text2gql_llm_type: Literal["openai", "litellm", "ollama/local"] = "openai"
    embedding_type: Optional[Literal["openai", "litellm", "ollama/local"]] = "openai"
    reranker_type: Optional[Literal["cohere", "siliconflow"]] = None
    keyword_extract_type: Literal["llm", "textrank", "hybrid"] = "llm"
    window_size: Optional[int] = 3
    hybrid_llm_weights: Optional[float] = 0.5
    # TODO: divide RAG part if necessary
    # 1. OpenAI settings
    openai_chat_api_base: Optional[str] = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_chat_api_key: Optional[str] = os.environ.get("OPENAI_API_KEY")
    openai_chat_language_model: Optional[str] = "gpt-4.1-mini"
    openai_extract_api_base: Optional[str] = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_extract_api_key: Optional[str] = os.environ.get("OPENAI_API_KEY")
    openai_extract_language_model: Optional[str] = "gpt-4.1-mini"
    openai_text2gql_api_base: Optional[str] = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_text2gql_api_key: Optional[str] = os.environ.get("OPENAI_API_KEY")
    openai_text2gql_language_model: Optional[str] = "gpt-4.1-mini"
    openai_embedding_api_base: Optional[str] = os.environ.get("OPENAI_EMBEDDING_BASE_URL", "https://api.openai.com/v1")
    openai_embedding_api_key: Optional[str] = os.environ.get("OPENAI_EMBEDDING_API_KEY")
    openai_embedding_model: Optional[str] = "text-embedding-3-small"
    openai_chat_tokens: int = 8192
    openai_extract_tokens: int = 256
    openai_text2gql_tokens: int = 4096
    # 2. Rerank settings
    cohere_base_url: Optional[str] = os.environ.get("CO_API_URL", "https://api.cohere.com/v1/rerank")
    reranker_api_key: Optional[str] = None
    reranker_model: Optional[str] = None
    # 3. Ollama settings
    ollama_chat_host: Optional[str] = "127.0.0.1"
    ollama_chat_port: Optional[int] = 11434
    ollama_chat_language_model: Optional[str] = None
    ollama_extract_host: Optional[str] = "127.0.0.1"
    ollama_extract_port: Optional[int] = 11434
    ollama_extract_language_model: Optional[str] = None
    ollama_text2gql_host: Optional[str] = "127.0.0.1"
    ollama_text2gql_port: Optional[int] = 11434
    ollama_text2gql_language_model: Optional[str] = None
    ollama_embedding_host: Optional[str] = "127.0.0.1"
    ollama_embedding_port: Optional[int] = 11434
    ollama_embedding_model: Optional[str] = None
    # 4. LiteLLM settings
    litellm_chat_api_key: Optional[str] = None
    litellm_chat_api_base: Optional[str] = None
    litellm_chat_language_model: Optional[str] = "openai/gpt-4.1-mini"
    litellm_chat_tokens: int = 8192
    litellm_extract_api_key: Optional[str] = None
    litellm_extract_api_base: Optional[str] = None
    litellm_extract_language_model: Optional[str] = "openai/gpt-4.1-mini"
    litellm_extract_tokens: int = 256
    litellm_text2gql_api_key: Optional[str] = None
    litellm_text2gql_api_base: Optional[str] = None
    litellm_text2gql_language_model: Optional[str] = "openai/gpt-4.1-mini"
    litellm_text2gql_tokens: int = 4096
    litellm_embedding_api_key: Optional[str] = None
    litellm_embedding_api_base: Optional[str] = None
    litellm_embedding_model: Optional[str] = "openai/text-embedding-3-small"
