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


"""Verify source precedence without transferring credentials to a new endpoint."""

import os
from unittest.mock import Mock

import pytest

from hugegraph_llm.config.admin_config import AdminConfig
from hugegraph_llm.config.hugegraph_config import HugeGraphConfig
from hugegraph_llm.config.index_config import IndexConfig
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.config.models import base_config

pytestmark = pytest.mark.contract


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(base_config, "env_path", str(path))
    for name in list(os.environ):
        if name.upper().startswith(
            (
                "GRAPH_",
                "OPENAI_",
                "LITELLM_",
                "QDRANT_",
                "MILVUS_",
                "RERANKER_",
                "COHERE_",
                "CO_API_",
                "HUGEGRAPH_LLM_ENABLE_THIN_WRITES",
                "ENABLE_LOGIN",
                "USER_TOKEN",
                "ADMIN_TOKEN",
            )
        ):
            monkeypatch.delenv(name)
    return path


@pytest.mark.parametrize(
    ("file_url", "process_url", "preserved"),
    [
        ("http://graph.example", "http://graph.example:80", True),
        ("http://graph.example:80", "http://graph.example/", True),
        ("https://graph.example", "https://graph.example:443", True),
        ("https://graph.example:443", "https://graph.example/", True),
        (None, "http://127.0.0.1:8080", True),
        ("http://graph.example:80", "http://graph.example:8080", False),
    ],
)
def test_graph_password_uses_effective_canonical_endpoint(env_file, monkeypatch, file_url, process_url, preserved):
    text = (f"GRAPH_URL={file_url}\n" if file_url is not None else "") + "GRAPH_PWD=file-graph-key\n"
    env_file.write_text(text)
    monkeypatch.setenv("GRAPH_URL", process_url)
    settings = HugeGraphConfig()
    assert settings.graph_pwd == ("file-graph-key" if preserved else "")
    assert settings.environment_source("graph_pwd") == (None if preserved else "GRAPH_URL")
    assert env_file.read_text() == text


MODEL_ENDPOINTS = [
    *[
        (f"openai_{role}_api_base", f"openai_{role}_api_key", "OPENAI_BASE_URL")
        for role in ("chat", "extract", "text2gql")
    ],
    *[
        (f"{provider}_{role}_api_base", f"{provider}_{role}_api_key", f"{provider}_{role}_api_base".upper())
        for provider in ("openai", "litellm")
        for role in ("chat", "extract", "text2gql", "embedding")
    ],
    ("cohere_base_url", "reranker_api_key", "CO_API_URL"),
]


@pytest.mark.parametrize(("base", "key", "variable"), MODEL_ENDPOINTS)
@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("paired_process_key", [False, True])
def test_process_model_endpoint_does_not_inherit_another_endpoint_key(
    env_file, monkeypatch, base, key, variable, changed, paired_process_key
):
    text = f"{base.upper()}=https://old.example/v1\n{key.upper()}=file-provider-key\n"
    env_file.write_text(text)
    monkeypatch.setenv(variable, "https://new.example/v1" if changed else "https://old.example:443/v1/")
    if paired_process_key:
        monkeypatch.setenv(key.upper(), "process-provider-key")
    settings = LLMConfig()
    expected = "process-provider-key" if paired_process_key else (None if changed else "file-provider-key")
    assert getattr(settings, key) == expected
    if changed and not paired_process_key:
        assert settings.environment_source(key) == variable
    assert env_file.read_text() == text


@pytest.mark.parametrize("backend", ["qdrant", "milvus"])
@pytest.mark.parametrize("part", ["host", "port"])
@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("paired_process_key", [False, True])
def test_process_vector_target_does_not_inherit_file_credentials(
    env_file, monkeypatch, backend, part, changed, paired_process_key
):
    port = 6333 if backend == "qdrant" else 19530
    credentials = (
        {"api_key": "file-vector-key"} if backend == "qdrant" else {"user": "file-user", "password": "file-vector-key"}
    )
    text = f"{backend.upper()}_HOST=vector.example\n{backend.upper()}_PORT={port}\n"
    text += "".join(f"{backend.upper()}_{field.upper()}={value}\n" for field, value in credentials.items())
    env_file.write_text(text)
    variable = f"{backend}_{part}".upper()
    value = ("new.example" if changed else "VECTOR.example") if part == "host" else str(port + int(changed))
    monkeypatch.setenv(variable, value)
    if paired_process_key:
        for field in credentials:
            monkeypatch.setenv(f"{backend}_{field}".upper(), f"process-{field}")
    settings = IndexConfig()
    for field, old in credentials.items():
        empty = None if field == "api_key" else ""
        assert getattr(settings, f"{backend}_{field}") == (
            f"process-{field}" if paired_process_key else (empty if changed else old)
        )
    assert env_file.read_text() == text


@pytest.mark.parametrize(
    ("variable", "field", "value", "settings_type"),
    [
        ("OPENAI_BASE_URL", "openai_chat_api_base", "https://file.example/v1", LLMConfig),
        ("OPENAI_CHAT_LANGUAGE_MODEL", "openai_chat_language_model", "file-model", LLMConfig),
        ("COHERE_BASE_URL", "cohere_base_url", "https://file.example/rerank", LLMConfig),
        ("ENABLE_LOGIN", "enable_login", "True", AdminConfig),
        ("USER_TOKEN", "user_token", "file-user-token", AdminConfig),
    ],
)
def test_empty_optional_process_placeholder_falls_back_to_file(
    env_file, monkeypatch, variable, field, value, settings_type
):
    env_file.write_text(f"{field.upper()}={value}\n")
    monkeypatch.setenv(variable, "")
    settings = settings_type()
    assert getattr(settings, field) == value
    assert settings.environment_source(field) is None


def test_empty_specific_process_key_does_not_hide_nonempty_generic_alias(env_file, monkeypatch):
    monkeypatch.setenv("OPENAI_CHAT_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")
    settings = LLMConfig()
    assert settings.openai_chat_api_key == "process-key"
    assert settings.environment_source("openai_chat_api_key") == "OPENAI_API_KEY"


@pytest.mark.parametrize("value", ["1", "yes", "on", "invalid", "false", "0", "", "true", "TRUE", " true "])
def test_thin_writes_only_accept_explicit_true_without_validation_errors(env_file, monkeypatch, value):
    from hugegraph_llm.api import thin_api

    monkeypatch.setenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", value)
    monkeypatch.setattr(thin_api.admin_settings, "enable_login", "true")
    assert (thin_api._thin_write_disabled() is None) == (value.strip().lower() == "true")


def test_chat_apply_does_not_export_managed_key_through_cascade(env_file, monkeypatch):
    from fastapi.testclient import TestClient

    from hugegraph_llm.demo.rag_demo import app, configs_block

    monkeypatch.setenv("OPENAI_CHAT_API_KEY", "managed-chat-key")
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "false")
    settings = LLMConfig()
    monkeypatch.setattr(configs_block, "llm_settings", settings)
    monkeypatch.setattr(configs_block, "test_api_connection", Mock(return_value=200))
    monkeypatch.setattr(configs_block.gr, "Info", lambda *_args: None)
    ui = app.init_rag_ui()
    render = next(
        function
        for function in ui.fns.values()
        if getattr(getattr(getattr(function.fn, "__self__", None), "fn", None), "__name__", None) == "chat_llm_settings"
    )
    monkeypatch.setattr(app, "init_rag_ui", lambda: ui)
    client = TestClient(app.create_app())
    try:
        response = client.post(
            f"/gradio_api/run/{render.api_name}", json={"data": ["openai"], "session_hash": "chat-save"}
        )
        assert response.status_code == 200, response.text
        config = response.json()["render_config"]
        values = {component["id"]: component["props"].get("value") for component in config["components"]}
        clicks = [
            dependency
            for dependency in config["dependencies"]
            if any(target[1] == "click" for target in dependency["targets"]) and dependency["backend_fn"]
        ]
        assert clicks
        for dependency in clicks:
            result = client.post(
                f"/gradio_api/run/{dependency['api_name']}",
                json={"data": [values[field] for field in dependency["inputs"]], "session_hash": "chat-save"},
            )
            assert result.status_code == 200, result.text
        assert settings.openai_extract_api_key is None
        assert settings.openai_text2gql_api_key is None
        assert not env_file.exists() or "managed-chat-key" not in env_file.read_text()
    finally:
        client.close()


def test_constructor_key_still_has_highest_precedence_for_custom_endpoint(env_file, monkeypatch):
    env_file.write_text("OPENAI_CHAT_API_BASE=https://file.example/v1\n")
    monkeypatch.setenv("OPENAI_API_KEY", "unpaired-process-key")
    assert LLMConfig(openai_chat_api_key="constructor-key").openai_chat_api_key == "constructor-key"


@pytest.mark.parametrize("field", ["OPENAI_CHAT_API_KEY", "OPENAI_CHAT_LANGUAGE_MODEL"])
def test_explicit_empty_file_strings_remain_empty(env_file, monkeypatch, field):
    env_file.write_text(f"{field}=\n")
    monkeypatch.setenv(field, "")
    assert getattr(LLMConfig(), field.lower()) == ""


def test_empty_vector_port_placeholders_do_not_crash_module_import(env_file, monkeypatch):
    import subprocess
    import sys

    monkeypatch.setenv("QDRANT_PORT", "")
    monkeypatch.setenv("MILVUS_PORT", "")
    monkeypatch.setenv("HUGEGRAPH_LLM_ENV_PATH", str(env_file))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from hugegraph_llm.config.index_config import IndexConfig; "
            "s=IndexConfig(); assert (s.qdrant_port,s.milvus_port)==(6333,19530)",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("previous", "effective"), [("cohere", "siliconflow"), ("siliconflow", "cohere")])
def test_reranker_provider_change_does_not_transfer_file_key(env_file, monkeypatch, previous, effective):
    env_file.write_text(f"RERANKER_TYPE={previous}\nRERANKER_API_KEY=file-provider-key\n")
    monkeypatch.setenv("RERANKER_TYPE", effective)
    settings = LLMConfig()
    assert settings.reranker_type == effective
    assert settings.reranker_api_key is None
    assert settings.environment_source("reranker_api_key") == "RERANKER_TYPE"


def test_managed_reranker_key_also_owns_provider_before_probe(env_file, monkeypatch):
    from hugegraph_llm.demo.rag_demo import configs_block

    monkeypatch.setenv("RERANKER_API_KEY", "managed-provider-key")
    settings = LLMConfig(reranker_type="cohere")
    assert settings.environment_source("reranker_type") == "RERANKER_API_KEY"
    monkeypatch.setattr(configs_block, "llm_settings", settings)
    probe = Mock(return_value=200)
    monkeypatch.setattr(configs_block, "test_api_connection", probe)
    settings.reranker_type = "siliconflow"
    with pytest.raises(ValueError, match="managed by environment"):
        configs_block.apply_reranker_config("managed-provider-key", "model", None)
    probe.assert_not_called()
    assert not env_file.exists()
