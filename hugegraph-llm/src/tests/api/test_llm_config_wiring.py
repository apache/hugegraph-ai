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


"""Exercise deployment configuration through the real settings sources and files."""

from unittest.mock import Mock

import pytest

from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.config.models import base_config
from hugegraph_llm.demo.rag_demo import configs_block
from hugegraph_llm.models.llms import init_llm
from tests.fixtures.saved_config import save_chat

pytestmark = pytest.mark.contract


@pytest.mark.parametrize("provider", ["openai", "ollama/local"])
@pytest.mark.parametrize("role", ["chat", "extract", "text2gql"])
def test_save_api_persists_complete_role_without_any_network(saved_config, monkeypatch, role, provider):
    settings, _, client = saved_config
    probe = Mock(side_effect=AssertionError("Save must not contact a model service"))
    monkeypatch.setattr(configs_block, "test_api_connection", probe)
    monkeypatch.setattr(init_llm.OpenAIClient, "generate", probe)
    monkeypatch.setattr(init_llm.OllamaClient, "generate", probe)
    response = save_chat(client, role=role, llm_type=provider, host="127.0.0.1", port=11434)
    assert response.status_code == 201
    assert response.json() == {"message": "Configuration saved."}
    reloaded = LLMConfig()
    assert reloaded.group_values(role) == settings.group_values(role)
    assert getattr(reloaded, f"{role}_llm_type") == provider
    if role != "chat":
        assert not getattr(reloaded, f"{role}_use_chat")
    probe.assert_not_called()


@pytest.mark.parametrize("route", ["/config/llm", "/config/embedding"])
def test_removed_litellm_provider_is_not_accepted(saved_config, route):
    _, _, client = saved_config
    response = client.post(route, json={"llm_type": "litellm", "language_model": "model"})
    assert response.status_code == 422


def test_app_import_and_supported_clients_without_litellm(tmp_path):
    import os
    import subprocess
    import sys

    # Simulate an image that has never installed the optional LiteLLM package.
    code = '''
import builtins
original_import = builtins.__import__
def without_litellm(name, *args, **kwargs):
    if name == "litellm" or name.startswith("litellm."):
        raise ModuleNotFoundError("litellm deliberately unavailable")
    return original_import(name, *args, **kwargs)
builtins.__import__ = without_litellm
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.demo.rag_demo.app import create_app
from hugegraph_llm.models.embeddings.init_embedding import get_embedding
from hugegraph_llm.models.llms.init_llm import get_chat_llm
assert create_app() is not None
assert get_chat_llm(LLMConfig(chat_llm_type="openai")) is not None
assert get_chat_llm(LLMConfig(chat_llm_type="ollama/local")) is not None
assert get_embedding(LLMConfig(embedding_type="openai")) is not None
assert get_embedding(LLMConfig(embedding_type="ollama/local")) is not None
'''
    env = os.environ.copy()
    env.update(HUGEGRAPH_LLM_RESOURCE_PATH=str(tmp_path), GRADIO_ANALYTICS_ENABLED="false")
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("role", ["chat", "extract", "text2gql"])
@pytest.mark.parametrize("provider", ["openai"])
def test_blank_key_retains_and_explicit_clear_survives_restart(saved_config, role, provider, monkeypatch):
    settings, _, client = saved_config
    assert save_chat(client, role=role, llm_type=provider).status_code == 201
    assert save_chat(client, role=role, llm_type=provider, api_key="").status_code == 201
    field = f"{provider}_{role}_api_key"
    assert getattr(settings, field) == "synthetic-user-key"
    assert save_chat(client, role=role, llm_type=provider, api_key=None, clear_api_key=True).status_code == 201
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-return")
    assert getattr(LLMConfig(), field) is None
    factory = {
        "chat": init_llm.get_chat_llm,
        "extract": init_llm.get_extract_llm,
        "text2gql": init_llm.get_text2gql_llm,
    }[role]
    client_mock = Mock()
    monkeypatch.setattr(init_llm, "OpenAIClient", client_mock)
    factory(LLMConfig())


@pytest.mark.parametrize("kind", ["embedding", "reranker"])
def test_embedding_reranker_save_clear_are_independent(saved_config, kind):
    settings, _, client = saved_config
    url = "/config/embedding" if kind == "embedding" else "/config/rerank"
    payload = (
        {"llm_type": "openai", "api_base": "http://embed.invalid/v1", "language_model": "embed"}
        if kind == "embedding"
        else {"reranker_type": "siliconflow", "reranker_model": "rerank"}
    )
    assert client.post(url, json={**payload, "api_key": "synthetic-other-key"}).status_code == 201
    assert client.post(url, json=payload).status_code == 201
    key = "openai_embedding_api_key" if kind == "embedding" else "reranker_api_key"
    assert getattr(LLMConfig(), key) == "synthetic-other-key"
    assert client.post(url, json={**payload, "clear_api_key": True}).status_code == 201
    assert getattr(LLMConfig(), key) is None
    assert not base_config.settings_path().read_text().count("synthetic-other-key")
    assert settings.extract_use_chat and settings.text2gql_use_chat


@pytest.mark.parametrize("role", ["extract", "text2gql"])
def test_role_dynamically_follows_chat_and_can_opt_out_and_restore(saved_config, monkeypatch, role):
    _, _, client = saved_config
    factory = init_llm.get_extract_llm if role == "extract" else init_llm.get_text2gql_llm
    constructor = Mock()
    monkeypatch.setattr(init_llm, "OpenAIClient", constructor)
    save_chat(client)
    for name in ("first-chat", "updated-chat"):
        save_chat(client, api_key="", language_model=name)
        factory(LLMConfig())
        assert constructor.call_args.kwargs["model_name"] == name
    save_chat(client, role=role, language_model="independent")
    save_chat(client, api_key="", language_model="latest-chat")
    factory(LLMConfig())
    assert constructor.call_args.kwargs["model_name"] == "independent"
    assert client.post(f"/config/llm/{role}/use-chat").status_code == 200
    factory(LLMConfig())
    assert constructor.call_args.kwargs["model_name"] == "latest-chat"
    assert "synthetic-user-key" not in str(LLMConfig().group_values(role))


@pytest.mark.parametrize(
    "bad",
    [
        {"api_base": "broken"},
        {"language_model": ""},
        {"max_tokens": 0},
        {"api_base": "http://host:bad"},
        {"api_base": "https://user:secret@host"},
        {"api_key": "", "clear_api_key": False, "api_base": "http://changed.invalid"},
        {"api_key": "new", "clear_api_key": True},
    ],
)
def test_invalid_save_keeps_last_good_connection(saved_config, bad):
    settings, _, client = saved_config
    save_chat(client)
    before, disk = settings.model_dump(), base_config.settings_path().read_bytes()
    response = save_chat(client, **bad)
    assert response.status_code in (400, 422)
    assert settings.model_dump() == before and base_config.settings_path().read_bytes() == disk


def test_render_model_form_does_not_activate_provider_or_echo_key(saved_config, monkeypatch):
    settings, _, client = saved_config
    save_chat(client)
    before = settings.model_dump()
    fields = []

    class Widget:
        def __init__(self, **kwargs):
            fields.append(kwargs)

        def click(self, *_args, **_kwargs):
            pass

    for name in ("Textbox", "Checkbox"):
        monkeypatch.setattr(configs_block.gr, name, Widget)
    monkeypatch.setattr(configs_block.gr, "Button", lambda *_: Widget())
    configs_block._model_form("chat", "ollama/local")
    assert settings.model_dump() == before
    assert all(f.get("value") != "synthetic-user-key" for f in fields)


@pytest.mark.parametrize("role", ["chat", "extract", "text2gql", "embedding", "reranker"])
def test_empty_provider_response_is_a_failed_test_without_undoing_save(saved_config, monkeypatch, role):
    _, _, client = saved_config
    save_chat(client)
    from hugegraph_llm.models.embeddings import init_embedding
    from hugegraph_llm.models.rerankers.cohere import CohereReranker

    if role == "embedding":
        monkeypatch.setattr(init_embedding.OpenAIEmbedding, "get_text_embedding", lambda *_: [])
    elif role == "reranker":
        client.post(
            "/config/rerank",
            json={"reranker_type": "cohere", "reranker_model": "rerank", "cohere_base_url": "http://rerank.invalid/v1"},
        )
        monkeypatch.setattr(CohereReranker, "get_rerank_lists", lambda *_: [])
    else:
        monkeypatch.setattr(init_llm.OpenAIClient, "generate", lambda *_args, **_kwargs: "")
    before = base_config.settings_path().read_bytes()
    assert client.post(f"/config/model/{role}/test").status_code == 502
    assert base_config.settings_path().read_bytes() == before


def test_web_form_saves_selected_provider_and_updates_inheritance_control(saved_config, monkeypatch):
    from functools import partial

    from fastapi.testclient import TestClient

    from hugegraph_llm.demo.rag_demo import app

    settings, _, _ = saved_config
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "false")
    monkeypatch.setattr(app.admin_settings, "enable_login", "false")
    ui = app.init_rag_ui()
    render = next(
        function
        for function in ui.fns.values()
        if getattr(getattr(getattr(function.fn, "__self__", None), "fn", None), "__name__", None)
        == "extract_llm_settings"
    )
    monkeypatch.setattr(app, "init_rag_ui", lambda: ui)
    client = TestClient(app.create_app())
    try:
        response = client.post(
            f"/gradio_api/run/{render.api_name}", json={"data": ["openai"], "session_hash": "scope-web-save"}
        )
        assert response.status_code == 200
        save = next(
            function
            for function in ui.state_holder["scope-web-save"].blocks_config.fns.values()
            if isinstance(function.fn, partial)
            and function.fn.func is configs_block.save_model_form
            and function.fn.args == ("extract", "openai")
        )
        response = client.post(
            f"/gradio_api/run/{save.api_name}",
            json={
                "data": ["synthetic-web-key", "http://127.0.0.1:9/v1", "openai/web", "100", False],
                "session_hash": "scope-web-save",
            },
        )
        assert response.status_code == 200 and response.json()["data"] == [False], response.text
        loaded = LLMConfig()
        assert not settings.extract_use_chat and not loaded.extract_use_chat
        assert loaded.extract_llm_type == "openai" and loaded.openai_extract_language_model == "openai/web"
        assert loaded.openai_extract_api_key == "synthetic-web-key"
        assert settings.chat_llm_type == "openai"
        assert "synthetic-web-key" not in response.text
    finally:
        client.close()
        ui.close()


@pytest.mark.parametrize("role", ["chat", "extract", "text2gql", "embedding"])
def test_same_openai_provider_model_change_keeps_key(saved_config, role):
    _, _, client = saved_config
    route = "/config/embedding" if role == "embedding" else "/config/llm"
    payload = {
        "llm_type": "openai",
        "role": "chat" if role == "embedding" else role,
        "api_base": "http://proxy.invalid/v1",
        "language_model": "openai/first",
        "api_key": "synthetic-key",
    }
    assert client.post(route, json=payload).status_code == 201
    assert client.post(route, json={**payload, "language_model": "openai/second", "api_key": ""}).status_code == 201
    loaded = LLMConfig()
    assert getattr(loaded, f"openai_{role}_api_key") == "synthetic-key"
    model_field = f"openai_{role}_model" if role == "embedding" else f"openai_{role}_language_model"
    assert getattr(loaded, model_field) == "openai/second"
