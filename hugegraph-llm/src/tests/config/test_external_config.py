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

import errno

import pytest
import yaml
from dotenv import dotenv_values

from hugegraph_llm.config.hugegraph_config import HugeGraphConfig
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.config.models import base_config
from tests.fixtures.saved_config import save_chat

pytestmark = pytest.mark.contract


def test_startup_reads_readonly_bootstrap_without_writes(saved_config):
    _, env, _ = saved_config
    assert not env.exists() and not base_config.settings_path().exists()
    env.write_text("OPENAI_API_KEY=synthetic-default\nWINDOW_SIZE=9\n")
    env.chmod(0o444)
    before = env.read_bytes()
    loaded = LLMConfig()
    assert loaded.window_size == 9 and loaded.openai_chat_api_key == "synthetic-default"
    assert loaded.extract_use_chat and loaded.text2gql_use_chat
    assert env.read_bytes() == before and not base_config.settings_path().exists()


def test_saved_complete_connection_survives_deployment_upgrade(saved_config, monkeypatch):
    _, env, client = saved_config
    env.write_text("# deployment owned\nOPENAI_API_KEY=old-default\n")
    assert save_chat(client).status_code == 201
    before = env.read_bytes()
    monkeypatch.setenv("CHAT_LLM_TYPE", "litellm")
    monkeypatch.setenv("OPENAI_API_KEY", "new-deployment-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://upgraded.invalid/v1")
    env.write_bytes(before + b"WINDOW_SIZE=13\n")
    reloaded = LLMConfig()
    assert (
        reloaded.chat_llm_type,
        reloaded.openai_chat_api_base,
        reloaded.openai_chat_language_model,
        reloaded.openai_chat_api_key,
    ) == ("openai", "http://saved.invalid/v1", "saved-model", "synthetic-user-key")
    assert reloaded.window_size == 13
    assert "new-deployment-secret" not in base_config.settings_path().read_text()
    assert env.read_bytes() == before + b"WINDOW_SIZE=13\n"
    assert base_config.settings_path().stat().st_mode & 0o777 == 0o600


def test_offline_saved_edit_is_loaded_on_restart(saved_config):
    _, _, client = saved_config
    save_chat(client)
    path = base_config.settings_path()
    document = yaml.safe_load(path.read_text())
    document["llm"]["chat"]["openai_chat_language_model"] = "offline-model"
    path.write_text(yaml.safe_dump(document))
    assert LLMConfig().openai_chat_language_model == "offline-model"


@pytest.mark.parametrize("field", ["options", "chat"])
def test_saved_connection_cannot_mix_unknown_or_options_fields(saved_config, field):
    base_config.settings_path().write_text(
        yaml.safe_dump({"llm": {field: {"openai_chat_api_key" if field == "options" else "graph_pwd": "bad"}}})
    )
    with pytest.raises(ValueError):
        LLMConfig()


def test_env_destination_never_uses_file_secret(saved_config, monkeypatch):
    _, env, _ = saved_config
    env.write_text("OPENAI_CHAT_API_BASE=https://old.invalid/v1\nOPENAI_CHAT_API_KEY=old-file-key\n")
    monkeypatch.setenv("OPENAI_CHAT_API_BASE", "https://new.invalid/v1")
    loaded = LLMConfig()
    assert loaded.openai_chat_api_base == "https://new.invalid/v1"
    assert loaded.openai_chat_api_key is None


def test_empty_aliases_and_typed_defaults(saved_config, monkeypatch):
    _, env, _ = saved_config
    env.write_text("OPENAI_CHAT_API_KEY=\nOPENAI_API_KEY=generic-key\nOLLAMA_CHAT_PORT=\n")
    monkeypatch.setenv("OPENAI_CHAT_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")
    loaded = LLMConfig()
    assert loaded.openai_chat_api_key == "process-key" and loaded.ollama_chat_port == 11434
    assert loaded.extract_use_chat


def test_explicit_empty_graph_password_does_not_reuse_file(saved_config, monkeypatch):
    _, env, _ = saved_config
    env.write_text("GRAPH_URL=http://old.invalid\nGRAPH_PWD=old-password\n")
    monkeypatch.setenv("GRAPH_URL", "http://new.invalid")
    monkeypatch.setenv("GRAPH_PWD", "")
    assert HugeGraphConfig().graph_pwd == ""


@pytest.mark.parametrize("failure", [errno.EACCES, errno.ENOSPC])
def test_failed_save_preserves_memory_disk_and_bootstrap(saved_config, monkeypatch, failure):
    settings, env, client = saved_config
    env.write_text("# untouched\n")
    assert save_chat(client).status_code == 201
    before, disk = settings.model_dump(), base_config.settings_path().read_bytes()

    def reject(*_):
        raise OSError(failure, "synthetic storage failure")

    monkeypatch.setattr(base_config.os, "replace", reject)
    response = save_chat(client, api_key="other-key", language_model="other-model")
    assert response.status_code == 503
    assert settings.model_dump() == before and base_config.settings_path().read_bytes() == disk
    assert env.read_text() == "# untouched\n"
    assert not list(env.parent.glob(".settings-*"))


def test_single_file_mount_fallback_and_existing_mode(saved_config, monkeypatch):
    settings, _, client = saved_config
    save_chat(client)
    path = base_config.settings_path()
    path.chmod(0o660)
    inode = path.stat().st_ino

    def busy(*_):
        raise OSError(errno.EBUSY, "synthetic mount")

    monkeypatch.setattr(base_config.os, "replace", busy)
    assert save_chat(client, api_key="", language_model="changed").status_code == 201
    assert path.stat().st_ino == inode and path.stat().st_mode & 0o777 == 0o660
    assert LLMConfig().openai_chat_language_model == "changed"
    assert settings.openai_chat_api_key == "synthetic-user-key"


def test_resource_volume_holds_saved_state_separate_from_external_dotenv(saved_config, monkeypatch, tmp_path):
    _, _, client = saved_config
    root = tmp_path / "volume"
    monkeypatch.setenv("HUGEGRAPH_LLM_RESOURCE_PATH", str(root))
    assert save_chat(client).status_code == 201
    assert (root / "settings.yaml").exists()
    assert not (root / ".env").exists()


def test_export_does_not_create_phantom_role_key_clears(saved_config, monkeypatch):
    settings, env, _ = saved_config
    settings.generate_env()
    assert "OPENAI_EXTRACT_API_KEY=" not in env.read_text()
    reloaded = LLMConfig()
    assert reloaded.extract_use_chat and reloaded.text2gql_use_chat


def test_export_omits_process_secrets(saved_config, monkeypatch):
    _, env, _ = saved_config
    monkeypatch.setenv("OPENAI_API_KEY", "deployment-secret")
    LLMConfig().generate_env()
    assert "deployment-secret" not in env.read_text()


def test_export_preserves_unrelated_lines_and_dynamic_references(saved_config, monkeypatch):
    _, env, _ = saved_config
    env.write_text(
        "# Deployment owned values\n"
        "CUSTOM_ENDPOINT=${HOST}/v1\n"
        "export UNRELATED_SECRET=${SOURCE_SECRET}\n"
        "GRAPH_URL=${HOST}\n"
        "GRAPH_PWD=${SOURCE_SECRET}\n"
    )
    monkeypatch.setenv("HOST", "http://first.invalid")
    monkeypatch.setenv("SOURCE_SECRET", "synthetic-original-secret")
    monkeypatch.setattr("builtins.input", lambda _: "y")

    LLMConfig().generate_env()
    HugeGraphConfig().generate_env()

    text = env.read_text()
    assert "# Deployment owned values\n" in text
    assert "CUSTOM_ENDPOINT=${HOST}/v1\n" in text
    assert "export UNRELATED_SECRET=${SOURCE_SECRET}\n" in text
    assert "GRAPH_URL=${HOST}\n" in text
    assert "GRAPH_PWD=${SOURCE_SECRET}\n" in text
    assert "synthetic-original-secret" not in text
    monkeypatch.setenv("HOST", "http://second.invalid")
    monkeypatch.setenv("SOURCE_SECRET", "synthetic-rotated-secret")
    values = dotenv_values(env)
    assert values["CUSTOM_ENDPOINT"] == "http://second.invalid/v1"
    assert values["UNRELATED_SECRET"] == "synthetic-rotated-secret"
    assert values["GRAPH_URL"] == "http://second.invalid"
    assert values["GRAPH_PWD"] == "synthetic-rotated-secret"


def test_export_rewrites_an_explicitly_changed_owned_value(saved_config, monkeypatch):
    _, env, _ = saved_config
    env.write_text("# retained\nGRAPH_URL=${HOST}\n")
    monkeypatch.setenv("HOST", "http://before.invalid")
    monkeypatch.setattr("builtins.input", lambda _: "y")
    graph = HugeGraphConfig()
    graph.graph_url = "http://after.invalid"

    graph.generate_env()

    text = env.read_text()
    assert "# retained\n" in text and "GRAPH_URL=${HOST}" not in text
    assert dotenv_values(env)["GRAPH_URL"] == "http://after.invalid"


def test_generate_command_keeps_all_sections(saved_config, monkeypatch):
    from hugegraph_llm.config.admin_config import AdminConfig

    settings, env, _ = saved_config
    monkeypatch.setattr("builtins.input", lambda _: "y")
    HugeGraphConfig().generate_env()
    AdminConfig().generate_env()
    settings.generate_env()
    text = env.read_text()
    assert "GRAPH_URL=" in text and "ADMIN_TOKEN=" in text and "CHAT_LLM_TYPE=" in text


def test_explicit_save_of_unchanged_defaults_is_durable(saved_config, monkeypatch):
    _, _, client = saved_config
    assert (
        save_chat(
            client, api_key=None, api_base="https://api.openai.com/v1", language_model="gpt-4.1-mini", max_tokens=8192
        ).status_code
        == 201
    )
    monkeypatch.setenv("OPENAI_CHAT_LANGUAGE_MODEL", "changed-deployment-default")
    assert LLMConfig().openai_chat_language_model == "gpt-4.1-mini"


def test_export_omits_case_insensitive_process_secret(saved_config, monkeypatch):
    _, env, _ = saved_config
    monkeypatch.setenv("openai_api_key", "lowercase-deployment-secret")
    LLMConfig().generate_env()
    assert "lowercase-deployment-secret" not in env.read_text()
