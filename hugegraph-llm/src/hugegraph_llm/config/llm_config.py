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
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field

from .models import BaseConfig


class LLMConfig(BaseConfig):
    """LLM settings"""

    section: ClassVar[str] = "llm"
    connection_groups: ClassVar[dict[str, tuple[str, ...]]] = {}
    extract_use_chat: bool = True
    text2gql_use_chat: bool = True

    @classmethod
    def _canonical(cls, source):
        values = super()._canonical(source)
        raw_names = {k.lower() for k in getattr(source, "env_vars", source())}
        for role in ("extract", "text2gql"):
            explicit = {f for f in cls.connection_groups.get(role, ()) if not f.endswith(("tokens", "use_chat"))}
            if any(f.lower() in raw_names and values.get(f) not in (None, "") for f in explicit):
                values.setdefault(f"{role}_use_chat", False)
        return values

    def group_values(self, group):
        if group in ("extract", "text2gql") and getattr(self, f"{group}_use_chat"):
            return {f"{group}_use_chat": True}
        provider = getattr(
            self,
            "embedding_type"
            if group == "embedding"
            else "reranker_type"
            if group == "reranker"
            else f"{group}_llm_type",
        )
        prefix = "ollama" if provider == "ollama/local" else provider
        return {
            f: getattr(self, f)
            for f in self.connection_groups[group]
            if f.startswith(f"{prefix}_{group}_")
            or f
            in (
                f"{group}_llm_type",
                f"{group}_use_chat",
                "embedding_type",
                "reranker_type",
                "reranker_api_key",
                "reranker_model",
            )
            or (group == "reranker" and provider == "cohere" and f == "cohere_base_url")
        }

    def validate_connection(self, group):
        if group in ("extract", "text2gql") and getattr(self, f"{group}_use_chat"):
            return
        values = self.group_values(group)
        provider = values.get(f"{group}_llm_type", values.get("embedding_type", values.get("reranker_type")))
        if provider is None and group == "reranker":
            return
        for field, value in values.items():
            if field.endswith(("_language_model", "_model", "_host")) and not str(value or "").strip():
                raise ValueError("A model and destination are required")
            if field.endswith("_port") and (value is None or not 1 <= int(value) <= 65535):
                raise ValueError("Invalid port")
            if field.endswith(("_api_base", "_base_url")):
                parsed = urlsplit(str(value or ""))
                if (
                    parsed.scheme not in ("http", "https")
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.fragment
                ):
                    raise ValueError("An absolute HTTP(S) URL without embedded credentials is required")
                _ = parsed.port

    def effective_role(self, role):
        return "chat" if role in ("extract", "text2gql") and getattr(self, f"{role}_use_chat") else role

    language: Literal["EN", "CN"] = "EN"
    chat_llm_type: Literal["openai", "ollama/local"] = "openai"
    extract_llm_type: Literal["openai", "ollama/local"] = "openai"
    text2gql_llm_type: Literal["openai", "ollama/local"] = "openai"
    embedding_type: Optional[Literal["openai", "ollama/local"]] = "openai"
    reranker_type: Optional[Literal["cohere", "siliconflow"]] = None
    rag_query_max_length: int = Field(default=50, ge=1)
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
    openai_chat_tokens: int = Field(8192, ge=1)
    openai_extract_tokens: int = Field(256, ge=1)
    openai_text2gql_tokens: int = Field(4096, ge=1)
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


LLMConfig.connection_groups = {
    **{
        role: tuple(f for f in LLMConfig.model_fields if f.startswith(f"{role}_") or f"_{role}_" in f)
        for role in ("chat", "extract", "text2gql")
    },
    "embedding": tuple(f for f in LLMConfig.model_fields if f.startswith("embedding_") or "_embedding_" in f),
    "reranker": tuple(f for f in LLMConfig.model_fields if f.startswith(("reranker_", "cohere_"))),
}
