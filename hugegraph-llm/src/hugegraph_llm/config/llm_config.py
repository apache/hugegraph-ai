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


from typing import Literal, Optional
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import AliasChoices, Field

from .models import BaseConfig, base_config


class LLMConfig(BaseConfig):
    """LLM settings"""

    @classmethod
    def _generic_key_is_scoped(cls, field):
        source = super().environment_source(field)
        if not field.endswith("_api_key") or not source or source.upper() != "OPENAI_API_KEY":
            return True
        base_field = field.removesuffix("_api_key") + "_api_base"
        if super().environment_source(base_field):
            return True
        values = {key.upper(): value for key, value in dotenv_values(base_config.env_path).items()}
        endpoint = values.get(base_field.upper()) or values.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        parsed = urlsplit(endpoint)
        return parsed.scheme == "https" and parsed.hostname == "api.openai.com" and parsed.port in (None, 443)

    @classmethod
    def environment_source(cls, field):
        return super().environment_source(field) if cls._generic_key_is_scoped(field) else None

    @classmethod
    def settings_customise_sources(cls, *args, **kwargs):
        sources = super().settings_customise_sources(*args, **kwargs)

        def scoped_environment():
            values = sources[1]()
            file_values = sources[2]()
            for role in ("chat", "extract", "text2gql"):
                field = f"openai_{role}_api_key"
                if not cls._generic_key_is_scoped(field):
                    key = field.upper()
                    if key not in file_values:
                        raise ValueError(
                            f"{key} is required for a file-configured custom endpoint; a generic process key cannot be forwarded there"
                        )
                    values.pop(key, None)
            return values

        return sources[0], scoped_environment, *sources[2:]

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
    openai_chat_api_base: Optional[str] = Field(
        "https://api.openai.com/v1", validation_alias=AliasChoices("OPENAI_CHAT_API_BASE", "OPENAI_BASE_URL")
    )
    openai_chat_api_key: Optional[str] = Field(
        None, validation_alias=AliasChoices("OPENAI_CHAT_API_KEY", "OPENAI_API_KEY")
    )
    openai_chat_language_model: Optional[str] = "gpt-4.1-mini"
    openai_extract_api_base: Optional[str] = Field(
        "https://api.openai.com/v1", validation_alias=AliasChoices("OPENAI_EXTRACT_API_BASE", "OPENAI_BASE_URL")
    )
    openai_extract_api_key: Optional[str] = Field(
        None, validation_alias=AliasChoices("OPENAI_EXTRACT_API_KEY", "OPENAI_API_KEY")
    )
    openai_extract_language_model: Optional[str] = "gpt-4.1-mini"
    openai_text2gql_api_base: Optional[str] = Field(
        "https://api.openai.com/v1", validation_alias=AliasChoices("OPENAI_TEXT2GQL_API_BASE", "OPENAI_BASE_URL")
    )
    openai_text2gql_api_key: Optional[str] = Field(
        None, validation_alias=AliasChoices("OPENAI_TEXT2GQL_API_KEY", "OPENAI_API_KEY")
    )
    openai_text2gql_language_model: Optional[str] = "gpt-4.1-mini"
    openai_embedding_api_base: Optional[str] = Field(
        "https://api.openai.com/v1",
        validation_alias=AliasChoices("OPENAI_EMBEDDING_API_BASE", "OPENAI_EMBEDDING_BASE_URL"),
    )
    openai_embedding_api_key: Optional[str] = Field(
        None, validation_alias=AliasChoices("OPENAI_EMBEDDING_API_KEY", "OPENAI_EMBEDDING_API_KEY")
    )
    openai_embedding_model: Optional[str] = "text-embedding-3-small"
    openai_chat_tokens: int = 8192
    openai_extract_tokens: int = 256
    openai_text2gql_tokens: int = 4096
    # 2. Rerank settings
    cohere_base_url: Optional[str] = Field(
        "https://api.cohere.com/v1/rerank", validation_alias=AliasChoices("COHERE_BASE_URL", "CO_API_URL")
    )
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
