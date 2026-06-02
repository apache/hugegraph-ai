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

import json
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import APIRouter, FastAPI, status
from fastapi.testclient import TestClient
from pydantic import ValidationError

from hugegraph_llm.api.graph_api import graph_http_api
from hugegraph_llm.api.models.rag_requests import GraphConfigRequest, GraphExtractRequest
from hugegraph_llm.api.rag_api import rag_http_api
from hugegraph_llm.config import huge_settings
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.graph_extract import GraphExtractFlow
from hugegraph_llm.state.ai_state import WkFlowInput


def _graph_client():
    router = APIRouter()
    graph_http_api(router)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@patch("hugegraph_llm.api.graph_api.SchedulerSingleton")
def test_graph_extract_returns_arrays(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.return_value = json.dumps({"vertices": [{"id": "1"}], "edges": []})
    mock_singleton.get_instance.return_value = scheduler

    response = _graph_client().post(
        "/graph/extract",
        json={"texts": "张三在北京工作。", "schema": {"vertexlabels": [], "edgelabels": []}, "include_meta": True},
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert isinstance(body["vertices"], list)
    assert isinstance(body["edges"], list)
    assert body["meta"] == {"vertex_count": 1, "edge_count": 0, "text_count": 1}

    args, kwargs = scheduler.schedule_flow.call_args
    assert args[0] == FlowName.GRAPH_EXTRACT
    assert args[1] == json.dumps({"vertexlabels": [], "edgelabels": []}, ensure_ascii=False)
    assert args[2] == ["张三在北京工作。"]
    assert kwargs["split_type"] == "document"


def test_graph_extract_rejects_empty_texts():
    response = _graph_client().post("/graph/extract", json={"texts": "  ", "schema": "hugegraph"})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_rejects_invalid_schema():
    response = _graph_client().post("/graph/extract", json={"texts": "x", "schema": "{bad"})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_rejects_incomplete_schema():
    response = _graph_client().post("/graph/extract", json={"texts": "x", "schema": {"vertexlabels": []}})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_rejects_invalid_split_type():
    response = _graph_client().post(
        "/graph/extract",
        json={"texts": "x", "schema": {"vertexlabels": [], "edgelabels": []}, "split_type": "doc"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_rejects_named_schema_without_client_config():
    response = _graph_client().post("/graph/extract", json={"texts": "x", "schema": "hugegraph"})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@patch("hugegraph_llm.api.graph_api.SchedulerSingleton")
def test_graph_extract_scheduler_error_returns_500(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.side_effect = RuntimeError("Error in flow init")
    mock_singleton.get_instance.return_value = scheduler

    response = _graph_client().post(
        "/graph/extract",
        json={"texts": "x", "schema": {"vertexlabels": [], "edgelabels": []}},
    )
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_graph_extract_request_model_validation():
    req = GraphExtractRequest(texts="hello", schema={"vertexlabels": [], "edgelabels": []})
    assert req.texts == ["hello"]
    assert req.graph_schema == json.dumps({"vertexlabels": [], "edgelabels": []}, ensure_ascii=False)
    assert req.client_config is None

    with pytest.raises(ValidationError):
        GraphExtractRequest(texts=[], schema="hugegraph")


def test_graph_extract_request_named_schema_requires_client_config():
    with pytest.raises(ValidationError):
        GraphExtractRequest(texts="hello", schema="hugegraph")

    req = GraphExtractRequest(
        texts="hello",
        schema="hugegraph",
        client_config=GraphConfigRequest(
            url="10.0.0.1:8080",
            graph="hugegraph",
            user="admin",
            pwd="secret",
            gs="space_a",
        ),
    )
    assert req.client_config is not None


@patch("hugegraph_llm.api.graph_api.SchedulerSingleton")
def test_graph_extract_passes_client_config_to_scheduler(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.return_value = json.dumps({"vertices": [], "edges": []})
    mock_singleton.get_instance.return_value = scheduler

    original = (
        huge_settings.graph_url,
        huge_settings.graph_name,
        huge_settings.graph_user,
        huge_settings.graph_pwd,
        huge_settings.graph_space,
    )
    try:
        response = _graph_client().post(
            "/graph/extract",
            json={
                "texts": "x",
                "schema": "custom_graph",
                "client_config": {
                    "url": "10.0.0.1:8080",
                    "graph": "custom_graph",
                    "user": "admin",
                    "pwd": "secret",
                    "gs": "space_a",
                },
            },
        )
        assert response.status_code == status.HTTP_200_OK
        assert (
            huge_settings.graph_url,
            huge_settings.graph_name,
            huge_settings.graph_user,
            huge_settings.graph_pwd,
            huge_settings.graph_space,
        ) == original

        _, kwargs = scheduler.schedule_flow.call_args
        client_config = kwargs["client_config"]
        assert client_config.url == "10.0.0.1:8080"
        assert client_config.graph == "custom_graph"
        assert client_config.user == "admin"
        assert client_config.pwd == "secret"
        assert client_config.gs == "space_a"
    finally:
        (
            huge_settings.graph_url,
            huge_settings.graph_name,
            huge_settings.graph_user,
            huge_settings.graph_pwd,
            huge_settings.graph_space,
        ) = original


def test_graph_extract_flow_prepare_sets_request_local_graph_config():
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()
    client_config = GraphConfigRequest(
        url="10.0.0.1:8080",
        graph="custom_graph",
        user="admin",
        pwd="secret",
        gs="space_a",
    )

    flow.prepare(
        prepared_input,
        "custom_graph",
        ["text"],
        "prompt",
        "property_graph",
        client_config=client_config,
    )

    assert prepared_input.graph_url == "10.0.0.1:8080"
    assert prepared_input.graph_user == "admin"
    assert prepared_input.graph_pwd == "secret"
    assert prepared_input.graph_space == "space_a"


def test_graph_extract_flow_prepare_clears_graph_config_when_missing():
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()
    prepared_input.graph_url = "stale"
    prepared_input.graph_user = "stale"
    prepared_input.graph_pwd = "stale"
    prepared_input.graph_space = "stale"

    flow.prepare(prepared_input, "custom_graph", ["text"], "prompt", "property_graph")

    assert prepared_input.graph_url is None
    assert prepared_input.graph_user is None
    assert prepared_input.graph_pwd is None
    assert prepared_input.graph_space is None


def test_graph_extract_flow_prepare_does_not_leak_config_across_runs():
    # A pooled pipeline is reused across requests, so prepare() must not let a
    # configured request's connection settings leak into a later request that
    # omits client_config.
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()
    client_config = GraphConfigRequest(
        url="10.0.0.1:8080",
        graph="custom_graph",
        user="admin",
        pwd="secret",
        gs="space_a",
    )

    flow.prepare(
        prepared_input,
        "custom_graph",
        ["text"],
        "prompt",
        "property_graph",
        client_config=client_config,
    )
    assert prepared_input.graph_url == "10.0.0.1:8080"

    flow.prepare(prepared_input, "custom_graph", ["text"], "prompt", "property_graph")

    assert prepared_input.graph_url is None
    assert prepared_input.graph_user is None
    assert prepared_input.graph_pwd is None
    assert prepared_input.graph_space is None


def test_existing_routes_still_register():
    router = APIRouter()
    rag_http_api(
        router,
        rag_answer_func=Mock(),
        graph_rag_recall_func=Mock(),
        apply_graph_conf=Mock(),
        apply_llm_conf=Mock(),
        apply_embedding_conf=Mock(),
        apply_reranker_conf=Mock(),
        gremlin_generate_selective_func=Mock(),
    )
    graph_http_api(router)
    app = FastAPI()
    app.include_router(router)

    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/rag" in paths
    assert "/text2gremlin" in paths
    assert "/config/graph" in paths
    assert "/graph/extract" in paths
