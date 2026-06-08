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

from unittest.mock import Mock

import pytest
from fastapi import APIRouter, FastAPI, status
from fastapi.testclient import TestClient

from hugegraph_llm.api.rag_api import rag_http_api
from hugegraph_llm.config import huge_settings, llm_settings

pytestmark = pytest.mark.contract

# FIXME: add negative-path tests for each /config/* endpoint that assert
# provider/auth/connection failures surface distinct error details.
# FIXME: add happy-path HTTP contract tests for /rag and /rag/graph response
# shaping and output-flag filtering.
# FIXME: distinguish graph/provider dependency failures from programmer errors
# instead of asserting one generic unexpected-error response for all failures.


def _make_test_client(**overrides):
    callbacks = {
        "rag_answer_func": Mock(return_value=("raw", "vector", "graph", "graph_vector")),
        "graph_rag_recall_func": Mock(return_value={"query": "q", "keywords": []}),
        "apply_graph_conf": Mock(return_value=status.HTTP_200_OK),
        "apply_llm_conf": Mock(return_value=status.HTTP_200_OK),
        "apply_embedding_conf": Mock(return_value=status.HTTP_200_OK),
        "apply_reranker_conf": Mock(return_value=status.HTTP_200_OK),
        "gremlin_generate_selective_func": Mock(return_value={"result": "g.V()"}),
    }
    callbacks.update(overrides)
    router = APIRouter()
    rag_http_api(router, **callbacks)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), callbacks


def _snapshot_llm_fields(fields):
    return {field: getattr(llm_settings, field) for field in fields}


def test_graph_config_api_passes_graph_field_to_apply_graph_conf():
    apply_graph_conf = Mock(return_value=status.HTTP_200_OK)
    router = APIRouter()
    rag_http_api(
        router,
        rag_answer_func=Mock(),
        graph_rag_recall_func=Mock(),
        apply_graph_conf=apply_graph_conf,
        apply_llm_conf=Mock(),
        apply_embedding_conf=Mock(),
        apply_reranker_conf=Mock(),
        gremlin_generate_selective_func=Mock(),
    )
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).post(
        "/config/graph",
        json={
            "url": "127.0.0.1:8080",
            "graph": "custom_graph",
            "user": "admin",
            "pwd": "secret",
            "gs": "space_a",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json() == {"message": "Connection successful. Configured finished."}
    apply_graph_conf.assert_called_once_with(
        "127.0.0.1:8080",
        "custom_graph",
        "admin",
        "secret",
        "space_a",
        origin_call="http",
    )


def test_llm_config_api_passes_openai_fields_to_apply_llm_conf(monkeypatch):
    monkeypatch.setattr(llm_settings, "chat_llm_type", "ollama/local")
    monkeypatch.setattr(llm_settings, "extract_llm_type", "ollama/local")
    monkeypatch.setattr(llm_settings, "text2gql_llm_type", "ollama/local")
    client, callbacks = _make_test_client()

    response = client.post(
        "/config/llm",
        json={
            "llm_type": "openai",
            "api_key": "sk-test",
            "api_base": "https://api.example.test",
            "language_model": "gpt-test",
            "max_tokens": "1024",
        },
    )

    assert llm_settings.chat_llm_type == "openai"
    assert llm_settings.extract_llm_type == "openai"
    assert llm_settings.text2gql_llm_type == "openai"
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json() == {"message": "Connection successful. Configured finished."}
    callbacks["apply_llm_conf"].assert_called_once_with(
        "sk-test",
        "https://api.example.test",
        "gpt-test",
        "1024",
        origin_call="http",
    )


def test_embedding_config_api_passes_openai_fields_to_apply_embedding_conf():
    client, callbacks = _make_test_client()

    response = client.post(
        "/config/embedding",
        json={
            "llm_type": "openai",
            "api_key": "sk-embedding",
            "api_base": "https://embedding.example.test",
            "language_model": "embedding-test",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    callbacks["apply_embedding_conf"].assert_called_once_with(
        "sk-embedding",
        "https://embedding.example.test",
        "embedding-test",
        origin_call="http",
    )


def test_llm_config_api_rolls_back_provider_type_on_apply_failure(monkeypatch):
    monkeypatch.setattr(llm_settings, "chat_llm_type", "ollama/local")
    monkeypatch.setattr(llm_settings, "extract_llm_type", "ollama/local")
    monkeypatch.setattr(llm_settings, "text2gql_llm_type", "ollama/local")
    rollback_fields = (
        "chat_llm_type",
        "extract_llm_type",
        "text2gql_llm_type",
        "openai_chat_api_key",
        "openai_chat_api_base",
        "openai_chat_language_model",
        "openai_chat_tokens",
        "openai_extract_api_key",
        "openai_extract_api_base",
        "openai_extract_language_model",
        "openai_extract_tokens",
        "openai_text2gql_api_key",
        "openai_text2gql_api_base",
        "openai_text2gql_language_model",
        "openai_text2gql_tokens",
    )
    original_values = {
        "chat_llm_type": "ollama/local",
        "extract_llm_type": "ollama/local",
        "text2gql_llm_type": "ollama/local",
        "openai_chat_api_key": "old-chat-key",
        "openai_chat_api_base": "https://old-chat.example",
        "openai_chat_language_model": "old-chat-model",
        "openai_chat_tokens": 11,
        "openai_extract_api_key": "old-extract-key",
        "openai_extract_api_base": "https://old-extract.example",
        "openai_extract_language_model": "old-extract-model",
        "openai_extract_tokens": 12,
        "openai_text2gql_api_key": "old-text2gql-key",
        "openai_text2gql_api_base": "https://old-text2gql.example",
        "openai_text2gql_language_model": "old-text2gql-model",
        "openai_text2gql_tokens": 13,
    }
    for field, value in original_values.items():
        monkeypatch.setattr(llm_settings, field, value)

    def failed_apply_llm_conf(api_key, api_base, language_model, max_tokens, **_kwargs):
        for config_name in ("chat", "extract", "text2gql"):
            monkeypatch.setattr(llm_settings, f"openai_{config_name}_api_key", api_key)
            monkeypatch.setattr(llm_settings, f"openai_{config_name}_api_base", api_base)
            monkeypatch.setattr(llm_settings, f"openai_{config_name}_language_model", language_model)
            monkeypatch.setattr(llm_settings, f"openai_{config_name}_tokens", int(max_tokens))
        return status.HTTP_500_INTERNAL_SERVER_ERROR

    client, callbacks = _make_test_client(apply_llm_conf=Mock(side_effect=failed_apply_llm_conf))

    response = client.post(
        "/config/llm",
        json={
            "llm_type": "openai",
            "api_key": "sk-test",
            "api_base": "https://api.example.test",
            "language_model": "gpt-test",
            "max_tokens": "1024",
        },
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert _snapshot_llm_fields(rollback_fields) == original_values
    callbacks["apply_llm_conf"].assert_called_once()


def test_embedding_config_api_rolls_back_provider_type_on_apply_failure(monkeypatch):
    monkeypatch.setattr(llm_settings, "embedding_type", "ollama/local")
    rollback_fields = (
        "embedding_type",
        "openai_embedding_api_key",
        "openai_embedding_api_base",
        "openai_embedding_model",
    )
    original_values = {
        "embedding_type": "ollama/local",
        "openai_embedding_api_key": "old-embedding-key",
        "openai_embedding_api_base": "https://old-embedding.example",
        "openai_embedding_model": "old-embedding-model",
    }
    for field, value in original_values.items():
        monkeypatch.setattr(llm_settings, field, value)

    def failed_apply_embedding_conf(api_key, api_base, language_model, **_kwargs):
        monkeypatch.setattr(llm_settings, "openai_embedding_api_key", api_key)
        monkeypatch.setattr(llm_settings, "openai_embedding_api_base", api_base)
        monkeypatch.setattr(llm_settings, "openai_embedding_model", language_model)
        return status.HTTP_500_INTERNAL_SERVER_ERROR

    client, callbacks = _make_test_client(apply_embedding_conf=Mock(side_effect=failed_apply_embedding_conf))

    response = client.post(
        "/config/embedding",
        json={
            "llm_type": "openai",
            "api_key": "sk-embedding",
            "api_base": "https://embedding.example.test",
            "language_model": "embedding-test",
        },
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert _snapshot_llm_fields(rollback_fields) == original_values
    callbacks["apply_embedding_conf"].assert_called_once()


def test_rerank_config_api_passes_cohere_fields_to_apply_reranker_conf():
    client, callbacks = _make_test_client()

    response = client.post(
        "/config/rerank",
        json={
            "reranker_type": "cohere",
            "api_key": "cohere-key",
            "reranker_model": "rerank-test",
            "cohere_base_url": "https://cohere.example.test",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    callbacks["apply_reranker_conf"].assert_called_once_with(
        "cohere-key",
        "rerank-test",
        "https://cohere.example.test",
        origin_call="http",
    )


def test_rag_api_invalid_request_body_returns_validation_shape():
    client, _ = _make_test_client()

    response = client.post("/rag", json={})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.json()["detail"][0]["loc"][-1] == "query"


def test_rag_client_config_updates_only_explicit_graph_fields(monkeypatch):
    monkeypatch.setattr(huge_settings, "graph_url", "http://original:8080")
    monkeypatch.setattr(huge_settings, "graph_name", "original_graph")
    monkeypatch.setattr(huge_settings, "graph_user", "original_user")
    monkeypatch.setattr(huge_settings, "graph_pwd", "original_pwd")
    monkeypatch.setattr(huge_settings, "graph_space", "original_space")
    observed_settings = {}

    def rag_answer_func(**_kwargs):
        observed_settings["graph_url"] = huge_settings.graph_url
        observed_settings["graph_name"] = huge_settings.graph_name
        observed_settings["graph_user"] = huge_settings.graph_user
        observed_settings["graph_pwd"] = huge_settings.graph_pwd
        observed_settings["graph_space"] = huge_settings.graph_space
        return ("raw", "vector", "graph", "graph_vector")

    client, callbacks = _make_test_client(rag_answer_func=Mock(side_effect=rag_answer_func))

    response = client.post(
        "/rag",
        json={
            "query": "find vertices",
            "client_config": {
                "url": "http://override:8080",
            },
        },
    )

    assert response.status_code == status.HTTP_200_OK
    callbacks["rag_answer_func"].assert_called_once()
    assert observed_settings == {
        "graph_url": "http://override:8080",
        "graph_name": "original_graph",
        "graph_user": "original_user",
        "graph_pwd": "original_pwd",
        "graph_space": "original_space",
    }
    assert huge_settings.graph_url == "http://original:8080"
    assert huge_settings.graph_name == "original_graph"
    assert huge_settings.graph_user == "original_user"
    assert huge_settings.graph_pwd == "original_pwd"
    assert huge_settings.graph_space == "original_space"


def test_llm_config_rejects_unsupported_provider_without_mutating(monkeypatch):
    monkeypatch.setattr(llm_settings, "chat_llm_type", "openai")
    client, callbacks = _make_test_client()

    response = client.post(
        "/config/llm",
        json={
            "llm_type": "unsupported",
            "api_key": "sk-test",
            "api_base": "https://api.example.test",
            "language_model": "gpt-test",
            "max_tokens": "1024",
        },
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    callbacks["apply_llm_conf"].assert_not_called()
    assert llm_settings.chat_llm_type == "openai"


def test_rerank_config_rejects_unsupported_provider_without_mutating(monkeypatch):
    monkeypatch.setattr(llm_settings, "reranker_type", "cohere")
    client, callbacks = _make_test_client()

    response = client.post(
        "/config/rerank",
        json={
            "reranker_type": "unsupported",
            "api_key": "rerank-key",
            "reranker_model": "rerank-test",
        },
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    callbacks["apply_reranker_conf"].assert_not_called()
    assert llm_settings.reranker_type == "cohere"


def test_rerank_config_rolls_back_provider_type_on_apply_failure(monkeypatch):
    monkeypatch.setattr(llm_settings, "reranker_type", "siliconflow")
    rollback_fields = (
        "reranker_type",
        "reranker_api_key",
        "reranker_model",
        "cohere_base_url",
    )
    original_values = {
        "reranker_type": "siliconflow",
        "reranker_api_key": "old-reranker-key",
        "reranker_model": "old-reranker-model",
        "cohere_base_url": "https://old-cohere.example",
    }
    for field, value in original_values.items():
        monkeypatch.setattr(llm_settings, field, value)

    def failed_apply_reranker_conf(api_key, reranker_model, cohere_base_url, **_kwargs):
        monkeypatch.setattr(llm_settings, "reranker_api_key", api_key)
        monkeypatch.setattr(llm_settings, "reranker_model", reranker_model)
        monkeypatch.setattr(llm_settings, "cohere_base_url", cohere_base_url)
        return status.HTTP_500_INTERNAL_SERVER_ERROR

    client, callbacks = _make_test_client(apply_reranker_conf=Mock(side_effect=failed_apply_reranker_conf))

    response = client.post(
        "/config/rerank",
        json={
            "reranker_type": "cohere",
            "api_key": "cohere-key",
            "reranker_model": "rerank-test",
            "cohere_base_url": "https://cohere.example.test",
        },
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert _snapshot_llm_fields(rollback_fields) == original_values
    callbacks["apply_reranker_conf"].assert_called_once()


def test_text2gremlin_callback_exception_returns_stable_response():
    client, _ = _make_test_client(gremlin_generate_selective_func=Mock(side_effect=RuntimeError("callback failed")))

    response = client.post("/text2gremlin", json={"query": "find people"})

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json() == {"detail": "An unexpected error occurred during Gremlin generation."}
