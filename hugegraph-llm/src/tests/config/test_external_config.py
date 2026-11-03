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

import os

import pytest
from dotenv import dotenv_values

from hugegraph_llm.config.hugegraph_config import HugeGraphConfig
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.config.models import base_config
from hugegraph_llm.config.models.base_config import BaseConfig

pytestmark = pytest.mark.contract


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(base_config, "env_path", str(path))
    for name in list(os.environ):
        if name.startswith(("OPENAI_", "GRAPH_")):
            monkeypatch.delenv(name)
    return path


def test_process_secret_overrides_persisted_derivatives_without_writing(env_file, monkeypatch):
    env_file.write_text("OPENAI_CHAT_API_KEY=stale\nOPENAI_EXTRACT_API_KEY=old\n")
    before = env_file.read_bytes()
    monkeypatch.setenv("OPENAI_API_KEY", "rotated")
    settings = LLMConfig()
    assert settings.openai_chat_api_key == "rotated"
    assert settings.openai_extract_api_key == "rotated"
    monkeypatch.setenv("OPENAI_CHAT_API_KEY", "chat-only")
    assert LLMConfig().openai_chat_api_key == "chat-only"
    monkeypatch.setenv("OPENAI_API_KEY", "rotated-again")
    assert LLMConfig().openai_extract_api_key == "rotated-again"
    assert env_file.read_bytes() == before
    assert "OPENAI_EXTRACT_API_KEY" not in os.environ


def test_file_aliases_are_loaded_without_mutating_environment(env_file):
    env_file.write_text("OPENAI_API_KEY=generic\nOPENAI_CHAT_API_KEY=specific\n")
    settings = LLMConfig()
    assert settings.openai_chat_api_key == "specific"
    assert settings.openai_extract_api_key == "generic"
    assert "OPENAI_API_KEY" not in os.environ


def test_startup_neither_creates_nor_updates_dotenv(env_file):
    LLMConfig()
    assert not env_file.exists()
    env_file.write_text("# mounted read-only configuration\nWINDOW_SIZE=9\n")
    env_file.chmod(0o444)
    before = env_file.read_bytes()
    assert LLMConfig().window_size == 9
    assert env_file.read_bytes() == before


def test_save_preserves_external_edits_and_does_not_export_environment(env_file, monkeypatch):
    env_file.write_text("WINDOW_SIZE=8\nLANGUAGE=EN\n")
    monkeypatch.setenv("OPENAI_API_KEY", "private-secret")
    settings = LLMConfig()
    # A user edits a different field between load and save.
    env_file.write_text("# keep comment\nWINDOW_SIZE=12\nLANGUAGE=EN\n")
    settings.language = "CN"
    settings.update_env()
    saved = dotenv_values(env_file)
    assert saved == {"WINDOW_SIZE": "12", "LANGUAGE": "CN"}
    assert "private-secret" not in env_file.read_text()
    assert "# keep comment" in env_file.read_text()
    assert env_file.stat().st_mode & 0o777 == 0o600


def test_managed_ui_change_is_rejected_without_changing_file(env_file, monkeypatch):
    env_file.write_text("LANGUAGE=EN\n")
    monkeypatch.setenv("OPENAI_API_KEY", "managed")
    settings = LLMConfig()
    settings.openai_chat_api_key = "ui-value"
    with pytest.raises(ValueError, match="managed by environment"):
        settings.update_env()
    assert env_file.read_text() == "LANGUAGE=EN\n"


def test_empty_password_clears_old_endpoint_credentials(env_file, monkeypatch):
    env_file.write_text("GRAPH_URL=http://old:8080\nGRAPH_PWD=old-private-password\n")
    monkeypatch.setenv("GRAPH_URL", "http://new:8080")
    monkeypatch.setenv("GRAPH_PWD", "")
    settings = HugeGraphConfig()
    assert settings.graph_url == "http://new:8080"
    assert settings.graph_pwd == ""


def test_failed_atomic_save_leaves_original_intact(env_file, monkeypatch):
    env_file.write_text("LANGUAGE=EN\n")
    settings = LLMConfig()
    settings.language = "CN"

    def fail_replace(*args):
        raise OSError("read-only mounted file")

    monkeypatch.setattr(base_config.os, "replace", fail_replace)
    with pytest.raises(OSError, match="read-only"):
        settings.update_env()
    assert env_file.read_text() == "LANGUAGE=EN\n"
    assert list(env_file.parent.glob(".env-*")) == []


def test_reload_validates_without_persisting_defaults(env_file):
    class Settings(BaseConfig):
        count: int = 1

    env_file.write_text("COUNT=7\n")
    settings = Settings()
    env_file.write_text("COUNT=bad\n")
    with pytest.raises(ValueError):
        settings.check_env()
    assert settings.count == 7


def test_resource_root_moves_both_configuration_and_generated_data(tmp_path, monkeypatch):
    from hugegraph_llm.config import paths
    from hugegraph_llm.config.models.base_prompt_config import resolve_prompt_yaml_path

    packaged = tmp_path / "packaged"
    (packaged / "demo").mkdir(parents=True)
    (packaged / "demo" / "example.txt").write_text("default")
    target = tmp_path / "data"
    monkeypatch.setattr(paths, "PACKAGED_RESOURCES", packaged)
    monkeypatch.setenv("HUGEGRAPH_LLM_RESOURCE_PATH", str(target))
    monkeypatch.delenv("HUGEGRAPH_LLM_ENV_PATH", raising=False)
    monkeypatch.delenv("HUGEGRAPH_LLM_PROMPT_CONFIG_PATH", raising=False)
    assert paths.ensure_resources() == str(target)
    assert base_config.resolve_env_path() == str(target / ".env")
    assert resolve_prompt_yaml_path() == str(target / "demo" / "config_prompt.yaml")
    example = target / "demo" / "example.txt"
    assert example.read_text() == "default"
    example.write_text("user edit")
    paths.ensure_resources()
    assert example.read_text() == "user edit"


def test_managed_api_update_rolls_back_memory_and_disk(env_file, monkeypatch):
    from hugegraph_llm.demo.rag_demo import configs_block

    env_file.write_text("LANGUAGE=EN\n")
    monkeypatch.setenv("OPENAI_API_KEY", "managed")
    settings = LLMConfig()
    monkeypatch.setattr(configs_block, "llm_settings", settings)
    monkeypatch.setattr(configs_block, "test_api_connection", lambda *args, **kwargs: 200)
    with pytest.raises(ValueError, match="managed by environment"):
        configs_block.apply_llm_config("chat", "override", "https://example.invalid/v1", "model", 100)
    assert settings.openai_chat_api_key == "managed"
    assert env_file.read_text() == "LANGUAGE=EN\n"


def test_explicit_constructor_values_override_alias_environment(env_file, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "managed")
    assert LLMConfig(openai_chat_api_key="explicit").openai_chat_api_key == "explicit"
