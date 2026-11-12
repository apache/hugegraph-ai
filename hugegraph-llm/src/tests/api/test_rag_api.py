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


def test_rag_api_invalid_request_body_returns_validation_shape():
    client, _ = _make_test_client()

    response = client.post("/rag", json={})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.json()["detail"][0]["loc"][-1] == "query"


def test_rag_accepts_client_config_without_mutating_globals(monkeypatch):
    monkeypatch.setattr(huge_settings, "graph_url", "http://original:8080")
    monkeypatch.setattr(huge_settings, "graph_name", "original_graph")
    monkeypatch.setattr(huge_settings, "graph_user", "original_user")
    monkeypatch.setattr(huge_settings, "graph_pwd", "original_pwd")
    monkeypatch.setattr(huge_settings, "graph_space", "original_space")
    client, callbacks = _make_test_client()

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
    assert huge_settings.graph_url == "http://original:8080"
    assert huge_settings.graph_name == "original_graph"
    assert huge_settings.graph_user == "original_user"
    assert huge_settings.graph_pwd == "original_pwd"
    assert huge_settings.graph_space == "original_space"


def test_graph_rag_accepts_client_config_without_mutating_globals(monkeypatch):
    monkeypatch.setattr(huge_settings, "graph_url", "http://original:8080")
    monkeypatch.setattr(huge_settings, "graph_name", "original_graph")
    monkeypatch.setattr(huge_settings, "graph_user", "original_user")
    monkeypatch.setattr(huge_settings, "graph_pwd", "original_pwd")
    monkeypatch.setattr(huge_settings, "graph_space", "original_space")
    client, callbacks = _make_test_client()
    response = client.post(
        "/rag/graph",
        json={
            "query": "find vertices",
            "client_config": {
                "url": "http://override:8080",
            },
        },
    )

    assert response.status_code == status.HTTP_200_OK
    callbacks["graph_rag_recall_func"].assert_called_once()
    assert huge_settings.graph_url == "http://original:8080"
    assert huge_settings.graph_name == "original_graph"
    assert huge_settings.graph_user == "original_user"
    assert huge_settings.graph_pwd == "original_pwd"
    assert huge_settings.graph_space == "original_space"


def test_text2gremlin_passes_configured_graph_target_without_mutating_globals(monkeypatch):
    monkeypatch.setattr(huge_settings, "graph_url", "http://original:8080")
    monkeypatch.setattr(huge_settings, "graph_name", "original_graph")
    monkeypatch.setattr(huge_settings, "graph_user", "original_user")
    monkeypatch.setattr(huge_settings, "graph_pwd", "original_pwd")
    monkeypatch.setattr(huge_settings, "graph_space", "original_space")
    callback = Mock(return_value={"template_gremlin": "g.V()"})
    client, _ = _make_test_client(gremlin_generate_selective_func=callback)

    response = client.post(
        "/text2gremlin",
        json={
            "query": "find vertices",
            "client_config": {
                "graph": "original_graph",
                "gs": "original_space",
            },
        },
    )

    assert response.status_code == status.HTTP_200_OK
    callback.assert_called_once()
    call = callback.call_args.kwargs
    assert call["schema_input"] == "original_graph"
    assert call["graph_client_config"] == {
        "url": "http://original:8080",
        "graph": "original_graph",
        "user": "original_user",
        "pwd": "original_pwd",
        "graphspace": "original_space",
    }
    assert huge_settings.graph_url == "http://original:8080"
    assert huge_settings.graph_name == "original_graph"
    assert huge_settings.graph_user == "original_user"
    assert huge_settings.graph_pwd == "original_pwd"
    assert huge_settings.graph_space == "original_space"


@pytest.mark.parametrize(
    "client_config, expected_field",
    [
        ({"graph": "other_graph"}, "graph"),
        ({"gs": "other_space"}, "gs"),
        ({"user": "other_user"}, "user"),
        ({"pwd": "other_pwd"}, "pwd"),
    ],
)
def test_text2gremlin_rejects_changed_graph_target(monkeypatch, client_config, expected_field):
    monkeypatch.setattr(huge_settings, "graph_name", "original_graph")
    monkeypatch.setattr(huge_settings, "graph_space", "original_space")
    callback = Mock()
    client, _ = _make_test_client(gremlin_generate_selective_func=callback)

    response = client.post(
        "/text2gremlin",
        json={"query": "find vertices", "client_config": client_config},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert expected_field in response.json()["detail"]
    callback.assert_not_called()


def test_text2gremlin_rejects_changed_graph_url(monkeypatch):
    monkeypatch.setattr(huge_settings, "graph_url", "http://original:8080")
    callback = Mock()
    client, _ = _make_test_client(gremlin_generate_selective_func=callback)

    response = client.post(
        "/text2gremlin",
        json={
            "query": "find vertices",
            "client_config": {"url": "http://attacker:8080"},
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "must match" in response.json()["detail"]
    callback.assert_not_called()


def test_text2gremlin_accepts_equivalent_graph_url(monkeypatch):
    monkeypatch.setattr(huge_settings, "graph_url", "127.0.0.1:8080")
    callback = Mock(return_value={"template_gremlin": "g.V()"})
    client, _ = _make_test_client(gremlin_generate_selective_func=callback)

    response = client.post(
        "/text2gremlin",
        json={
            "query": "find vertices",
            "client_config": {"url": "http://127.0.0.1:8080/"},
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert callback.call_args.kwargs["graph_client_config"]["url"] == "127.0.0.1:8080"


def test_text2gremlin_rejects_malformed_graph_url(monkeypatch):
    monkeypatch.setattr(huge_settings, "graph_url", "http://original:8080")
    callback = Mock()
    client, _ = _make_test_client(gremlin_generate_selective_func=callback)

    response = client.post(
        "/text2gremlin",
        json={
            "query": "find vertices",
            "client_config": {"url": "http://[::1"},
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    callback.assert_not_called()


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


def test_text2gremlin_callback_exception_returns_stable_response():
    client, _ = _make_test_client(gremlin_generate_selective_func=Mock(side_effect=RuntimeError("callback failed")))

    response = client.post("/text2gremlin", json={"query": "find people"})

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json() == {"detail": "An unexpected error occurred during Gremlin generation."}


@pytest.mark.parametrize("route", ["/rag", "/rag/graph"])
def test_inference_uses_request_prompts_without_writing_mounted_configuration(tmp_path, monkeypatch, route):
    from hugegraph_llm.config import prompt
    from hugegraph_llm.config.models import base_prompt_config
    from hugegraph_llm.demo.rag_demo import rag_block, text2gremlin_block

    mounted = tmp_path / "config_prompt.yaml"
    mounted.write_text("# operator-owned prompt\n")
    mounted.chmod(0o444)
    monkeypatch.setattr(base_prompt_config, "yaml_file_path", str(mounted))
    before = dict(vars(prompt))
    scheduler = Mock()
    scheduler.schedule_flow.return_value = {"raw_answer": "stubbed response", "query": "request question"}
    monkeypatch.setattr(rag_block.SchedulerSingleton, "get_instance", lambda: scheduler)
    client, _ = _make_test_client(
        rag_answer_func=rag_block.rag_answer,
        graph_rag_recall_func=text2gremlin_block.graph_rag_recall,
    )
    with client:
        response = client.post(
            route,
            json={
                "query": "request question",
                "raw_answer": True,
                "answer_prompt": "request-local answer prompt",
                "gremlin_prompt": "request-local gremlin prompt",
            },
        )
    assert response.status_code == 200, response.text
    scheduler.schedule_flow.assert_called_once()
    assert scheduler.schedule_flow.call_args.kwargs["query"] == "request question"
    assert scheduler.schedule_flow.call_args.kwargs["gremlin_prompt"] == "request-local gremlin prompt"
    if route == "/rag":
        assert scheduler.schedule_flow.call_args.kwargs["answer_prompt"] == "request-local answer prompt"
    assert vars(prompt) == before
    assert mounted.read_text() == "# operator-owned prompt\n"


def test_streaming_inference_does_not_persist_request_prompts(tmp_path, monkeypatch):
    import asyncio

    from hugegraph_llm.config import prompt
    from hugegraph_llm.config.models import base_prompt_config
    from hugegraph_llm.demo.rag_demo import rag_block

    mounted = tmp_path / "config_prompt.yaml"
    mounted.write_text("# operator-owned prompt\n")
    mounted.chmod(0o444)
    monkeypatch.setattr(base_prompt_config, "yaml_file_path", str(mounted))
    before = dict(vars(prompt))

    async def stream(*args, **kwargs):
        assert kwargs["query"] == "stream question"
        assert kwargs["answer_prompt"] == "request-local prompt"
        yield {"raw_answer": "stubbed stream"}

    monkeypatch.setattr(rag_block.SchedulerSingleton, "get_instance", lambda: Mock(schedule_stream_flow=stream))

    async def consume():
        return [
            item
            async for item in rag_block.rag_answer_streaming(
                "stream question",
                True,
                False,
                False,
                False,
                0.5,
                "bleu",
                False,
                "request-local information",
                "request-local prompt",
                "request-local keywords",
            )
        ]

    assert asyncio.run(consume())
    assert vars(prompt) == before
    assert mounted.read_text() == "# operator-owned prompt\n"


def test_batch_upload_creates_output_directory_on_fresh_volume(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import gradio as gr
    import pandas as pd

    from hugegraph_llm.demo.rag_demo import rag_block

    root = tmp_path / "fresh-resource-root"
    monkeypatch.setattr(rag_block, "resource_path", str(root))
    with gr.Blocks() as ui:
        rag_block.create_rag_block()
    upload = next(function.fn for function in ui.fns.values() if function.fn.__name__ == "read_file_to_excel")
    csv = tmp_path / "questions.csv"
    csv.write_text("Question,Expected Answer,Basic,Vector,Graph,Combined\nquestion,expected,,,,\n")
    assert not root.exists()
    frame, count = upload(SimpleNamespace(name=str(csv)))
    assert count == 1
    assert frame.iloc[0, 0] == "question"
    assert pd.read_excel(root / "demo/questions.xlsx").iloc[0, 0] == "question"


def test_rag_default_response_has_no_trace_field():
    client, _ = _make_test_client()
    response = client.post("/rag", json={"query": "q"})
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert "trace" not in body
    assert body["graph_only"] == "graph"


def test_rag_include_trace_returns_graph_recall_fields():
    trace = {
        "keywords": ["alice"],
        "match_vids": ["1:alice"],
        "graph_result_flag": 1,
        "gremlin": "g.V().limit(1)",
        "graph_result": [{"id": "1:alice"}],
        "vertex_degree_list": [],
    }
    client, callbacks = _make_test_client(
        rag_answer_func=Mock(return_value=("raw", "vector", "graph", "graph_vector", trace))
    )
    response = client.post("/rag", json={"query": "q", "include_trace": True})
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["trace"] == trace
    # the answer fields keep their previous shape and output-flag filtering
    assert body["graph_only"] == "graph"
    assert "raw_answer" not in body
    assert callbacks["rag_answer_func"].call_args.kwargs["include_trace"] is True
