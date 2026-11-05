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

from importlib.metadata import version
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from hugegraph_llm.demo.rag_demo import app

pytestmark = pytest.mark.contract


def test_gradio_homepage_and_file_upload_schema(monkeypatch):
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "false")
    monkeypatch.setattr(app.prompt, "update_yaml_file", Mock())
    monkeypatch.setattr(app.admin_settings, "enable_login", "false")

    application = app.create_app()
    # A request without entering the client context avoids the background
    # scheduler while exercising the real UI and its Pydantic-generated schema.
    client = TestClient(application)
    try:
        response = client.get("/")
        assert response.status_code == 200
        assert "HugeGraph RAG Platform" in response.text
        assert client.get("/gradio_api/info").status_code == 200
    finally:
        client.close()


@pytest.mark.parametrize(
    ("render_name", "provider"),
    [
        *[
            (name, provider)
            for name in ("chat_llm_settings", "extract_llm_settings", "text2gql_llm_settings", "embedding_settings")
            for provider in ("openai", "ollama/local")
        ],
        ("reranker_settings", "cohere"),
        ("reranker_settings", "siliconflow"),
        ("vector_engine_settings", "Milvus"),
        ("vector_engine_settings", "Qdrant"),
    ],
)
def test_dynamic_configuration_inputs_remain_editable(monkeypatch, render_name, provider):
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "false")
    monkeypatch.setattr(app.prompt, "update_yaml_file", Mock())
    monkeypatch.setattr(app.admin_settings, "enable_login", "false")
    settings = app.prompt.llm_settings
    for field in ("chat_llm_type", "extract_llm_type", "text2gql_llm_type", "embedding_type", "reranker_type"):
        monkeypatch.setattr(settings, field, getattr(settings, field))

    ui = app.init_rag_ui()
    render = next(
        function
        for function in ui.fns.values()
        if getattr(getattr(getattr(function.fn, "__self__", None), "fn", None), "__name__", None) == render_name
    )
    monkeypatch.setattr(app, "init_rag_ui", lambda: ui)
    client = TestClient(app.create_app())
    try:
        response = client.post(
            f"/gradio_api/run/{render.api_name}",
            json={"data": [provider], "session_hash": "editable-settings-regression"},
        )
        assert response.status_code == 200, response.text
        textboxes = [
            component["props"]
            for component in response.json()["render_config"]["components"]
            if component["type"] == "textbox" and component["props"].get("visible", True)
        ]
        assert textboxes
        assert all(component.get("interactive") is True for component in textboxes)
    finally:
        client.close()


def test_document_tab_switches_are_synchronous_client_updates(monkeypatch):
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "false")
    monkeypatch.setattr(app.prompt, "update_yaml_file", Mock())
    monkeypatch.setattr(app.admin_settings, "enable_login", "false")

    ui = app.init_rag_ui()
    expected_javascript = {
        "(files, _text) => [files, '']",
        "(_files, text) => [[], text]",
    }
    tab_switches = [
        dependency for dependency in ui.config["dependencies"] if dependency.get("js") in expected_javascript
    ]

    assert {dependency["js"] for dependency in tab_switches} == expected_javascript
    assert all(dependency["backend_fn"] is False for dependency in tab_switches)
    assert all(dependency["queue"] is False for dependency in tab_switches)


def test_openapi_reports_installed_package_version(monkeypatch):
    monkeypatch.setattr(app.prompt, "update_yaml_file", Mock())
    monkeypatch.setattr(app, "init_rag_ui", Mock())
    monkeypatch.setattr(app.gr, "mount_gradio_app", lambda application, *_args, **_kwargs: application)

    application = app.create_app()

    assert application.openapi()["info"]["version"] == version("hugegraph-llm")


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.255.255.254", True),
        ("::1", True),
        ("localhost", True),
        ("LOCALHOST", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.168.1.10", False),
        ("example.internal", False),
    ],
)
def test_is_loopback_host(host, expected):
    assert app.is_loopback_host(host) is expected


def test_parse_args_defaults_to_loopback():
    args = app.parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 8001


def test_run_server_passes_default_loopback_host_to_uvicorn(monkeypatch):
    uvicorn_run = Mock()
    monkeypatch.delenv("HG_DEV_RELOAD", raising=False)
    monkeypatch.setattr(app.uvicorn, "run", uvicorn_run)

    app.run_server(app.parse_args([]))

    uvicorn_run.assert_called_once_with(
        "hugegraph_llm.demo.rag_demo.app:create_app",
        host="127.0.0.1",
        port=8001,
        factory=True,
        reload=False,
    )


def test_run_server_warns_when_binding_non_loopback(monkeypatch):
    uvicorn_run = Mock()
    warning = Mock()
    monkeypatch.setattr(app.uvicorn, "run", uvicorn_run)
    monkeypatch.setattr(app.log, "warning", warning)

    app.run_server(app.parse_args(["--host", "0.0.0.0"]))

    warning.assert_called_once()
    message = warning.call_args.args[0]
    assert "no unified authentication" in message.lower()
    assert "reverse proxy authentication" in message.lower()
    assert "firewall" in message.lower()
    assert "trusted network" in message.lower()
    uvicorn_run.assert_called_once()
    assert uvicorn_run.call_args.kwargs["host"] == "0.0.0.0"


def test_run_server_does_not_warn_for_loopback(monkeypatch):
    monkeypatch.setattr(app.uvicorn, "run", Mock())
    warning = Mock()
    monkeypatch.setattr(app.log, "warning", warning)

    app.run_server(app.parse_args(["--host", "::1"]))

    warning.assert_not_called()
