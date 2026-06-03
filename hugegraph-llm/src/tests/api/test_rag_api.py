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
from hugegraph_llm.config import llm_settings

pytestmark = pytest.mark.contract


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


def test_text2gremlin_callback_exception_returns_stable_response():
    client, _ = _make_test_client(gremlin_generate_selective_func=Mock(side_effect=RuntimeError("callback failed")))

    response = client.post("/text2gremlin", json={"query": "find people"})

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json() == {"detail": "An unexpected error occurred during Gremlin generation."}
