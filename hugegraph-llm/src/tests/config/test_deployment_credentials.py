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

import pytest
import yaml

from hugegraph_llm import config
from hugegraph_llm.config.hugegraph_config import HugeGraphConfig
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.config.models import base_config
from hugegraph_llm.demo.rag_demo import configs_block
from tests.fixtures.saved_config import save_chat

pytestmark = pytest.mark.contract


def _reload_runtime(monkeypatch):
    settings = LLMConfig()
    monkeypatch.setattr(config, "llm_settings", settings)
    monkeypatch.setattr(configs_block, "llm_settings", settings)
    return settings


def test_file_endpoint_with_secret_and_ui_save_tracks_rotation(saved_config, monkeypatch):
    _, env, client = saved_config
    env.write_text(
        "OPENAI_CHAT_API_BASE=https://proxy.example/v1\n"
        "OPENAI_CHAT_LANGUAGE_MODEL=file-model\n"
        "EXTRACT_LLM_TYPE=ollama/local\nOLLAMA_EXTRACT_LANGUAGE_MODEL=local-model\n"
        "OPENAI_CHAT_API_KEY=old-file-secret\n"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "secret-one")
    settings = _reload_runtime(monkeypatch)
    assert (settings.openai_chat_api_base, settings.openai_chat_language_model, settings.openai_chat_api_key) == (
        "https://proxy.example/v1",
        "file-model",
        "secret-one",
    )
    assert settings.extract_llm_type == "ollama/local" and not settings.extract_use_chat
    response = save_chat(client, api_key="", api_base="https://proxy.example/v1", language_model="ui-model")
    assert response.status_code == 201
    document = yaml.safe_load(base_config.settings_path().read_text())
    assert "secret-one" not in base_config.settings_path().read_text()
    assert document["llm"]["chat"]["_env_secrets"]["openai_chat_api_key"] == "OPENAI_API_KEY"

    monkeypatch.setenv("OPENAI_API_KEY", "secret-two")
    monkeypatch.setenv("OPENAI_CHAT_API_BASE", "https://new-deployment-default.example/v1")
    reloaded = LLMConfig()
    assert (reloaded.openai_chat_api_base, reloaded.openai_chat_language_model, reloaded.openai_chat_api_key) == (
        "https://proxy.example/v1",
        "ui-model",
        "secret-two",
    )
    monkeypatch.delenv("OPENAI_API_KEY")
    assert LLMConfig().openai_chat_api_key is None  # no fallback to the stale file secret


def test_ui_address_change_requires_key_and_explicit_key_replaces_secret(saved_config, monkeypatch):
    _, env, client = saved_config
    env.write_text("OPENAI_CHAT_API_BASE=https://proxy.example/v1\nOPENAI_CHAT_LANGUAGE_MODEL=file-model\n")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-one")
    settings = _reload_runtime(monkeypatch)
    response = save_chat(client, api_key="", api_base="https://other.example/v1", language_model="file-model")
    assert response.status_code >= 400
    assert settings.openai_chat_api_base == "https://proxy.example/v1"
    assert not base_config.settings_path().exists()

    response = save_chat(client, api_key="new-ui-key", api_base="https://other.example/v1", language_model="file-model")
    assert response.status_code == 201
    monkeypatch.setenv("OPENAI_API_KEY", "rotated-secret")
    loaded = LLMConfig()
    assert loaded.openai_chat_api_base == "https://other.example/v1"
    assert loaded.openai_chat_api_key == "new-ui-key"


def test_web_provider_switch_requires_key_and_does_not_forward_old_secret(saved_config, monkeypatch):
    _, env, client = saved_config
    env.write_text("OPENAI_CHAT_API_BASE=https://proxy.example/v1\nOPENAI_CHAT_LANGUAGE_MODEL=file-model\n")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-one")
    _reload_runtime(monkeypatch)
    assert (
        save_chat(client, api_key="", api_base="https://proxy.example/v1", language_model="same-provider").status_code
        == 201
    )
    assert LLMConfig().openai_chat_api_key == "secret-one"
    response = save_chat(client, llm_type="ollama/local", host="localhost", port=11434, language_model="local-model")
    assert response.status_code == 201
    reloaded = LLMConfig()
    assert (reloaded.chat_llm_type, reloaded.ollama_chat_host, reloaded.ollama_chat_language_model) == (
        "ollama/local",
        "localhost",
        "local-model",
    )
    assert "secret-one" not in base_config.settings_path().read_text()


def test_web_explicit_key_equal_to_secret_is_saved_as_user_key(saved_config, monkeypatch):
    _, env, client = saved_config
    env.write_text("OPENAI_CHAT_API_BASE=https://proxy.example/v1\nOPENAI_CHAT_LANGUAGE_MODEL=file-model\n")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-one")
    _reload_runtime(monkeypatch)
    response = save_chat(client, api_key="secret-one", api_base="https://proxy.example/v1", language_model="file-model")
    assert response.status_code == 201
    monkeypatch.setenv("OPENAI_API_KEY", "secret-two")
    assert LLMConfig().openai_chat_api_key == "secret-one"


def test_saved_env_reference_obeys_specific_alias_priority(saved_config, monkeypatch):
    _, env, client = saved_config
    env.write_text("OPENAI_CHAT_API_BASE=https://proxy.example/v1\nOPENAI_CHAT_LANGUAGE_MODEL=file-model\n")
    monkeypatch.setenv("OPENAI_API_KEY", "generic-key")
    monkeypatch.setenv("OPENAI_CHAT_API_KEY", "specific-key")
    settings = _reload_runtime(monkeypatch)
    assert settings.openai_chat_api_key == "specific-key"
    assert (
        save_chat(client, api_key="", api_base="https://proxy.example/v1", language_model="ui-model").status_code == 201
    )
    document = yaml.safe_load(base_config.settings_path().read_text())
    assert document["llm"]["chat"]["_env_secrets"]["openai_chat_api_key"] == "OPENAI_CHAT_API_KEY"
    monkeypatch.setenv("OPENAI_CHAT_API_KEY", "rotated-specific-key")
    assert LLMConfig().openai_chat_api_key == "rotated-specific-key"
    monkeypatch.delenv("OPENAI_CHAT_API_KEY")
    assert LLMConfig().openai_chat_api_key is None  # never fall back to generic-key


def test_graph_file_endpoint_and_secret_follow_rotation(saved_config, monkeypatch):
    _, env, _ = saved_config
    env.write_text("GRAPH_URL=http://file.example:8080\nGRAPH_USER=file-user\nGRAPH_PWD=file-secret\n")
    monkeypatch.setenv("GRAPH_PWD", "graph-secret-one")
    graph = HugeGraphConfig()
    assert (graph.graph_url, graph.graph_user, graph.graph_pwd) == (
        "http://file.example:8080",
        "file-user",
        "graph-secret-one",
    )
    graph.graph_name = "another-graph"
    graph.update_env(connection_group="connection")
    assert "graph-secret-one" not in base_config.settings_path().read_text()
    monkeypatch.setenv("GRAPH_PWD", "graph-secret-two")
    assert HugeGraphConfig().graph_pwd == "graph-secret-two"
    monkeypatch.delenv("GRAPH_PWD")
    assert HugeGraphConfig().graph_pwd == ""


def test_graph_web_switch_cannot_send_previous_password_to_new_host(saved_config, monkeypatch):
    _, env, _ = saved_config
    env.write_text("GRAPH_URL=http://file.example:8080\nGRAPH_USER=file-user\n")
    monkeypatch.setenv("GRAPH_PWD", "graph-secret")
    graph = HugeGraphConfig()
    monkeypatch.setattr(configs_block, "huge_settings", graph)
    sent = []
    monkeypatch.setattr(configs_block, "test_api_connection", lambda url, **kwargs: sent.append((url, kwargs)) or 200)
    with pytest.raises(ValueError, match="re-entering"):
        configs_block.apply_graph_config("http://other.example:8080", "hugegraph", "file-user", "", "")
    assert not sent
    assert configs_block.apply_graph_config("http://file.example:8080", "renamed", "file-user", "", "") == 200
    assert "graph-secret" not in base_config.settings_path().read_text()
    assert (
        configs_block.apply_graph_config("http://other.example:8080", "renamed", "file-user", "graph-secret", "") == 200
    )
    assert sent[-1][0] == "http://other.example:8080/graphs/renamed/schema"


def test_deployment_endpoint_override_does_not_send_file_key(saved_config, monkeypatch):
    _, env, _ = saved_config
    env.write_text("OPENAI_CHAT_API_BASE=https://file.example/v1\nOPENAI_CHAT_API_KEY=file-key\n")
    monkeypatch.setenv("OPENAI_CHAT_API_BASE", "https://new.example/v1")
    loaded = LLMConfig()
    assert loaded.openai_chat_api_base == "https://new.example/v1" and loaded.openai_chat_api_key is None


def test_same_deployment_provider_does_not_discard_file_connection(saved_config, monkeypatch):
    _, env, _ = saved_config
    env.write_text("OPENAI_CHAT_API_BASE=https://file.example/v1\nOPENAI_CHAT_API_KEY=file-key\n")
    monkeypatch.setenv("CHAT_LLM_TYPE", "openai")
    loaded = LLMConfig()
    assert loaded.openai_chat_api_base == "https://file.example/v1" and loaded.openai_chat_api_key == "file-key"
