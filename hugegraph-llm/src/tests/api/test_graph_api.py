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
from hugegraph_llm.api.models.rag_requests import GraphExtractRequest
from hugegraph_llm.api.rag_api import rag_http_api
from hugegraph_llm.flows import FlowName


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
        json={"texts": "张三在北京工作。", "schema": {"vertexlabels": []}, "include_meta": True},
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert isinstance(body["vertices"], list)
    assert isinstance(body["edges"], list)
    assert body["meta"] == {"vertex_count": 1, "edge_count": 0, "text_count": 1}

    args, kwargs = scheduler.schedule_flow.call_args
    assert args[0] == FlowName.GRAPH_EXTRACT
    assert args[1] == json.dumps({"vertexlabels": []}, ensure_ascii=False)
    assert args[2] == ["张三在北京工作。"]
    assert kwargs["split_type"] == "document"


def test_graph_extract_rejects_empty_texts():
    response = _graph_client().post("/graph/extract", json={"texts": "  ", "schema": "hugegraph"})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_rejects_invalid_schema():
    response = _graph_client().post("/graph/extract", json={"texts": "x", "schema": "{bad"})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_rejects_invalid_split_type():
    response = _graph_client().post(
        "/graph/extract",
        json={"texts": "x", "schema": "hugegraph", "split_type": "doc"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@patch("hugegraph_llm.api.graph_api.SchedulerSingleton")
def test_graph_extract_scheduler_error_returns_500(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.side_effect = RuntimeError("Error in flow init")
    mock_singleton.get_instance.return_value = scheduler

    response = _graph_client().post("/graph/extract", json={"texts": "x", "schema": "hugegraph"})
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_graph_extract_request_model_validation():
    req = GraphExtractRequest(texts="hello", schema={"vertexlabels": []})
    assert req.texts == ["hello"]
    assert req.graph_schema == json.dumps({"vertexlabels": []}, ensure_ascii=False)

    with pytest.raises(ValidationError):
        GraphExtractRequest(texts=[], schema="hugegraph")


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
