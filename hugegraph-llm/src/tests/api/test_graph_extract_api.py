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
from fastapi import APIRouter, FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from pydantic import ValidationError

from hugegraph_llm.api.graph_extract_api import GraphExtractService, graph_extract_http_api
from hugegraph_llm.api.models.graph_extract_requests import GraphExtractClientConfig, GraphExtractRequest
from hugegraph_llm.api.models.graph_extract_responses import GraphExtractResponse
from hugegraph_llm.api.rag_api import rag_http_api
from hugegraph_llm.config import huge_settings
from hugegraph_llm.flows.graph_extract import GraphExtractFlow
from hugegraph_llm.state.ai_state import WkFlowInput

INLINE_SCHEMA = {"vertexlabels": [], "edgelabels": []}


class CapturePipeline:
    def __init__(self):
        self.params = {}

    def createGParam(self, value, name):
        self.params[name] = value

    def registerGElement(self, *args):
        return None


def _graph_client():
    router = APIRouter()
    graph_extract_http_api(router)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _named_client_config(graph="custom_graph"):
    return {"graph": graph, "user": "admin", "pwd": "secret", "gs": "space_a"}


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_graph_extract_returns_envelope(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.return_value = json.dumps({"vertices": [{"id": "1"}], "edges": []})
    mock_singleton.get_instance.return_value = scheduler

    response = _graph_client().post(
        "/graph/extract",
        json={"texts": "张三在北京工作。", "schema": INLINE_SCHEMA, "include_meta": True},
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["result"] == {"vertices": [{"id": "1"}], "edges": []}
    assert body["warnings"] == []
    assert body["meta"] == {"vertex_count": 1, "edge_count": 0, "text_count": 1}


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_graph_extract_omits_meta_by_default(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.return_value = json.dumps({"vertices": [], "edges": []})
    mock_singleton.get_instance.return_value = scheduler

    response = _graph_client().post("/graph/extract", json={"texts": "x", "schema": INLINE_SCHEMA})

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["meta"] == {}


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_graph_extract_moves_warning_into_warnings(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.return_value = json.dumps(
        {"vertices": [], "edges": [], "warning": "The schema may not match the Doc"}
    )
    mock_singleton.get_instance.return_value = scheduler

    response = _graph_client().post("/graph/extract", json={"texts": "x", "schema": INLINE_SCHEMA})

    body = response.json()
    assert body["warnings"] == ["The schema may not match the Doc"]
    assert "warning" not in body["result"]


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_graph_extract_accepts_text_and_list(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.return_value = json.dumps({"vertices": [], "edges": []})
    mock_singleton.get_instance.return_value = scheduler

    client = _graph_client()
    client.post("/graph/extract", json={"texts": "single", "schema": INLINE_SCHEMA})
    assert scheduler.schedule_flow.call_args.args[2] == ["single"]

    client.post("/graph/extract", json={"texts": ["a", "b"], "schema": INLINE_SCHEMA})
    assert scheduler.schedule_flow.call_args.args[2] == ["a", "b"]


def test_graph_extract_rejects_empty_texts():
    response = _graph_client().post("/graph/extract", json={"texts": "  ", "schema": INLINE_SCHEMA})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_rejects_invalid_schema():
    response = _graph_client().post("/graph/extract", json={"texts": "x", "schema": "{bad"})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_rejects_incomplete_schema():
    response = _graph_client().post("/graph/extract", json={"texts": "x", "schema": {"vertexlabels": []}})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_graph_extract_rejects_malformed_inline_schema_before_scheduler(mock_singleton):
    response = _graph_client().post(
        "/graph/extract",
        json={"texts": "x", "schema": {"vertexlabels": [{"name": "person"}], "edgelabels": []}},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    mock_singleton.get_instance.assert_not_called()


def test_graph_extract_rejects_invalid_split_type():
    response = _graph_client().post(
        "/graph/extract",
        json={"texts": "x", "schema": INLINE_SCHEMA, "split_type": "doc"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_rejects_triples_extract_type():
    response = _graph_client().post(
        "/graph/extract",
        json={"texts": "x", "schema": INLINE_SCHEMA, "extract_type": "triples"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_rejects_named_schema_without_client_config():
    response = _graph_client().post("/graph/extract", json={"texts": "x", "schema": "hugegraph"})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_rejects_client_config_with_inline_schema():
    response = _graph_client().post(
        "/graph/extract",
        json={"texts": "x", "schema": INLINE_SCHEMA, "client_config": _named_client_config()},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_rejects_mismatched_schema_and_client_config_graph():
    response = _graph_client().post(
        "/graph/extract",
        json={"texts": "x", "schema": "custom_graph", "client_config": _named_client_config("other_graph")},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_rejects_url_in_client_config():
    response = _graph_client().post(
        "/graph/extract",
        json={
            "texts": "x",
            "schema": "custom_graph",
            "client_config": {"graph": "custom_graph", "url": "10.0.0.1:8080"},
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_graph_extract_named_schema_does_not_mutate_globals(mock_singleton):
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
    response = _graph_client().post(
        "/graph/extract",
        json={"texts": "x", "schema": "custom_graph", "client_config": _named_client_config()},
    )

    assert response.status_code == status.HTTP_200_OK
    assert (
        huge_settings.graph_url,
        huge_settings.graph_name,
        huge_settings.graph_user,
        huge_settings.graph_pwd,
        huge_settings.graph_space,
    ) == original
    assert scheduler.schedule_flow.call_args.kwargs["client_config"].graph == "custom_graph"


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_graph_extract_scheduler_error_returns_500(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.side_effect = RuntimeError("Error in flow init")
    mock_singleton.get_instance.return_value = scheduler

    response = _graph_client().post("/graph/extract", json={"texts": "x", "schema": INLINE_SCHEMA})
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_service_extract_sync_builds_envelope(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.return_value = json.dumps({"vertices": [{"id": "1"}], "edges": []})
    mock_singleton.get_instance.return_value = scheduler

    resp = GraphExtractService.extract_sync(GraphExtractRequest(texts="x", schema=INLINE_SCHEMA, include_meta=True))

    assert isinstance(resp, GraphExtractResponse)
    assert resp.status == "succeeded"
    assert resp.result == {"vertices": [{"id": "1"}], "edges": []}
    assert resp.warnings == []
    assert resp.meta == {"vertex_count": 1, "edge_count": 0, "text_count": 1}


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_service_extract_sync_maps_errors_to_500(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.side_effect = RuntimeError("boom")
    mock_singleton.get_instance.return_value = scheduler

    with pytest.raises(HTTPException) as exc_info:
        GraphExtractService.extract_sync(GraphExtractRequest(texts="x", schema=INLINE_SCHEMA))
    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_request_model_validation():
    req = GraphExtractRequest(texts="hello", schema=INLINE_SCHEMA)
    assert req.texts == ["hello"]
    assert req.graph_schema == json.dumps(INLINE_SCHEMA, ensure_ascii=False)
    assert req.client_config is None

    with pytest.raises(ValidationError):
        GraphExtractRequest(texts=[], schema="hugegraph")


def test_request_model_named_schema_requires_matching_client_config():
    with pytest.raises(ValidationError):
        GraphExtractRequest(texts="hello", schema="hugegraph")

    with pytest.raises(ValidationError):
        GraphExtractRequest(
            texts="hello",
            schema="custom_graph",
            client_config=GraphExtractClientConfig(graph="other_graph"),
        )

    req = GraphExtractRequest(
        texts="hello",
        schema="hugegraph",
        client_config=GraphExtractClientConfig(graph="hugegraph", user="admin", pwd="secret", gs="space_a"),
    )
    assert req.client_config.graph == "hugegraph"


def test_request_model_rejects_client_config_with_inline_schema():
    with pytest.raises(ValidationError):
        GraphExtractRequest(
            texts="hello",
            schema=INLINE_SCHEMA,
            client_config=GraphExtractClientConfig(graph="hugegraph"),
        )


def test_client_config_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        GraphExtractClientConfig(graph="custom_graph", url="10.0.0.1:8080")


def test_flow_prepare_sets_request_local_graph_config():
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()
    client_config = GraphExtractClientConfig(graph="custom_graph", user="admin", pwd="secret", gs="space_a")

    flow.prepare(prepared_input, "custom_graph", ["text"], "prompt", "property_graph", client_config=client_config)

    assert prepared_input.graph_client_config == {
        "url": huge_settings.graph_url,
        "user": "admin",
        "pwd": "secret",
        "graphspace": "space_a",
    }


def test_flow_prepare_keeps_omitted_graphspace_none():
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()
    client_config = GraphExtractClientConfig(graph="custom_graph", user="admin", pwd="secret")

    flow.prepare(prepared_input, "custom_graph", ["text"], "prompt", "property_graph", client_config=client_config)

    assert prepared_input.graph_client_config["graphspace"] is None


def test_request_defaults_extract_strategy_to_baseline():
    req = GraphExtractRequest(texts="hello", schema=INLINE_SCHEMA)
    assert req.extract_strategy == "baseline"
    assert req.include_debug is False


def test_request_accepts_explicit_baseline_and_enhanced_strategy():
    baseline_req = GraphExtractRequest(texts="hello", schema=INLINE_SCHEMA, extract_strategy="baseline")
    enhanced_req = GraphExtractRequest(
        texts="hello",
        schema=INLINE_SCHEMA,
        extract_strategy="enhanced",
        include_debug=True,
    )
    assert baseline_req.extract_strategy == "baseline"
    assert baseline_req.include_debug is False
    assert enhanced_req.extract_strategy == "enhanced"
    assert enhanced_req.include_debug is True


def test_graph_extract_rejects_unknown_extract_strategy():
    response = _graph_client().post(
        "/graph/extract",
        json={"texts": "x", "schema": INLINE_SCHEMA, "extract_strategy": "aggressive"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_graph_extract_threads_strategy_and_debug_into_scheduler_kwargs(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.return_value = json.dumps({"vertices": [], "edges": []})
    mock_singleton.get_instance.return_value = scheduler

    response = _graph_client().post(
        "/graph/extract",
        json={
            "texts": "x",
            "schema": INLINE_SCHEMA,
            "extract_strategy": "enhanced",
            "include_debug": True,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    kwargs = scheduler.schedule_flow.call_args.kwargs
    assert kwargs["extract_strategy"] == "enhanced"
    assert kwargs["include_debug"] is True


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_graph_extract_defaults_baseline_strategy_when_field_omitted(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.return_value = json.dumps({"vertices": [], "edges": []})
    mock_singleton.get_instance.return_value = scheduler

    response = _graph_client().post("/graph/extract", json={"texts": "x", "schema": INLINE_SCHEMA})

    assert response.status_code == status.HTTP_200_OK
    kwargs = scheduler.schedule_flow.call_args.kwargs
    assert kwargs["extract_strategy"] == "baseline"
    assert kwargs["include_debug"] is False


def test_flow_prepare_captures_extract_strategy_and_include_debug():
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()

    flow.prepare(
        prepared_input,
        json.dumps(INLINE_SCHEMA),
        ["text"],
        "prompt",
        "property_graph",
        extract_strategy="enhanced",
        include_debug=True,
    )

    assert prepared_input.extract_strategy == "enhanced"
    assert prepared_input.include_debug is True


def test_flow_prepare_defaults_extract_strategy_and_include_debug():
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()

    flow.prepare(
        prepared_input,
        json.dumps(INLINE_SCHEMA),
        ["text"],
        "prompt",
        "property_graph",
    )

    assert prepared_input.extract_strategy == "baseline"
    assert prepared_input.include_debug is False


def test_wkflow_input_reset_clears_enhanced_strategy_fields():
    prepared_input = WkFlowInput()
    prepared_input.extract_strategy = "enhanced"
    prepared_input.include_debug = True

    from pycgraph import CStatus  # local import to avoid polluting module namespace

    prepared_input.reset(CStatus())

    assert prepared_input.extract_strategy is None
    assert prepared_input.include_debug is None


# ==============================================================================
# Enhanced-strategy envelope
# ==============================================================================


def _enhanced_scheduler_payload(*, structured_warnings=None, quality_metrics=None, debug_info=None):
    """Mimic what GraphExtractFlow.post_deal emits under enhanced strategy."""
    payload = {
        "vertices": [{"id": "1:Tom", "label": "person", "properties": {"name": "Tom"}}],
        "edges": [],
        "extract_strategy": "enhanced",
        "chunk_count": 2,
        "call_count": 2,
    }
    if structured_warnings is not None:
        payload["structured_warnings"] = structured_warnings
    if quality_metrics is not None:
        payload["quality_metrics"] = quality_metrics
    if debug_info is not None:
        payload["debug_info"] = debug_info
    return json.dumps(payload)


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_enhanced_meta_carries_strategy_chunk_call_token_usage(mock_singleton):
    scheduler = MagicMock()
    scheduler.schedule_flow.return_value = _enhanced_scheduler_payload(
        structured_warnings=[],
        quality_metrics={"schema_valid_vertex_ratio": 1.0},
    )
    mock_singleton.get_instance.return_value = scheduler

    response = _graph_client().post(
        "/graph/extract",
        json={
            "texts": "some text",
            "schema": INLINE_SCHEMA,
            "extract_strategy": "enhanced",
            "include_meta": True,
        },
    )

    body = response.json()
    assert response.status_code == status.HTTP_200_OK
    assert body["meta"]["extract_strategy"] == "enhanced"
    assert body["meta"]["chunk_count"] == 2
    assert body["meta"]["call_count"] == 2
    assert body["meta"]["token_usage"] == "unavailable"


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_enhanced_structured_warnings_and_quality_metrics_in_meta(mock_singleton):
    warnings_payload = [
        {"code": "PROPERTY_COERCED", "item_type": "vertex", "reason": "x", "strategy": "enhanced"},
        {"code": "DUPLICATE_VERTEX_MERGED", "item_type": "vertex", "reason": "y", "strategy": "enhanced"},
    ]
    metrics_payload = {
        "schema_valid_vertex_ratio": 1.0,
        "duplicate_vertex_reduction": 0.5,
    }
    scheduler = MagicMock()
    scheduler.schedule_flow.return_value = _enhanced_scheduler_payload(
        structured_warnings=warnings_payload,
        quality_metrics=metrics_payload,
    )
    mock_singleton.get_instance.return_value = scheduler

    response = _graph_client().post(
        "/graph/extract",
        json={
            "texts": "t",
            "schema": INLINE_SCHEMA,
            "extract_strategy": "enhanced",
            "include_meta": True,
        },
    )

    body = response.json()
    assert body["meta"]["structured_warnings"] == warnings_payload
    assert body["meta"]["quality_metrics"] == metrics_payload
    # Top-level warnings surface a short summary of the structured warning count.
    assert any("structured warning" in w for w in body["warnings"])


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_enhanced_debug_info_only_when_include_debug(mock_singleton):
    debug_payload = {
        "chunks": [{"chunk_id": 0, "raw_output": "..."}],
        "warning_code_distribution": {"PROPERTY_COERCED": 1},
    }
    scheduler = MagicMock()
    scheduler.schedule_flow.return_value = _enhanced_scheduler_payload(
        structured_warnings=[],
        quality_metrics={},
        debug_info=debug_payload,
    )
    mock_singleton.get_instance.return_value = scheduler

    # include_debug=false → no debug_info in meta.
    response = _graph_client().post(
        "/graph/extract",
        json={
            "texts": "t",
            "schema": INLINE_SCHEMA,
            "extract_strategy": "enhanced",
            "include_meta": True,
        },
    )
    assert "debug_info" not in response.json()["meta"]

    # include_debug=true → debug_info populated even without include_meta.
    scheduler.schedule_flow.return_value = _enhanced_scheduler_payload(
        structured_warnings=[],
        quality_metrics={},
        debug_info=debug_payload,
    )
    response = _graph_client().post(
        "/graph/extract",
        json={
            "texts": "t",
            "schema": INLINE_SCHEMA,
            "extract_strategy": "enhanced",
            "include_debug": True,
        },
    )
    body = response.json()
    assert body["meta"]["debug_info"] == debug_payload


@patch("hugegraph_llm.api.graph_extract_api.SchedulerSingleton")
def test_baseline_response_untouched_when_extract_strategy_is_baseline(mock_singleton):
    """Regression: baseline meta must stay byte-identical to the pre-enhanced shape."""
    scheduler = MagicMock()
    scheduler.schedule_flow.return_value = json.dumps({"vertices": [{"id": "v1"}], "edges": []})
    mock_singleton.get_instance.return_value = scheduler

    response = _graph_client().post(
        "/graph/extract",
        json={"texts": "t", "schema": INLINE_SCHEMA, "include_meta": True},
    )
    body = response.json()
    # Only the three baseline counts, nothing else.
    assert body["meta"] == {"vertex_count": 1, "edge_count": 0, "text_count": 1}
    assert body["warnings"] == []


def test_flow_prepare_does_not_leak_config_across_runs():
    # A pooled pipeline is reused across requests, so prepare() must clear config
    # when a later request omits client_config.
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()
    client_config = GraphExtractClientConfig(graph="custom_graph", user="admin", pwd="secret", gs="space_a")

    flow.prepare(prepared_input, "custom_graph", ["text"], "prompt", "property_graph", client_config=client_config)
    assert prepared_input.graph_client_config is not None

    flow.prepare(prepared_input, "custom_graph", ["text"], "prompt", "property_graph")
    assert prepared_input.graph_client_config is None


def test_flow_build_flow_preserves_split_type_and_client_config(monkeypatch):
    monkeypatch.setattr(
        "hugegraph_llm.flows.graph_extract.GPipeline",
        CapturePipeline,
    )
    client_config = GraphExtractClientConfig(graph="custom_graph", user="admin", pwd="secret", gs="space_a")

    pipeline = GraphExtractFlow().build_flow(
        "custom_graph",
        ["text"],
        "prompt",
        "property_graph",
        split_type="paragraph",
        client_config=client_config,
    )

    prepared_input = pipeline.params["wkflow_input"]
    assert prepared_input.split_type == "paragraph"
    assert prepared_input.graph_client_config == {
        "url": huge_settings.graph_url,
        "user": "admin",
        "pwd": "secret",
        "graphspace": "space_a",
    }


def test_wkflow_input_reset_clears_graph_client_config():
    prepared_input = WkFlowInput()
    prepared_input.graph_client_config = {"url": "10.0.0.1:8080"}

    prepared_input.reset(None)

    assert prepared_input.graph_client_config is None


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
    graph_extract_http_api(router)
    app = FastAPI()
    app.include_router(router)

    paths = set(app.openapi()["paths"])
    assert "/rag" in paths
    assert "/text2gremlin" in paths
    assert "/config/graph" in paths
    assert "/graph/extract" in paths
