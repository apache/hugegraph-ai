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

from fastapi import APIRouter, FastAPI, status
from fastapi.testclient import TestClient

from hugegraph_llm.api.models.rag_requests import RAGRequest
from hugegraph_llm.api.models.rag_response import RAGTrace, serialize_rag_trace
from hugegraph_llm.api.rag_api import build_rag_api_response, rag_http_api
from hugegraph_llm.flows.common import graph_trace_payload
from hugegraph_llm.flows.rag_flow_graph_only import RAGGraphOnlyFlow
from hugegraph_llm.flows.rag_flow_graph_vector import RAGGraphVectorFlow
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


def _rag_client(rag_answer_func):
    router = APIRouter()
    rag_http_api(
        router,
        rag_answer_func=rag_answer_func,
        graph_rag_recall_func=Mock(),
        apply_graph_conf=Mock(),
        apply_llm_conf=Mock(),
        apply_embedding_conf=Mock(),
        apply_reranker_conf=Mock(),
        gremlin_generate_selective_func=Mock(),
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


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


def test_rag_default_response_has_no_trace():
    rag_answer = Mock(return_value=("", "", "graph answer", ""))
    response = _rag_client(rag_answer).post("/rag", json={"query": "hello", "graph_only": True})

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body == {"query": "hello", "graph_only": "graph answer"}
    assert "trace" not in body


def test_rag_include_trace_returns_graph_debug_fields():
    rag_answer = Mock(
        return_value={
            "graph_only_answer": "graph answer",
            "trace": {
                "keywords": ["hello"],
                "match_vids": ["1:foo"],
                "gremlin": "g.V()",
            },
        }
    )
    response = _rag_client(rag_answer).post(
        "/rag",
        json={"query": "hello", "graph_only": True, "include_trace": True},
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["graph_only"] == "graph answer"
    assert body["trace"]["keywords"] == ["hello"]
    assert body["trace"]["match_vids"] == ["1:foo"]
    rag_answer.assert_called_once()
    assert rag_answer.call_args.kwargs["include_trace"] is True


def test_rag_include_trace_returns_graph_debug_fields_for_graph_vector_answer():
    rag_answer = Mock(
        return_value={
            "graph_vector_answer": "hybrid answer",
            "trace": {
                "keywords": ["hello"],
                "match_vids": ["1:foo"],
                "gremlin": "g.V()",
            },
        }
    )
    response = _rag_client(rag_answer).post(
        "/rag",
        json={
            "query": "hello",
            "graph_only": False,
            "graph_vector_answer": True,
            "include_trace": True,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["graph_vector_answer"] == "hybrid answer"
    assert body["trace"]["keywords"] == ["hello"]
    assert body["trace"]["gremlin"] == "g.V()"


def test_rag_include_trace_skipped_for_vector_only():
    rag_answer = Mock(return_value=("", "vector answer", "", ""))
    response = _rag_client(rag_answer).post(
        "/rag",
        json={"query": "hello", "graph_only": False, "vector_only": True, "include_trace": True},
    )

    assert response.status_code == status.HTTP_200_OK
    assert "trace" not in response.json()


def test_graph_trace_payload_excludes_prompts_and_secrets():
    trace = graph_trace_payload(
        {
            "keywords": ["a"],
            "gremlin": "g.V()",
            "answer_prompt": "secret prompt",
            "graph_pwd": "secret",
        }
    )
    assert trace == {"keywords": ["a"], "gremlin": "g.V()"}


def test_serialize_rag_trace_omits_none_fields():
    trace = serialize_rag_trace({"keywords": ["a"], "gremlin": None})
    assert trace == {"keywords": ["a"]}
    assert RAGTrace(**trace).keywords == ["a"]


def test_build_rag_api_response_supports_legacy_tuple():
    req = RAGRequest(query="hello", graph_only=True)
    response = build_rag_api_response(req, ("", "", "graph answer", ""))
    assert response == {"query": "hello", "graph_only": "graph answer"}


def test_rag_graph_only_post_deal_include_trace():
    pipeline = Mock()
    state = WkFlowState()
    state.graph_only_answer = "answer"
    state.keywords = ["kw"]
    state.gremlin = "g.V()"
    wk_input = WkFlowInput()
    wk_input.include_trace = True

    def get_param(name):
        return wk_input if name == "wkflow_input" else state

    pipeline.getGParamWithNoEmpty.side_effect = get_param

    result = RAGGraphOnlyFlow().post_deal(pipeline)
    assert result["graph_only_answer"] == "answer"
    assert result["trace"]["keywords"] == ["kw"]
    assert result["trace"]["gremlin"] == "g.V()"


def test_rag_graph_vector_post_deal_include_trace():
    pipeline = Mock()
    state = WkFlowState()
    state.graph_vector_answer = "hybrid answer"
    state.keywords = ["kw"]
    state.match_vids = ["1:foo"]
    wk_input = WkFlowInput()
    wk_input.include_trace = True

    def get_param(name):
        return wk_input if name == "wkflow_input" else state

    pipeline.getGParamWithNoEmpty.side_effect = get_param

    result = RAGGraphVectorFlow().post_deal(pipeline)
    assert result["graph_vector_answer"] == "hybrid answer"
    assert result["trace"]["keywords"] == ["kw"]
    assert result["trace"]["match_vids"] == ["1:foo"]
