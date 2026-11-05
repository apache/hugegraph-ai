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

import importlib
import warnings
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hugegraph_llm.api.models.rag_response import ThinAPIError, ThinAPIMeta, ThinAPIResponse
from hugegraph_llm.api.thin_api import thin_router
from hugegraph_llm.config import prompt
from hugegraph_llm.demo.rag_demo import app as rag_demo_app
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.graph_extract import GraphExtractFlow
from hugegraph_llm.state.ai_state import WkFlowInput


def _client(monkeypatch, scheduler):
    monkeypatch.setattr(
        "hugegraph_llm.api.thin_api.SchedulerSingleton.get_instance",
        Mock(return_value=scheduler),
    )
    app = FastAPI()
    app.include_router(thin_router)
    return TestClient(app)


def _production_router_client(monkeypatch, scheduler):
    monkeypatch.setattr(
        "hugegraph_llm.api.thin_api.SchedulerSingleton.get_instance",
        Mock(return_value=scheduler),
    )
    app = FastAPI()
    api_router, auth_enabled = rag_demo_app.create_api_router()
    assert auth_enabled is True
    app.include_router(api_router)
    return TestClient(app)


def _assert_envelope(response_json: dict, expected_ok: bool):
    assert response_json["ok"] is expected_ok
    assert "data" in response_json
    assert "error" in response_json
    assert "warnings" in response_json
    assert "next_actions" in response_json
    assert "meta" in response_json
    assert response_json["meta"]["request_id"].startswith("req-")
    assert isinstance(response_json["meta"]["duration_ms"], (int, float))
    if expected_ok:
        assert response_json["error"] is None
    else:
        assert response_json["error"] is not None
        assert "type" in response_json["error"]
        assert "message" in response_json["error"]


def test_graph_extract_api_calls_flow(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = '{"vertices": [], "edges": []}'
    client = _client(monkeypatch, scheduler)

    response = client.post(
        "/graph-extract",
        json={
            "text": "Alice knows Bob.",
            "schema": "{}",
            "example_prompt": "extract graph",
            "language": "en",
        },
    )

    assert response.status_code == 200
    json_body = response.json()
    _assert_envelope(json_body, expected_ok=True)
    assert json_body["data"] == '{"vertices": [], "edges": []}'
    scheduler.schedule_flow.assert_called_once_with(
        FlowName.GRAPH_EXTRACT,
        "{}",
        "Alice knows Bob.",
        "extract graph",
        "property_graph",
        split_type="document",
        language="en",
    )


def test_graph_extract_api_arguments_match_real_prepare_contract(monkeypatch):
    class FlowContractScheduler:
        prepared_input = None

        def schedule_flow(self, flow_name, *args, **kwargs):
            assert flow_name is FlowName.GRAPH_EXTRACT
            self.prepared_input = WkFlowInput()
            GraphExtractFlow().prepare(self.prepared_input, *args, **kwargs)
            return '{"vertices": [], "edges": []}'

    scheduler = FlowContractScheduler()
    client = _client(monkeypatch, scheduler)

    response = client.post(
        "/graph-extract",
        json={"text": "Alice knows Bob.", "schema": "{}", "language": "en"},
    )

    assert response.status_code == 200
    _assert_envelope(response.json(), expected_ok=True)
    assert scheduler.prepared_input is not None
    assert scheduler.prepared_input.split_type == "document"
    assert scheduler.prepared_input.language == "en"
    assert scheduler.prepared_input.example_prompt == prompt.extract_graph_prompt


def test_graph_extract_api_preserves_explicit_empty_prompt(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = '{"vertices": [], "edges": []}'
    client = _client(monkeypatch, scheduler)

    response = client.post(
        "/graph-extract",
        json={"text": "Alice knows Bob.", "schema": "{}", "example_prompt": ""},
    )

    assert response.status_code == 200
    scheduler.schedule_flow.assert_called_once_with(
        FlowName.GRAPH_EXTRACT,
        "{}",
        "Alice knows Bob.",
        "",
        "property_graph",
        split_type="document",
        language="zh",
    )


def test_graph_import_api_calls_flow(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = '{"imported": true}'
    monkeypatch.setattr("hugegraph_llm.api.thin_api.admin_settings.enable_login", "True")
    monkeypatch.setenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", "true")
    client = _client(monkeypatch, scheduler)

    response = client.post("/graph-import", json={"data": "{}", "schema": None})

    assert response.status_code == 200
    json_body = response.json()
    _assert_envelope(json_body, expected_ok=True)
    assert json_body["data"] == '{"imported": true}'
    scheduler.schedule_flow.assert_called_once_with(FlowName.IMPORT_GRAPH_DATA, "{}", None)


def test_thin_api_request_models_do_not_emit_schema_shadow_warning():
    import hugegraph_llm.api.models.rag_requests as rag_requests

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        module = importlib.reload(rag_requests)

    assert not any('Field name "schema"' in str(item.message) for item in caught)

    extract = module.GraphExtractRequest(text="Alice knows Bob.", schema="{}")
    graph_import = module.GraphImportRequest(data="{}", schema=None)

    assert extract.graph_schema == "{}"
    assert graph_import.graph_schema is None
    assert extract.model_dump(by_alias=True)["schema"] == "{}"


def test_vid_embeddings_refresh_api_calls_flow(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = "Removed 0 vectors, added 1 vectors."
    monkeypatch.setattr("hugegraph_llm.api.thin_api.admin_settings.enable_login", "True")
    monkeypatch.setenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", "true")
    client = _client(monkeypatch, scheduler)

    response = client.post("/vid-embeddings/refresh", json={})

    assert response.status_code == 200
    json_body = response.json()
    _assert_envelope(json_body, expected_ok=True)
    assert json_body["data"] == "Removed 0 vectors, added 1 vectors."
    scheduler.schedule_flow.assert_called_once_with(FlowName.UPDATE_VID_EMBEDDINGS)


@pytest.mark.parametrize(
    ("graphspace", "payload", "expected_ok"),
    [
        (None, {"expected_graph": "target", "expected_graphspace": None}, True),
        ("space", {"expected_graph": "target", "expected_graphspace": "space"}, True),
        (None, {"expected_graph": "other", "expected_graphspace": None}, False),
        ("space", {"expected_graph": "target", "expected_graphspace": "other"}, False),
        ("space", {"expected_graph": "target", "expected_graphspace": None}, False),
        (None, {"expected_graph": "target", "expected_graphspace": "space"}, False),
        (None, {"expected_graph": "target"}, False),
        (None, {"expected_graphspace": None}, False),
        (None, {"expected_graph": None, "expected_graphspace": None}, False),
    ],
)
def test_vid_embeddings_refresh_validates_target_before_flow(monkeypatch, graphspace, payload, expected_ok):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = "Refreshed."
    monkeypatch.setattr("hugegraph_llm.api.thin_api.admin_settings.enable_login", "True")
    monkeypatch.setattr("hugegraph_llm.api.thin_api.huge_settings.graph_name", "target")
    monkeypatch.setattr("hugegraph_llm.api.thin_api.huge_settings.graph_space", graphspace)
    monkeypatch.setenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", "true")
    client = _client(monkeypatch, scheduler)

    response = client.post("/vid-embeddings/refresh", json=payload)

    assert response.status_code == 200
    _assert_envelope(response.json(), expected_ok=expected_ok)
    if expected_ok:
        scheduler.schedule_flow.assert_called_once_with(FlowName.UPDATE_VID_EMBEDDINGS)
    else:
        assert response.json()["error"]["type"] == "VALIDATION_ERROR"
        scheduler.schedule_flow.assert_not_called()


@pytest.mark.parametrize("path", ["/vid-embeddings/refresh", "/v1/vid-embeddings/refresh"])
@pytest.mark.parametrize("configured_space", [None, "", "   ", "DEFAULT"])
@pytest.mark.parametrize("expected_space", [None, "", "   ", "DEFAULT"])
def test_refresh_normalizes_default_identity_without_mutating_settings(
    monkeypatch, path, configured_space, expected_space
):
    from hugegraph_llm.api.thin_api import huge_settings

    scheduler = Mock()
    scheduler.schedule_flow.return_value = "Refreshed."
    monkeypatch.setattr("hugegraph_llm.api.thin_api.admin_settings.enable_login", "true")
    monkeypatch.setattr(huge_settings, "graph_name", "target")
    monkeypatch.setattr(huge_settings, "graph_space", configured_space)
    monkeypatch.setenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", "true")
    client = _client(monkeypatch, scheduler)

    response = client.post(path, json={"expected_graph": "target", "expected_graphspace": expected_space})

    assert response.status_code == 200
    _assert_envelope(response.json(), expected_ok=True)
    scheduler.schedule_flow.assert_called_once_with(FlowName.UPDATE_VID_EMBEDDINGS)
    assert huge_settings.graph_space == configured_space


@pytest.mark.parametrize(
    ("configured_space", "expected_graph", "expected_space", "expected_ok"),
    [
        ("space", "target", "space", True),
        ("space", "other", "space", False),
        ("space", "target", "other", False),
        ("space", "target", None, False),
        (None, "target", "space", False),
        ("space", "target", " space ", False),
    ],
)
def test_validated_refresh_checks_target_before_flow(
    monkeypatch, configured_space, expected_graph, expected_space, expected_ok
):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = "Refreshed."
    monkeypatch.setattr("hugegraph_llm.api.thin_api.admin_settings.enable_login", "true")
    monkeypatch.setattr("hugegraph_llm.api.thin_api.huge_settings.graph_name", "target")
    monkeypatch.setattr("hugegraph_llm.api.thin_api.huge_settings.graph_space", configured_space)
    monkeypatch.setenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", "true")
    client = _client(monkeypatch, scheduler)

    response = client.post(
        "/v1/vid-embeddings/refresh",
        json={"expected_graph": expected_graph, "expected_graphspace": expected_space},
    )

    assert response.status_code == 200
    _assert_envelope(response.json(), expected_ok=expected_ok)
    if expected_ok:
        scheduler.schedule_flow.assert_called_once_with(FlowName.UPDATE_VID_EMBEDDINGS)
    else:
        assert response.json()["error"]["type"] == "VALIDATION_ERROR"
        scheduler.schedule_flow.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"expected_graph": "target"},
        {"expected_graphspace": "DEFAULT"},
        {"expected_graph": None, "expected_graphspace": "DEFAULT"},
        {"expected_graph": "", "expected_graphspace": "DEFAULT"},
    ],
)
def test_validated_refresh_requires_target_fields(monkeypatch, payload):
    scheduler = Mock()
    monkeypatch.setattr("hugegraph_llm.api.thin_api.admin_settings.enable_login", "true")
    monkeypatch.setenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", "true")
    client = _client(monkeypatch, scheduler)

    response = client.post("/v1/vid-embeddings/refresh", json=payload)

    assert response.status_code == 422
    scheduler.schedule_flow.assert_not_called()


def test_vid_embeddings_refresh_capabilities_has_no_flow_or_write(monkeypatch):
    scheduler = Mock()
    monkeypatch.delenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", raising=False)
    client = _client(monkeypatch, scheduler)

    response = client.get("/vid-embeddings/refresh-capabilities")

    assert response.status_code == 200
    _assert_envelope(response.json(), expected_ok=True)
    assert response.json()["data"] == {"protocol_version": 1}
    scheduler.schedule_flow.assert_not_called()


@pytest.mark.parametrize("path", ["/vid-embeddings/refresh", "/v1/vid-embeddings/refresh"])
def test_ui_config_reload_waits_for_refresh_target(monkeypatch, tmp_path, path):
    from hugegraph_llm.api import thin_api
    from hugegraph_llm.config.models import base_config

    # Exercise the callback actually registered by Gradio, not a copied function.
    ui = rag_demo_app.init_rag_ui()
    reload_config = next(
        fn.fn for fn in ui.fns.values() if fn.fn and getattr(fn.fn, "__name__", None) == "refresh_ui_config_prompt"
    )
    env_path = tmp_path / "graph.env"
    env_path.write_text("GRAPH_NAME=graph_a\nGRAPH_SPACE=DEFAULT\n", encoding="utf-8")
    monkeypatch.setattr(base_config, "env_path", str(env_path))
    # Isolate all graph defaults; an explicit empty GRAPH_PWD is a real password clear.
    for field in type(thin_api.huge_settings).model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    settings = type(thin_api.huge_settings)(_env_file=env_path)
    monkeypatch.setattr(thin_api, "huge_settings", settings)
    monkeypatch.setattr(rag_demo_app, "huge_settings", settings)
    monkeypatch.setattr(prompt, "ensure_yaml_file_exists", Mock())
    monkeypatch.setattr(rag_demo_app.admin_settings, "enable_login", "true")
    monkeypatch.setattr(rag_demo_app.admin_settings, "user_token", "internal-token")
    monkeypatch.setenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", "true")
    flow_entered, finish_flow = Event(), Event()
    reload_started, reload_finished = Event(), Event()

    def refresh_flow(*_args):
        flow_entered.set()
        assert finish_flow.wait(10)
        return {"observed_graph": settings.graph_name}

    def reload_ui():
        reload_started.set()
        try:
            return reload_config()
        finally:
            reload_finished.set()

    scheduler = Mock()
    scheduler.schedule_flow.side_effect = refresh_flow
    client = _production_router_client(monkeypatch, scheduler)
    payload = {"expected_graph": "graph_a", "expected_graphspace": "DEFAULT"}
    headers = {"Authorization": "Bearer internal-token"}
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            refresh = workers.submit(client.post, path, json=payload, headers=headers)
            try:
                assert flow_entered.wait(5)
                env_path.write_text(
                    env_path.read_text(encoding="utf-8").replace("GRAPH_NAME=graph_a", "GRAPH_NAME=graph_b"),
                    encoding="utf-8",
                )
                reloaded = workers.submit(reload_ui)
                assert reload_started.wait(5)
                assert not reload_finished.wait(0.2), "UI reload bypassed the active refresh lock"
                assert settings.graph_name == "graph_a"
            finally:
                finish_flow.set()
            response = refresh.result(timeout=5)
            assert response.status_code == 200
            assert response.json()["data"] == {"observed_graph": "graph_a"}
            assert reloaded.result(timeout=5)[1] == "graph_b"
        # After the refresh finishes, reload takes effect and old-target requests fail.
        assert settings.graph_name == "graph_b"
        rejected = client.post(path, json=payload, headers=headers)
        assert rejected.json()["error"]["type"] == "VALIDATION_ERROR"
        scheduler.schedule_flow.assert_called_once_with(FlowName.UPDATE_VID_EMBEDDINGS)
    finally:
        client.close()
        ui.close()


def test_production_router_protects_refresh_capabilities(monkeypatch):
    scheduler = Mock()
    monkeypatch.setattr(rag_demo_app.admin_settings, "enable_login", "True")
    monkeypatch.setattr(rag_demo_app.admin_settings, "user_token", "internal-token")
    client = _production_router_client(monkeypatch, scheduler)

    missing = client.get("/vid-embeddings/refresh-capabilities")
    accepted = client.get("/vid-embeddings/refresh-capabilities", headers={"Authorization": "Bearer internal-token"})

    assert missing.status_code in {401, 403}
    assert accepted.status_code == 200
    assert accepted.json()["data"] == {"protocol_version": 1}
    scheduler.schedule_flow.assert_not_called()


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/graph-import", {"data": "{}", "schema": None}),
        ("/vid-embeddings/refresh", {}),
        ("/vid-embeddings/refresh", {"expected_graph": "target", "expected_graphspace": None}),
        ("/v1/vid-embeddings/refresh", {"expected_graph": "target", "expected_graphspace": None}),
    ],
)
def test_thin_write_endpoints_are_disabled_by_default(monkeypatch, path, payload):
    scheduler = Mock()
    monkeypatch.delenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", raising=False)
    monkeypatch.setattr("hugegraph_llm.api.thin_api.admin_settings.enable_login", "False")
    client = _client(monkeypatch, scheduler)

    response = client.post(path, json=payload)

    assert response.status_code == 200
    body = response.json()
    _assert_envelope(body, expected_ok=False)
    assert body["error"]["type"] == "FEATURE_DISABLED"
    scheduler.schedule_flow.assert_not_called()


def test_thin_writes_remain_disabled_without_login(monkeypatch):
    scheduler = Mock()
    monkeypatch.setattr("hugegraph_llm.api.thin_api.admin_settings.enable_login", "False")
    monkeypatch.setenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", "true")
    client = _client(monkeypatch, scheduler)

    response = client.post("/graph-import", json={"data": "{}", "schema": None})

    assert response.status_code == 200
    assert response.json()["error"]["type"] == "FEATURE_DISABLED"
    scheduler.schedule_flow.assert_not_called()


def test_thin_writes_remain_disabled_without_write_flag(monkeypatch):
    scheduler = Mock()
    monkeypatch.setattr("hugegraph_llm.api.thin_api.admin_settings.enable_login", "True")
    monkeypatch.delenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", raising=False)
    client = _client(monkeypatch, scheduler)

    response = client.post("/graph-import", json={"data": "{}", "schema": None})

    assert response.status_code == 200
    assert response.json()["error"]["type"] == "FEATURE_DISABLED"
    scheduler.schedule_flow.assert_not_called()


@pytest.mark.parametrize(
    ("path", "payload", "expected_flow"),
    [
        (
            "/graph-import",
            {"data": "{}", "schema": None},
            FlowName.IMPORT_GRAPH_DATA,
        ),
        (
            "/vid-embeddings/refresh",
            {},
            FlowName.UPDATE_VID_EMBEDDINGS,
        ),
        (
            "/v1/vid-embeddings/refresh",
            {"expected_graph": "target", "expected_graphspace": "DEFAULT"},
            FlowName.UPDATE_VID_EMBEDDINGS,
        ),
    ],
)
@pytest.mark.parametrize("login_value", ["true", "TRUE", " true "])
def test_production_router_requires_bearer_for_enabled_thin_writes(
    monkeypatch, path, payload, expected_flow, login_value
):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = {"status": "ok"}
    monkeypatch.setattr(rag_demo_app.admin_settings, "enable_login", login_value)
    monkeypatch.setattr(rag_demo_app.admin_settings, "user_token", "internal-token")
    monkeypatch.setattr("hugegraph_llm.api.thin_api.huge_settings.graph_name", "target")
    monkeypatch.setattr("hugegraph_llm.api.thin_api.huge_settings.graph_space", "DEFAULT")
    monkeypatch.setenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", "true")
    client = _production_router_client(monkeypatch, scheduler)

    missing = client.post(path, json=payload)
    invalid = client.post(
        path,
        json=payload,
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert missing.status_code in {401, 403}
    assert invalid.status_code == 401
    assert "wrong-token" not in invalid.text
    scheduler.schedule_flow.assert_not_called()
    accepted = client.post(
        path,
        json=payload,
        headers={"Authorization": "Bearer internal-token"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["ok"] is True
    assert scheduler.schedule_flow.call_count == 1
    assert scheduler.schedule_flow.call_args.args[0] == expected_flow

    scheduler.schedule_flow.reset_mock()
    monkeypatch.setenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", "false")
    disabled = client.post(path, json=payload, headers={"Authorization": "Bearer internal-token"})
    assert disabled.status_code == 200
    assert disabled.json()["ok"] is False
    assert disabled.json()["error"]["type"] == "FEATURE_DISABLED"
    scheduler.schedule_flow.assert_not_called()


@pytest.mark.parametrize("login_value", ["false", " FALSE ", "invalid", "", None])
@pytest.mark.parametrize("path", ["/graph-import", "/vid-embeddings/refresh", "/v1/vid-embeddings/refresh"])
def test_production_router_blocks_thin_writes_when_login_disabled(monkeypatch, login_value, path):
    scheduler = Mock()
    monkeypatch.setattr(rag_demo_app.admin_settings, "enable_login", login_value)
    monkeypatch.setenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", "true")
    monkeypatch.setattr("hugegraph_llm.api.thin_api.SchedulerSingleton.get_instance", Mock(return_value=scheduler))
    router, auth_enabled = rag_demo_app.create_api_router()
    assert auth_enabled is False
    app = FastAPI()
    app.include_router(router)
    payload = (
        {"data": "{}", "schema": None}
        if path == "/graph-import"
        else {"expected_graph": "target", "expected_graphspace": "DEFAULT"}
    )
    response = TestClient(app).post(path, json=payload)
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"]["type"] == "FEATURE_DISABLED"
    scheduler.schedule_flow.assert_not_called()


def test_graph_index_info_api_calls_flow(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.return_value = '{"vertices": 1}'
    client = _client(monkeypatch, scheduler)

    response = client.get("/graph-index-info")

    assert response.status_code == 200
    json_body = response.json()
    _assert_envelope(json_body, expected_ok=True)
    assert json_body["data"] == '{"vertices": 1}'
    scheduler.schedule_flow.assert_called_once_with(FlowName.GET_GRAPH_INDEX_INFO)


def test_thin_api_returns_flow_execution_failed(monkeypatch):
    scheduler = Mock()
    scheduler.schedule_flow.side_effect = RuntimeError("secret path /tmp/token")
    error_log = Mock()
    monkeypatch.setattr("hugegraph_llm.api.thin_api.log.error", error_log)
    monkeypatch.setattr(
        "hugegraph_llm.api.thin_api._generate_request_id",
        Mock(return_value="req-safe-error"),
    )
    client = _client(monkeypatch, scheduler)

    response = client.get("/graph-index-info")

    assert response.status_code == 200
    json_body = response.json()
    _assert_envelope(json_body, expected_ok=False)
    assert json_body["data"] is None
    assert json_body["error"]["type"] == "FLOW_EXECUTION_FAILED"
    assert json_body["error"]["message"] == "An internal error occurred during flow execution."
    assert "secret" not in json_body["error"]["message"]
    assert json_body["error"]["source"] == "hugegraph-llm"
    assert "details" in json_body["error"]
    assert json_body["meta"]["request_id"] == "req-safe-error"
    error_log.assert_called_once_with(
        "Thin API flow execution failed: request_id=%s flow=%s exception_type=%s",
        "req-safe-error",
        FlowName.GET_GRAPH_INDEX_INFO.value,
        "RuntimeError",
    )
    assert "secret" not in repr(error_log.call_args)
    assert "/tmp/token" not in repr(error_log.call_args)


def test_thin_api_response_defaults_are_not_shared():
    first = ThinAPIResponse(ok=True, meta=ThinAPIMeta(request_id="req-a"))
    second = ThinAPIResponse(ok=True, meta=ThinAPIMeta(request_id="req-b"))
    first.warnings.append("one")
    first.next_actions.append("next")

    assert second.warnings == []
    assert second.next_actions == []

    first_error = ThinAPIError(type="X", message="x")
    second_error = ThinAPIError(type="Y", message="y")
    first_error.details["secret"] = "value"
    assert second_error.details == {}
