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
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, FastAPI, status
from fastapi.testclient import TestClient
from pydantic import ValidationError

from hugegraph_llm.api.graph_extract_api import graph_extract_http_api
from hugegraph_llm.api.models.graph_extract_requests import GraphExtractClientConfig, GraphExtractRequest
from hugegraph_llm.api.models.graph_extract_responses import GraphExtractResponse
from hugegraph_llm.config import huge_settings, llm_settings
from hugegraph_llm.flows.graph_extract import GraphExtractFlow
from hugegraph_llm.services.graph_extract_service import (
    FlowOutputValidationError,
    GraphExtractService,
    normalize_schema,
)
from hugegraph_llm.state.ai_state import WkFlowInput

INLINE_SCHEMA = {"vertexlabels": [], "edgelabels": []}
VALID_SCHEMA = {
    "vertexlabels": [{"name": "person", "properties": ["name"]}],
    "edgelabels": [{"name": "knows", "source_label": "person", "target_label": "person"}],
}


class CapturePipeline:
    def __init__(self):
        self.params = {}

    def createGParam(self, value, name):
        self.params[name] = value

    def registerGElement(self, *args):
        return None


class EchoGraphExtractService:
    def __init__(self):
        self.requests = []
        self._lock = Lock()

    def extract_sync(self, req):
        with self._lock:
            self.requests.append(
                {
                    "content_type": req.content_type,
                    "texts": list(req.texts),
                    "max_parallel_chunks": req.max_parallel_chunks,
                    "client_config": req.client_config.model_dump() if req.client_config else None,
                }
            )
        chunk_count = len(req.texts)
        return GraphExtractResponse(
            status="succeeded",
            result={"vertices": [], "edges": []},
            warnings=[],
            meta={
                "content_type": req.content_type,
                "chunk_count": chunk_count,
                "max_parallel_chunks": min(req.max_parallel_chunks, chunk_count),
                "call_count": chunk_count,
                "texts": list(req.texts),
                "client_config": req.client_config.model_dump() if req.client_config else None,
            },
        )


def _graph_client(service=None):
    router = APIRouter()
    graph_extract_http_api(router, service=service)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _named_client_config(graph="custom_graph"):
    return {"graph": graph, "user": "admin", "pwd": "secret", "gs": "space_a"}


def _graph_result():
    return {
        "vertices": [{"label": "person", "properties": {"name": "marko"}}],
        "edges": [
            {
                "label": "knows",
                "outV": "marko",
                "outVLabel": "person",
                "inV": "vadas",
                "inVLabel": "person",
                "properties": {},
            }
        ],
    }


def test_graph_extract_returns_envelope_from_service():
    service = Mock()
    service.extract_sync.return_value = GraphExtractResponse(
        status="succeeded",
        result=_graph_result(),
        warnings=[],
        meta={"vertex_count": 1, "edge_count": 1, "text_count": 1},
    )

    response = _graph_client(service).post(
        "/graph/extract",
        json={"texts": "marko knows vadas", "schema": VALID_SCHEMA, "include_meta": True},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "status": "succeeded",
        "result": _graph_result(),
        "warnings": [],
        "meta": {"vertex_count": 1, "edge_count": 1, "text_count": 1},
    }
    service.extract_sync.assert_called_once()


def test_graph_extract_accepts_content_text_wire_shape():
    service = Mock()
    service.extract_sync.return_value = GraphExtractResponse(
        status="succeeded",
        result=_graph_result(),
        warnings=[],
        meta={},
    )

    response = _graph_client(service).post(
        "/graph/extract",
        json={"content_type": "text", "content": "marko knows vadas", "schema": VALID_SCHEMA},
    )

    assert response.status_code == status.HTTP_200_OK
    request = service.extract_sync.call_args.args[0]
    assert request.content_type == "text"
    assert request.content == "marko knows vadas"
    assert request.texts == ["marko knows vadas"]


def test_graph_extract_accepts_content_chunks_wire_shape():
    service = Mock()
    service.extract_sync.return_value = GraphExtractResponse(
        status="succeeded",
        result=_graph_result(),
        warnings=[],
        meta={},
    )

    response = _graph_client(service).post(
        "/graph/extract",
        json={
            "content_type": "chunks",
            "content": ["marko knows vadas", "vadas knows josh"],
            "schema": VALID_SCHEMA,
            "max_parallel_chunks": 2,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    request = service.extract_sync.call_args.args[0]
    assert request.content_type == "chunks"
    assert request.content == ["marko knows vadas", "vadas knows josh"]
    assert request.texts == ["marko knows vadas", "vadas knows josh"]
    assert request.max_parallel_chunks == 2


def test_graph_extract_accepts_legacy_texts_list_as_chunks():
    service = Mock()
    service.extract_sync.return_value = GraphExtractResponse(
        status="succeeded",
        result=_graph_result(),
        warnings=[],
        meta={},
    )

    response = _graph_client(service).post(
        "/graph/extract",
        json={"texts": ["marko knows vadas", "vadas knows josh"], "schema": VALID_SCHEMA},
    )

    assert response.status_code == status.HTTP_200_OK
    request = service.extract_sync.call_args.args[0]
    assert request.content_type == "chunks"
    assert request.content == ["marko knows vadas", "vadas knows josh"]
    assert request.texts == ["marko knows vadas", "vadas knows josh"]


def test_graph_extract_api_concurrent_requests_keep_request_state_isolated():
    service = EchoGraphExtractService()

    payloads = [
        {
            "content_type": "text",
            "content": "doc A paragraph one.\n\ndoc A paragraph two.",
            "schema": VALID_SCHEMA,
            "split_type": "paragraph",
            "max_parallel_chunks": 2,
        },
        {
            "content_type": "chunks",
            "content": ["doc B chunk one", "doc B chunk two"],
            "schema": VALID_SCHEMA,
            "max_parallel_chunks": 2,
        },
        {
            "texts": "legacy text alias",
            "schema": "legacy_graph",
            "client_config": _named_client_config("legacy_graph"),
        },
        {
            "content_type": "chunks",
            "content": ["single direct chunk"],
            "schema": VALID_SCHEMA,
            "max_parallel_chunks": 4,
        },
    ]

    def post_payload(payload):
        return _graph_client(service).post("/graph/extract", json=payload).json()

    with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
        responses = list(executor.map(post_payload, payloads))

    assert [response["status"] for response in responses] == ["succeeded"] * len(payloads)
    assert responses[0]["meta"]["content_type"] == "text"
    assert responses[0]["meta"]["texts"] == ["doc A paragraph one.\n\ndoc A paragraph two."]
    assert responses[1]["meta"]["content_type"] == "chunks"
    assert responses[1]["meta"]["texts"] == ["doc B chunk one", "doc B chunk two"]
    assert responses[2]["meta"]["content_type"] == "text"
    assert responses[2]["meta"]["client_config"]["graph"] == "legacy_graph"
    assert responses[3]["meta"]["chunk_count"] == 1
    assert responses[3]["meta"]["max_parallel_chunks"] == 1
    assert len(service.requests) == len(payloads)


def test_graph_extract_rejects_invalid_public_contract_inputs():
    client = _graph_client(Mock())

    cases = [
        {"texts": "  ", "schema": INLINE_SCHEMA},
        {"texts": "x", "schema": "{bad"},
        {"texts": "x", "schema": {"vertexlabels": [{"name": "person"}], "edgelabels": []}},
        {"texts": "x", "schema": INLINE_SCHEMA, "split_type": "doc"},
        {"texts": "x", "schema": INLINE_SCHEMA, "extract_type": "triples"},
        {"content_type": "text", "content": ["chunk"], "schema": INLINE_SCHEMA},
        {"content_type": "chunks", "content": "not-a-list", "schema": INLINE_SCHEMA},
        {"content_type": "chunks", "content": [], "schema": INLINE_SCHEMA},
        {"content_type": "chunks", "content": ["x"], "schema": INLINE_SCHEMA, "split_type": "paragraph"},
        {"texts": "x", "content": "y", "schema": INLINE_SCHEMA},
        {"texts": "x", "schema": "hugegraph"},
        {"texts": "x", "schema": INLINE_SCHEMA, "client_config": _named_client_config()},
        {"texts": "x", "schema": "custom_graph", "client_config": _named_client_config("other_graph")},
        {"texts": "x", "schema": "custom_graph", "client_config": {"graph": "custom_graph", "url": "10.0.0.1:8080"}},
    ]

    for payload in cases:
        response = client.post("/graph/extract", json=payload)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_graph_extract_validation_error_reports_invalid_field_detail():
    response = _graph_client(Mock()).post(
        "/graph/extract",
        json={"content_type": "chunks", "content": ["chunk"], "schema": INLINE_SCHEMA, "split_type": "paragraph"},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    detail = response.json()["detail"]
    assert detail["code"] == "GRAPH_EXTRACT_VALIDATION_ERROR"
    assert detail["phase"] == "request"
    error_detail = detail["message"]
    assert "split_type" in error_detail
    assert "document" in error_detail
    assert "content_type is chunks" in error_detail
    assert "input_value" not in error_detail
    assert "input" not in error_detail


def test_graph_extract_validation_error_does_not_echo_sensitive_input():
    response = _graph_client(Mock()).post(
        "/graph/extract",
        json={
            "content_type": "text",
            "content": "hello",
            "schema": "custom_graph",
            "client_config": {"graph": "custom_graph", "pwd": "top-secret", "url": "10.0.0.1:8080"},
        },
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    detail_text = json.dumps(response.json(), ensure_ascii=False)
    assert "top-secret" not in detail_text
    assert "10.0.0.1:8080" not in detail_text


def test_graph_extract_api_returns_structured_error_for_invalid_flow_output():
    service = Mock()
    service.extract_sync.side_effect = FlowOutputValidationError(
        "Invalid property graph JSON: failed to parse extracted JSON"
    )

    response = _graph_client(service).post(
        "/graph/extract",
        json={"content_type": "text", "content": "bad llm output", "schema": VALID_SCHEMA},
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == {
        "code": "GRAPH_EXTRACT_INVALID_FLOW_OUTPUT",
        "message": "Graph extraction flow output is invalid",
        "phase": "extract",
    }


def test_graph_extract_api_rejects_malformed_workflow_property_graph_output():
    scheduler = Mock()
    scheduler.schedule_flow.return_value = json.dumps(
        {"vertices": [{"label": "person", "properties": None}], "edges": []}
    )

    response = _graph_client(GraphExtractService(scheduler)).post(
        "/graph/extract",
        json={"content_type": "text", "content": "bad workflow output", "schema": VALID_SCHEMA},
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == {
        "code": "GRAPH_EXTRACT_INVALID_FLOW_OUTPUT",
        "message": "Graph extraction flow output is invalid",
        "phase": "extract",
    }


def test_graph_extract_api_maps_client_value_error_to_bad_request():
    service = Mock()
    service.extract_sync.side_effect = ValueError("schema graph name must match client_config.graph")

    response = _graph_client(service).post(
        "/graph/extract",
        json={"content_type": "text", "content": "bad input", "schema": VALID_SCHEMA},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == {
        "code": "GRAPH_EXTRACT_INVALID_INPUT",
        "message": "schema graph name must match client_config.graph",
        "phase": "request",
    }


def test_graph_extract_api_returns_structured_error_for_runtime_failure():
    service = Mock()
    service.extract_sync.side_effect = RuntimeError("llm provider timeout")

    response = _graph_client(service).post(
        "/graph/extract",
        json={"content_type": "text", "content": "provider failure", "schema": VALID_SCHEMA},
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == {
        "code": "GRAPH_EXTRACT_FAILED",
        "message": "Graph extraction failed during execution",
        "phase": "extract",
    }
    assert "llm provider timeout" not in json.dumps(response.json(), ensure_ascii=False)


def test_graph_extract_request_validates_content_shape_and_parallel_limit(monkeypatch):
    monkeypatch.setattr(llm_settings, "graph_extract_max_parallel_chunks", 2)
    monkeypatch.setattr(llm_settings, "graph_extract_max_parallel_chunks_limit", 3)

    text_request = GraphExtractRequest(content_type="text", content="hello", schema=INLINE_SCHEMA)
    assert text_request.texts == ["hello"]
    assert text_request.max_parallel_chunks == 2

    chunk_request = GraphExtractRequest(
        content_type="chunks",
        content=["chunk one", "chunk two"],
        schema=INLINE_SCHEMA,
        max_parallel_chunks=3,
    )
    assert chunk_request.texts == ["chunk one", "chunk two"]
    assert chunk_request.max_parallel_chunks == 3

    with pytest.raises(ValidationError):
        GraphExtractRequest(content_type="chunks", content=["chunk"], schema=INLINE_SCHEMA, max_parallel_chunks=4)


def test_graph_extract_service_parses_flow_json_and_records_metadata():
    scheduler = Mock()
    scheduler.schedule_flow.return_value = json.dumps(
        {
            **_graph_result(),
            "call_count": 2,
            "chunk_count": 2,
            "warning": "schema mismatch",
        }
    )

    response = GraphExtractService(scheduler).extract_sync(
        GraphExtractRequest(
            content_type="text",
            content="marko knows vadas",
            schema=VALID_SCHEMA,
            language="en",
            include_meta=True,
            max_parallel_chunks=2,
        )
    )

    assert response.status == "succeeded"
    assert response.result == _graph_result()
    assert response.warnings == ["schema mismatch"]
    assert response.meta["extract_type"] == "property_graph"
    assert response.meta["language"] == "en"
    assert response.meta["text_count"] == 1
    assert response.meta["content_type"] == "text"
    assert response.meta["chunk_count"] == 2
    assert response.meta["max_parallel_chunks"] == 2
    assert response.meta["vertex_count"] == 1
    assert response.meta["edge_count"] == 1
    assert response.meta["call_count"] == 2
    scheduler.schedule_flow.assert_called_once()
    assert scheduler.schedule_flow.call_args.kwargs["language"] == "en"
    assert scheduler.schedule_flow.call_args.kwargs["split_type"] == "document"
    assert scheduler.schedule_flow.call_args.kwargs["content_type"] == "text"
    assert scheduler.schedule_flow.call_args.kwargs["max_parallel_chunks"] == 2


def test_graph_extract_service_passes_request_local_client_config_and_redacts_password(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = json.dumps({"vertices": [], "edges": []})
    monkeypatch.setattr(huge_settings, "graph_url", "127.0.0.1:8080")
    original = (
        huge_settings.graph_url,
        huge_settings.graph_name,
        huge_settings.graph_user,
        huge_settings.graph_pwd,
        huge_settings.graph_space,
    )
    client_config = GraphExtractClientConfig(graph="custom_graph", user="admin", pwd="secret", gs="space_a")

    response = GraphExtractService(scheduler).extract_sync(
        GraphExtractRequest(
            texts="x",
            schema="custom_graph",
            client_config=client_config,
            include_meta=True,
        )
    )

    assert scheduler.schedule_flow.call_args.kwargs["client_config"] == client_config
    assert "graph_config" not in scheduler.schedule_flow.call_args.kwargs
    assert response.meta["client_config"] == {
        "graph": "custom_graph",
        "user": "admin",
        "pwd": "***",
        "gs": "space_a",
    }
    assert (
        huge_settings.graph_url,
        huge_settings.graph_name,
        huge_settings.graph_user,
        huge_settings.graph_pwd,
        huge_settings.graph_space,
    ) == original


def test_graph_extract_service_rejects_invalid_flow_json():
    scheduler = Mock()
    scheduler.schedule_flow.return_value = "{broken"

    with pytest.raises(ValueError, match="Invalid graph extraction flow JSON"):
        GraphExtractService(scheduler).extract_sync(GraphExtractRequest(texts="x", schema=INLINE_SCHEMA))


def test_normalize_schema_rejects_malformed_json_schema():
    with pytest.raises(ValueError, match="schema must be valid JSON"):
        normalize_schema("{bad")


def test_property_graph_response_rejects_legacy_edge_shape():
    scheduler = Mock()
    scheduler.schedule_flow.return_value = json.dumps(
        {
            "vertices": [{"label": "person", "properties": {"name": "marko"}}],
            "edges": [{"start": "marko", "type": "knows", "end": "vadas"}],
        }
    )

    with pytest.raises(ValueError, match="canonical property graph edge"):
        GraphExtractService(scheduler).extract_sync(GraphExtractRequest(texts="x", schema=INLINE_SCHEMA))


def test_property_graph_response_rejects_non_object_properties():
    scheduler = Mock()
    scheduler.schedule_flow.return_value = json.dumps(
        {"vertices": [{"label": "person", "properties": None}], "edges": []}
    )

    with pytest.raises(ValueError, match=r"vertex\[0\].properties"):
        GraphExtractService(scheduler).extract_sync(GraphExtractRequest(texts="x", schema=INLINE_SCHEMA))


def test_request_model_validation_and_aliases():
    req = GraphExtractRequest(texts="hello", schema=INLINE_SCHEMA)
    assert req.texts == ["hello"]
    assert req.graph_schema == INLINE_SCHEMA
    assert req.schema == INLINE_SCHEMA
    assert req.client_config is None

    legacy_schema_alias = GraphExtractRequest(texts="hello", graph_schema=INLINE_SCHEMA)
    assert legacy_schema_alias.schema == INLINE_SCHEMA

    legacy_chunks = GraphExtractRequest(texts=["hello", "world"], schema=INLINE_SCHEMA)
    assert legacy_chunks.content_type == "chunks"
    assert legacy_chunks.texts == ["hello", "world"]

    with pytest.raises(ValidationError):
        GraphExtractRequest(texts=[], schema="hugegraph")


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


def test_flow_prepare_rejects_invalid_max_parallel_chunks():
    flow = GraphExtractFlow()

    with pytest.raises(ValueError, match="max_parallel_chunks"):
        flow.prepare(WkFlowInput(), INLINE_SCHEMA, ["text"], "prompt", "property_graph", max_parallel_chunks=0)


def test_flow_prepare_preserves_content_type_and_parallel_chunks():
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()

    flow.prepare(
        prepared_input,
        "custom_graph",
        ["chunk one", "chunk two"],
        "prompt",
        "property_graph",
        content_type="chunks",
        max_parallel_chunks=3,
    )

    assert prepared_input.texts == ["chunk one", "chunk two"]
    assert prepared_input.content_type == "chunks"
    assert prepared_input.max_parallel_chunks == 3


def test_graph_extract_meta_handles_invalid_chunk_texts_defensively():
    request = GraphExtractRequest(content_type="chunks", content=["chunk"], schema=INLINE_SCHEMA, include_meta=True)
    request.texts = None

    meta = GraphExtractService()._build_extract_meta(
        request,
        {"call_count": 1},
        {"vertices": [], "edges": []},
        0,
        {},
    )

    assert meta["chunk_count"] == 1
    assert meta["max_parallel_chunks"] == 1


def test_flow_build_flow_preserves_split_type_and_client_config(monkeypatch):
    monkeypatch.setattr("hugegraph_llm.flows.graph_extract.GPipeline", CapturePipeline)
    client_config = GraphExtractClientConfig(graph="custom_graph", user="admin", pwd="secret", gs="space_a")

    pipeline = GraphExtractFlow().build_flow(
        "custom_graph",
        ["text"],
        "prompt",
        "property_graph",
        split_type="paragraph",
        max_parallel_chunks=3,
        client_config=client_config,
    )

    prepared_input = pipeline.params["wkflow_input"]
    assert prepared_input.split_type == "paragraph"
    assert prepared_input.max_parallel_chunks == 3
    assert prepared_input.graph_client_config["graphspace"] == "space_a"


def test_wkflow_input_reset_clears_graph_configs():
    prepared_input = WkFlowInput()
    prepared_input.graph_client_config = {"url": "10.0.0.1:8080"}
    prepared_input.graph_config = {"graph": "custom_graph"}

    prepared_input.reset(None)

    assert prepared_input.graph_client_config is None
    assert prepared_input.graph_config is None
