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


from typing import ClassVar, Literal, Optional

from .models import BaseConfig


class LLMConfig(BaseConfig):
    """LLM settings"""

    _config_section: ClassVar[str] = "llm"

    _flat_to_nested_mapping: ClassVar[dict] = {
        "openai_chat_api_base": "openai.chat.api_base",
        "openai_chat_api_key": "openai.chat.api_key",
        "openai_chat_language_model": "openai.chat.language_model",
        "openai_chat_tokens": "openai.chat.tokens",
        "openai_extract_api_base": "openai.extract.api_base",
        "openai_extract_api_key": "openai.extract.api_key",
        "openai_extract_language_model": "openai.extract.language_model",
        "openai_extract_tokens": "openai.extract.tokens",
        "openai_text2gql_api_base": "openai.text2gql.api_base",
        "openai_text2gql_api_key": "openai.text2gql.api_key",
        "openai_text2gql_language_model": "openai.text2gql.language_model",
        "openai_text2gql_tokens": "openai.text2gql.tokens",
        "openai_embedding_api_base": "openai.embedding.api_base",
        "openai_embedding_api_key": "openai.embedding.api_key",
        "openai_embedding_model": "openai.embedding.model",
        "ollama_chat_host": "ollama.chat.host",
        "ollama_chat_port": "ollama.chat.port",
        "ollama_chat_language_model": "ollama.chat.language_model",
        "ollama_extract_host": "ollama.extract.host",
        "ollama_extract_port": "ollama.extract.port",
        "ollama_extract_language_model": "ollama.extract.language_model",
        "ollama_text2gql_host": "ollama.text2gql.host",
        "ollama_text2gql_port": "ollama.text2gql.port",
        "ollama_text2gql_language_model": "ollama.text2gql.language_model",
        "ollama_embedding_host": "ollama.embedding.host",
        "ollama_embedding_port": "ollama.embedding.port",
        "ollama_embedding_model": "ollama.embedding.model",
        "litellm_chat_api_key": "litellm.chat.api_key",
        "litellm_chat_api_base": "litellm.chat.api_base",
        "litellm_chat_language_model": "litellm.chat.language_model",
        "litellm_chat_tokens": "litellm.chat.tokens",
        "litellm_extract_api_key": "litellm.extract.api_key",
        "litellm_extract_api_base": "litellm.extract.api_base",
        "litellm_extract_language_model": "litellm.extract.language_model",
        "litellm_extract_tokens": "litellm.extract.tokens",
        "litellm_text2gql_api_key": "litellm.text2gql.api_key",
        "litellm_text2gql_api_base": "litellm.text2gql.api_base",
        "litellm_text2gql_language_model": "litellm.text2gql.language_model",
        "litellm_text2gql_tokens": "litellm.text2gql.tokens",
        "litellm_embedding_api_key": "litellm.embedding.api_key",
        "litellm_embedding_api_base": "litellm.embedding.api_base",
        "litellm_embedding_model": "litellm.embedding.model",
    }

    _env_var_map: ClassVar[dict] = {
        "openai_chat_api_key": "OPENAI_API_KEY",
        "openai_chat_api_base": "OPENAI_BASE_URL",
        "openai_extract_api_key": "OPENAI_API_KEY",
        "openai_extract_api_base": "OPENAI_BASE_URL",
        "openai_text2gql_api_key": "OPENAI_API_KEY",
        "openai_text2gql_api_base": "OPENAI_BASE_URL",
        "openai_embedding_api_key": "OPENAI_EMBEDDING_API_KEY",
        "openai_embedding_api_base": "OPENAI_EMBEDDING_BASE_URL",
        "cohere_base_url": "CO_API_URL",
    }

    language: Literal["EN", "CN"] = "EN"
    chat_llm_type: Literal["openai", "litellm", "ollama/local"] = "openai"
    extract_llm_type: Literal["openai", "litellm", "ollama/local"] = "openai"
    text2gql_llm_type: Literal["openai", "litellm", "ollama/local"] = "openai"
    embedding_type: Optional[Literal["openai", "litellm", "ollama/local"]] = "openai"
    reranker_type: Optional[Literal["cohere", "siliconflow"]] = None
    keyword_extract_type: Literal["llm", "textrank", "hybrid"] = "llm"
    window_size: Optional[int] = 3
    hybrid_llm_weights: Optional[float] = 0.5
    # OpenAI
    openai_chat_api_base: Optional[str] = "https://api.openai.com/v1"
    openai_chat_api_key: Optional[str] = None
    openai_chat_language_model: Optional[str] = "gpt-4.1-mini"
    openai_extract_api_base: Optional[str] = "https://api.openai.com/v1"
    openai_extract_api_key: Optional[str] = None
    openai_extract_language_model: Optional[str] = "gpt-4.1-mini"
    openai_text2gql_api_base: Optional[str] = "https://api.openai.com/v1"
    openai_text2gql_api_key: Optional[str] = None
    openai_text2gql_language_model: Optional[str] = "gpt-4.1-mini"
    openai_embedding_api_base: Optional[str] = "https://api.openai.com/v1"
    openai_embedding_api_key: Optional[str] = None
    openai_embedding_model: Optional[str] = "text-embedding-3-small"
    openai_chat_tokens: int = 8192
    openai_extract_tokens: int = 256
    openai_text2gql_tokens: int = 4096
    # Rerank
    cohere_base_url: Optional[str] = "https://api.cohere.com/v1/rerank"
    reranker_api_key: Optional[str] = None
    reranker_model: Optional[str] = None
    # Ollama
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
    # LiteLLM
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
