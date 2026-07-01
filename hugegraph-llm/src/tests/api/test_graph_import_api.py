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
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, FastAPI, status
from fastapi.testclient import TestClient

from hugegraph_llm.api.graph_extract_api import graph_extract_http_api
from hugegraph_llm.api.models.graph_extract_requests import GraphExtractAndImportRequest, GraphImportRequest
from hugegraph_llm.api.models.graph_extract_responses import GraphExtractResponse, GraphImportResponse
from hugegraph_llm.config import huge_settings
from hugegraph_llm.flows import FlowName
from hugegraph_llm.services.graph_extract_service import (
    FlowOutputValidationError,
    GraphExtractService,
    GraphImportService,
    apply_client_config,
)


def _payload_data():
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


def _target_client_config(graph="target_graph"):
    return {"graph": graph, "user": "admin", "pwd": "secret", "gs": "space_a"}


def _import_payload(**overrides):
    payload = {
        "schema": {
            "propertykeys": [
                {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
            ],
            "vertexlabels": [{"name": "person", "properties": ["name"]}],
            "edgelabels": [{"name": "knows", "source_label": "person", "target_label": "person"}],
        },
        "data": _payload_data(),
        "write_to_graph": True,
        "client_config": _target_client_config(),
    }
    payload.update(overrides)
    return payload


def _extract_payload(**overrides):
    payload = {
        "texts": ["marko knows vadas"],
        "schema": {
            "vertexlabels": [{"name": "person", "properties": ["name"]}],
            "edgelabels": [{"name": "knows", "source_label": "person", "target_label": "person"}],
        },
        "example_prompt": "extract graph",
        "write_to_graph": True,
    }
    payload.update(overrides)
    return payload


def _client(extract_service=None, import_service=None):
    router = APIRouter()
    graph_extract_http_api(router, service=extract_service, import_service=import_service)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _import_response(updated_embeddings=False):
    return GraphImportResponse(
        status="succeeded",
        vertex_count=1,
        edge_count=1,
        updated_embeddings=updated_embeddings,
        warnings=[],
        meta={"duration_ms": 2},
    )


def _flow_import_result(
    vertices_created=1,
    edges_created=1,
    triples_created=0,
    vertices_skipped=0,
    edges_skipped=0,
    triples_skipped=0,
    errors=None,
):
    return json.dumps(
        {
            "import_result": {
                "vertices_attempted": vertices_created + vertices_skipped,
                "vertices_created": vertices_created,
                "vertices_skipped": vertices_skipped,
                "edges_attempted": edges_created + edges_skipped,
                "edges_created": edges_created,
                "edges_skipped": edges_skipped,
                "triples_attempted": triples_created + triples_skipped,
                "triples_created": triples_created,
                "triples_skipped": triples_skipped,
                "errors": errors or [],
            }
        }
    )


def _partial_import_response():
    return GraphImportResponse(
        status="partial",
        vertex_count=1,
        edge_count=0,
        updated_embeddings=False,
        warnings=["missing primary key"],
        meta={"duration_ms": 2, "import_result": {"vertices_created": 1, "edges_skipped": 1}},
    )


def test_post_graph_import_calls_import_service():
    import_service = Mock()
    import_service.import_graph.return_value = _import_response()
    client = _client(import_service=import_service)

    response = client.post("/graph/import", json=_import_payload())

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["vertex_count"] == 1
    assert response.json()["updated_embeddings"] is False
    import_service.import_graph.assert_called_once()


def test_post_graph_import_requires_write_confirmation_before_writing():
    import_service = Mock()
    client = _client(import_service=import_service)

    response = client.post("/graph/import", json=_import_payload(write_to_graph=False))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"]["code"] == "GRAPH_IMPORT_CONFIRMATION_REQUIRED"
    import_service.import_graph.assert_not_called()


def test_post_graph_import_validation_error_uses_import_code():
    import_service = Mock()
    client = _client(import_service=import_service)

    response = client.post(
        "/graph/import",
        json=_import_payload(data={"vertices": [{"label": "person", "properties": None}]}),
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.json()["detail"]["code"] == "GRAPH_IMPORT_VALIDATION_ERROR"
    assert response.json()["detail"]["phase"] == "import"
    import_service.import_graph.assert_not_called()


def test_graph_import_request_rejects_empty_graph_data():
    with pytest.raises(ValueError, match="vertex or edge"):
        GraphImportRequest(schema={"vertices": [{"label": "person"}]}, data={"vertices": [], "edges": []})


def test_graph_import_request_rejects_triples_only_graph_data():
    with pytest.raises(ValueError, match="triples import is not supported"):
        GraphImportRequest(
            schema={
                "vertexlabels": [{"name": "person", "properties": ["name"]}],
                "edgelabels": [],
            },
            data={"triples": [{"start": "marko", "type": "knows", "end": "vadas"}]},
            write_to_graph=True,
        )


def test_graph_import_request_rejects_malformed_property_graph_data():
    invalid_payloads = [
        {"vertices": "not-a-list"},
        {"vertices": [{"properties": {"name": "marko"}}]},
        {"vertices": [{"label": "person", "properties": "not-an-object"}]},
        {"edges": "not-a-list"},
        {"edges": [{"label": "knows", "outV": "marko", "inV": "vadas", "properties": {}}]},
        {
            "edges": [
                {
                    "label": "knows",
                    "outV": "marko",
                    "outVLabel": "person",
                    "inV": "vadas",
                    "inVLabel": "person",
                    "properties": "not-an-object",
                }
            ]
        },
    ]

    for data in invalid_payloads:
        with pytest.raises(ValueError):
            GraphImportRequest(**_import_payload(data=data))


def test_graph_import_request_rejects_edge_endpoint_label_mismatch():
    data = _payload_data()
    data["edges"][0]["outVLabel"] = "movie"

    with pytest.raises(ValueError, match="outVLabel must match schema source_label"):
        GraphImportRequest(**_import_payload(data=data))


def test_graph_import_request_rejects_inline_schema_unknown_property():
    data = _payload_data()
    data["vertices"][0]["properties"]["secret"] = "raw user data"

    with pytest.raises(ValueError, match="vertices\\[0\\].properties.secret"):
        GraphImportRequest(**_import_payload(data=data))


def test_graph_import_request_rejects_inline_schema_invalid_property_type():
    data = _payload_data()
    data["vertices"][0]["properties"]["name"] = 123

    with pytest.raises(ValueError, match="vertices\\[0\\].properties.name must match schema property type"):
        GraphImportRequest(**_import_payload(data=data))


def test_graph_import_request_rejects_bool_for_integer_property_and_accepts_integer_double():
    payload = _import_payload(
        schema={
            "propertykeys": [
                {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
                {"name": "age", "data_type": "INT", "cardinality": "SINGLE"},
                {"name": "score", "data_type": "DOUBLE", "cardinality": "SINGLE"},
            ],
            "vertexlabels": [{"name": "person", "properties": ["name", "age", "score"]}],
            "edgelabels": [],
        },
        data={"vertices": [{"label": "person", "properties": {"name": "marko", "age": 29, "score": 1}}]},
    )

    request = GraphImportRequest(**payload)
    assert request.data["vertices"][0]["properties"]["score"] == 1

    payload["data"]["vertices"][0]["properties"]["age"] = True
    with pytest.raises(ValueError, match="vertices\\[0\\].properties.age must match schema property type"):
        GraphImportRequest(**payload)


def test_graph_import_request_rejects_inline_schema_unknown_edge_property():
    data = _payload_data()
    data["edges"][0]["properties"]["secret"] = "raw edge data"

    with pytest.raises(ValueError, match="edges\\[0\\].properties.secret"):
        GraphImportRequest(**_import_payload(data=data))


def test_graph_import_request_requires_explicit_target_graph_for_inline_schema_write():
    with pytest.raises(ValueError, match="client_config.graph"):
        GraphImportRequest(**_import_payload(client_config=None))

    with pytest.raises(ValueError, match="client_config.graph"):
        GraphExtractAndImportRequest(**_extract_payload(write_to_graph=True))


def test_extract_and_import_requires_write_confirmation_before_writing():
    import_service = Mock()
    client = _client(import_service=import_service)

    response = client.post("/graph/extract-and-import", json=_extract_payload(write_to_graph=False))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"]["code"] == "GRAPH_IMPORT_CONFIRMATION_REQUIRED"
    import_service.import_graph.assert_not_called()


def test_confirmed_extract_and_import_runs_extraction_before_import():
    extract_service = Mock()
    extract_service.extract_sync.return_value = GraphExtractResponse(
        status="succeeded",
        result=_payload_data(),
        warnings=[],
        meta={"vertex_count": 1, "edge_count": 1},
    )
    import_service = Mock()
    import_service.import_graph.return_value = _import_response()
    client = _client(extract_service=extract_service, import_service=import_service)

    response = client.post("/graph/extract-and-import", json=_extract_payload(client_config=_target_client_config()))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "succeeded"
    assert response.json()["import_result"]["status"] == "succeeded"
    extract_service.extract_sync.assert_called_once()
    import_service.import_graph.assert_called_once()


def test_extract_and_import_top_status_tracks_import_result():
    extract_service = Mock()
    extract_service.extract_sync.return_value = GraphExtractResponse(
        status="succeeded",
        result=_payload_data(),
        warnings=[],
        meta={},
    )
    import_service = Mock()
    import_service.import_graph.return_value = _partial_import_response()
    client = _client(extract_service=extract_service, import_service=import_service)

    response = client.post("/graph/extract-and-import", json=_extract_payload(client_config=_target_client_config()))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "partial"
    assert response.json()["import_result"]["status"] == "partial"


def test_extract_and_import_extract_phase_runtime_error_is_sanitized():
    extract_service = Mock()
    extract_service.extract_sync.side_effect = RuntimeError("raw text provider timeout secret")
    import_service = Mock()
    client = _client(extract_service=extract_service, import_service=import_service)

    response = client.post("/graph/extract-and-import", json=_extract_payload(client_config=_target_client_config()))

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == {
        "code": "GRAPH_EXTRACT_FAILED",
        "message": "Graph extraction failed during execution",
        "phase": "extract",
    }
    assert "raw text provider timeout secret" not in str(response.json())
    import_service.import_graph.assert_not_called()


def test_extract_and_import_import_phase_runtime_error_is_sanitized():
    extract_service = Mock()
    extract_service.extract_sync.return_value = GraphExtractResponse(
        status="succeeded",
        result=_payload_data(),
        warnings=[],
        meta={},
    )
    import_service = Mock()
    import_service.import_graph.side_effect = RuntimeError("hugegraph password secret")
    client = _client(extract_service=extract_service, import_service=import_service)

    response = client.post("/graph/extract-and-import", json=_extract_payload(client_config=_target_client_config()))

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == {
        "code": "GRAPH_IMPORT_FAILED",
        "message": "Graph import failed during execution",
        "phase": "import",
    }
    assert "hugegraph password secret" not in str(response.json())


def test_extract_and_import_flow_output_errors_keep_phase_specific_codes():
    extract_service = Mock()
    extract_service.extract_sync.side_effect = FlowOutputValidationError("raw llm output")
    import_service = Mock()
    client = _client(extract_service=extract_service, import_service=import_service)

    extract_error = client.post(
        "/graph/extract-and-import", json=_extract_payload(client_config=_target_client_config())
    )

    assert extract_error.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert extract_error.json()["detail"] == {
        "code": "GRAPH_EXTRACT_INVALID_FLOW_OUTPUT",
        "message": "Graph extraction flow output is invalid",
        "phase": "extract",
    }
    import_service.import_graph.assert_not_called()

    extract_service.extract_sync.side_effect = None
    extract_service.extract_sync.return_value = GraphExtractResponse(
        status="succeeded",
        result=_payload_data(),
        warnings=[],
        meta={},
    )
    import_service.import_graph.side_effect = FlowOutputValidationError("raw import output")

    import_error = client.post(
        "/graph/extract-and-import", json=_extract_payload(client_config=_target_client_config())
    )

    assert import_error.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert import_error.json()["detail"] == {
        "code": "GRAPH_IMPORT_INVALID_FLOW_OUTPUT",
        "message": "Graph import flow output is invalid",
        "phase": "import",
    }


def test_extract_and_import_allows_inline_schema_with_request_graph_config():
    request = GraphExtractAndImportRequest(**_extract_payload(client_config=_target_client_config()))

    assert request.client_config.graph == "target_graph"


def test_extract_and_import_passes_inline_schema_request_graph_config_to_import():
    extract_service = Mock()
    extract_service.extract_sync.return_value = GraphExtractResponse(
        status="succeeded",
        result=_payload_data(),
        warnings=[],
        meta={},
    )
    import_service = Mock()
    import_service.import_graph.return_value = _import_response()
    client = _client(extract_service=extract_service, import_service=import_service)

    response = client.post(
        "/graph/extract-and-import",
        json=_extract_payload(client_config=_target_client_config()),
    )

    assert response.status_code == status.HTTP_200_OK
    import_request = import_service.import_graph.call_args.args[0]
    assert import_request.client_config.graph == "target_graph"
    assert import_request.client_config.user == "admin"
    assert import_request.client_config.pwd == "secret"
    assert import_request.client_config.gs == "space_a"


def test_extract_and_import_inline_schema_keeps_client_config_out_of_extract_flow(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = '{"vertices":[],"edges":[]}'
    monkeypatch.setattr(
        "hugegraph_llm.services.graph_extract_service.SchedulerSingleton.get_instance",
        lambda: scheduler,
    )
    request = GraphExtractAndImportRequest(**_extract_payload(client_config=_target_client_config()))

    GraphExtractService().extract_sync(request)

    assert scheduler.schedule_flow.call_args.kwargs["client_config"] is None


def test_extract_and_import_rejects_triples_extraction_at_request_boundary():
    extract_service = Mock()
    import_service = Mock()
    client = _client(extract_service=extract_service, import_service=import_service)

    response = client.post(
        "/graph/extract-and-import",
        json=_extract_payload(extract_type="triples", client_config=_target_client_config()),
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    extract_service.extract_sync.assert_not_called()
    import_service.import_graph.assert_not_called()


def test_graph_import_service_uses_import_flow_and_updates_embeddings_only_when_requested(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.side_effect = [_flow_import_result(), "{}"]
    monkeypatch.setattr(
        "hugegraph_llm.services.graph_extract_service.SchedulerSingleton.get_instance",
        lambda: scheduler,
    )

    response = GraphImportService().import_graph(
        GraphImportRequest(**_import_payload(options={"update_vid_embeddings": True}))
    )

    assert response.updated_embeddings is True
    assert scheduler.schedule_flow.call_args_list[0].args[0] == FlowName.IMPORT_GRAPH_DATA
    assert scheduler.schedule_flow.call_args_list[1].args[0] == FlowName.UPDATE_VID_EMBEDDINGS
    assert scheduler.schedule_flow.call_args_list[1].kwargs["graph_config"]["graph"] == "target_graph"


def test_graph_import_service_requires_write_confirmation():
    scheduler = Mock()

    with pytest.raises(ValueError, match="write_to_graph must be True"):
        GraphImportService(scheduler=scheduler).import_graph(
            GraphImportRequest(**_import_payload(write_to_graph=False, client_config=None))
        )

    scheduler.schedule_flow.assert_not_called()


def test_graph_import_service_keeps_import_result_when_embedding_update_fails(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.side_effect = [
        _flow_import_result(),
        RuntimeError("embed failed at http://internal.example/token=secret"),
    ]
    monkeypatch.setattr(
        "hugegraph_llm.services.graph_extract_service.SchedulerSingleton.get_instance",
        lambda: scheduler,
    )

    response = GraphImportService().import_graph(
        GraphImportRequest(**_import_payload(options={"update_vid_embeddings": True}))
    )

    assert response.status == "partial"
    assert response.vertex_count == 1
    assert response.edge_count == 1
    assert response.updated_embeddings is False
    assert response.warnings == ["update_vid_embeddings failed"]
    assert "internal.example" not in " ".join(response.warnings)
    assert "secret" not in " ".join(response.warnings)
    assert scheduler.schedule_flow.call_args_list[0].args[0] == FlowName.IMPORT_GRAPH_DATA
    assert scheduler.schedule_flow.call_args_list[1].args[0] == FlowName.UPDATE_VID_EMBEDDINGS


def test_graph_import_service_does_not_update_embeddings_by_default(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = _flow_import_result()
    monkeypatch.setattr(
        "hugegraph_llm.services.graph_extract_service.SchedulerSingleton.get_instance",
        lambda: scheduler,
    )

    response = GraphImportService().import_graph(GraphImportRequest(**_import_payload()))

    assert response.updated_embeddings is False
    assert len(scheduler.schedule_flow.call_args_list) == 1
    assert scheduler.schedule_flow.call_args.args[0] == FlowName.IMPORT_GRAPH_DATA


def test_graph_import_service_uses_request_graph_config_without_mutating_global_config(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = _flow_import_result(edges_created=0)
    monkeypatch.setattr(
        "hugegraph_llm.services.graph_extract_service.SchedulerSingleton.get_instance",
        lambda: scheduler,
    )
    monkeypatch.setattr(huge_settings, "graph_url", "127.0.0.1:8080")
    monkeypatch.setattr(huge_settings, "graph_name", "before-graph")
    monkeypatch.setattr(huge_settings, "graph_user", "before-user")
    monkeypatch.setattr(huge_settings, "graph_pwd", "before-pwd")
    monkeypatch.setattr(huge_settings, "graph_space", "before-space")

    response = GraphImportService().import_graph(
        GraphImportRequest(
            **_import_payload(
                client_config={
                    "graph": "hugegraph",
                    "user": "admin",
                    "pwd": "secret",
                    "gs": "space_a",
                }
            )
        )
    )

    assert scheduler.schedule_flow.call_args.kwargs["graph_config"] == {
        "graph": "hugegraph",
        "user": "admin",
        "pwd": "secret",
        "gs": "space_a",
    }
    assert response.meta["client_config"]["pwd"] == "***"
    assert "secret" not in str(response.model_dump())
    assert huge_settings.graph_url == "127.0.0.1:8080"
    assert huge_settings.graph_name == "before-graph"
    assert huge_settings.graph_user == "before-user"
    assert huge_settings.graph_pwd == "before-pwd"
    assert huge_settings.graph_space == "before-space"


def test_graph_import_service_aligns_graph_name_schema_with_write_target(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = _flow_import_result(vertices_created=0, edges_created=0)
    monkeypatch.setattr(
        "hugegraph_llm.services.graph_extract_service.SchedulerSingleton.get_instance",
        lambda: scheduler,
    )

    GraphImportService().import_graph(
        GraphImportRequest(
            schema="tenant_graph",
            data=_payload_data(),
            write_to_graph=True,
            client_config={"user": "admin"},
        )
    )

    assert scheduler.schedule_flow.call_args.kwargs["graph_config"] == {
        "graph": "tenant_graph",
        "user": "admin",
    }


def test_apply_client_config_accepts_dict_without_mutating_input():
    config = {"graph": "tenant_graph", "user": "admin", "pwd": None}

    result = apply_client_config(config, schema="tenant_graph", align_graph_with_schema=True)

    assert result == {"graph": "tenant_graph", "user": "admin"}
    assert config == {"graph": "tenant_graph", "user": "admin", "pwd": None}


def test_graph_import_service_rejects_schema_graph_and_target_graph_mismatch(monkeypatch):
    scheduler = Mock()
    monkeypatch.setattr(
        "hugegraph_llm.services.graph_extract_service.SchedulerSingleton.get_instance",
        lambda: scheduler,
    )

    with pytest.raises(ValueError, match="schema graph name"):
        GraphImportRequest(
            schema="schema_graph",
            data=_payload_data(),
            write_to_graph=True,
            client_config={"graph": "target_graph"},
        )

    scheduler.schedule_flow.assert_not_called()


def test_graph_import_service_passes_graph_config_to_vid_embedding_update(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.side_effect = [
        _flow_import_result(vertices_created=0, edges_created=0),
        "{}",
    ]
    monkeypatch.setattr(
        "hugegraph_llm.services.graph_extract_service.SchedulerSingleton.get_instance",
        lambda: scheduler,
    )

    GraphImportService().import_graph(
        GraphImportRequest(
            **_import_payload(
                client_config={
                    "graph": "tenant_graph",
                },
                options={"update_vid_embeddings": True},
            )
        )
    )

    assert scheduler.schedule_flow.call_args_list[1].kwargs["graph_config"] == {
        "graph": "tenant_graph",
    }


def test_graph_import_response_counts_actual_import_result_not_request_size(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = (
        '{"import_result":{"vertices_attempted":1,"vertices_created":0,"vertices_skipped":1,'
        '"edges_attempted":1,"edges_created":1,"edges_skipped":0,'
        '"triples_attempted":0,"triples_created":0,"triples_skipped":0,'
        '"errors":[{"kind":"vertex","index":0,"label":"person","key":"name","reason":"missing_primary_key"}]}}'
    )
    monkeypatch.setattr(
        "hugegraph_llm.services.graph_extract_service.SchedulerSingleton.get_instance",
        lambda: scheduler,
    )

    response = GraphImportService().import_graph(GraphImportRequest(**_import_payload()))

    assert response.status == "partial"
    assert response.vertex_count == 0
    assert response.edge_count == 1
    assert response.meta["import_result"]["vertices_skipped"] == 1
    assert response.meta["import_result"]["errors"] == [
        {"kind": "vertex", "index": 0, "label": "person", "key": "name", "reason": "missing_primary_key"}
    ]
    assert response.warnings == ["vertex import error index=0 label=person key=name reason=missing_primary_key"]


def test_graph_import_response_marks_all_skipped_result_as_failed(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = (
        '{"import_result":{"vertices_attempted":0,"vertices_created":0,"vertices_skipped":1,'
        '"edges_attempted":0,"edges_created":0,"edges_skipped":0,'
        '"triples_attempted":0,"triples_created":0,"triples_skipped":0,'
        '"errors":["vertex creation failed for Tom Hanks with token=secret"]}}'
    )
    monkeypatch.setattr(
        "hugegraph_llm.services.graph_extract_service.SchedulerSingleton.get_instance",
        lambda: scheduler,
    )

    response = GraphImportService().import_graph(GraphImportRequest(**_import_payload()))

    assert response.status == "failed"
    assert response.vertex_count == 0
    assert response.meta["import_result"]["errors"] == [{"kind": "import", "reason": "import_error"}]
    assert response.warnings == ["import error reason=import_error"]
    assert "Tom Hanks" not in str(response.warnings)
    assert "secret" not in str(response.meta["import_result"]["errors"])


@pytest.mark.parametrize("raw_result", ["{}", '{"import_result":{}}'])
def test_graph_import_service_rejects_missing_or_malformed_import_result(monkeypatch, raw_result):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = raw_result
    monkeypatch.setattr(
        "hugegraph_llm.services.graph_extract_service.SchedulerSingleton.get_instance",
        lambda: scheduler,
    )

    with pytest.raises(FlowOutputValidationError, match="import_result"):
        GraphImportService().import_graph(GraphImportRequest(**_import_payload()))


def test_extract_endpoint_never_invokes_import_service():
    extract_service = Mock()
    extract_service.extract_sync.return_value = GraphExtractResponse(
        status="succeeded",
        result=_payload_data(),
        warnings=[],
        meta={"vertex_count": 1, "edge_count": 1},
    )
    import_service = Mock()
    client = _client(extract_service=extract_service, import_service=import_service)

    response = client.post("/graph/extract", json=_extract_payload())

    assert response.status_code == status.HTTP_200_OK
    import_service.import_graph.assert_not_called()
