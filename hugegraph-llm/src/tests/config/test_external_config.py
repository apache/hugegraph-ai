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
    mode_before = env_file.stat().st_mode & 0o777
    settings.language = "CN"
    settings.update_env()
    saved = dotenv_values(env_file)
    assert saved == {"WINDOW_SIZE": "12", "LANGUAGE": "CN"}
    assert "private-secret" not in env_file.read_text()
    assert "# keep comment" in env_file.read_text()
    assert env_file.stat().st_mode & 0o777 == mode_before


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


def test_resource_root_uses_assets_without_startup_copies(tmp_path, monkeypatch):
    from hugegraph_llm.config import paths
    from hugegraph_llm.config.models.base_prompt_config import resolve_prompt_yaml_path

    packaged = tmp_path / "packaged"
    (packaged / "demo").mkdir(parents=True)
    (packaged / "demo" / "example.txt").write_text("default")
    target = packaged / "data"
    monkeypatch.setattr(paths, "PACKAGED_RESOURCES", packaged)
    monkeypatch.setenv("HUGEGRAPH_LLM_RESOURCE_PATH", str(target))
    monkeypatch.delenv("HUGEGRAPH_LLM_ENV_PATH", raising=False)
    monkeypatch.delenv("HUGEGRAPH_LLM_PROMPT_CONFIG_PATH", raising=False)
    assert paths.resolve_resource_path() == target
    assert paths.resource_file("demo", "example.txt") == str(packaged / "demo" / "example.txt")
    assert not target.exists()
    assert base_config.resolve_env_path() == str(target / ".env")
    assert resolve_prompt_yaml_path() == str(target / "demo" / "config_prompt.yaml")
    (target / "demo").mkdir(parents=True)
    example = target / "demo" / "example.txt"
    example.write_text("user edit")
    assert paths.resource_file("demo", "example.txt") == str(example)


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


@pytest.mark.parametrize("field", ["WINDOW_SIZE", "OPENAI_CHAT_TOKENS"])
def test_empty_typed_process_values_use_file_or_default(env_file, monkeypatch, field):
    env_file.write_text(f"{field}=12\n")
    monkeypatch.setenv(field, "")
    settings = LLMConfig()
    assert getattr(settings, field.lower()) == 12
    assert settings.environment_source(field.lower()) is None


def test_empty_required_process_string_does_not_erase_default(env_file, monkeypatch):
    monkeypatch.setenv("GRAPH_URL", "")
    assert HugeGraphConfig().graph_url == "http://127.0.0.1:8080"


def test_cleared_file_password_survives_save_and_reload(env_file):
    settings = HugeGraphConfig()
    settings.graph_pwd = ""
    settings.update_env()
    assert HugeGraphConfig().graph_pwd == ""


def test_proxy_credentials_stay_paired_with_file_endpoint(env_file, monkeypatch):
    env_file.write_text("OPENAI_CHAT_API_BASE=https://proxy.example/v1\nOPENAI_CHAT_API_KEY=proxy-key\n")
    monkeypatch.setenv("OPENAI_API_KEY", "private-process-key")
    settings = LLMConfig()
    assert (settings.openai_chat_api_base, settings.openai_chat_api_key) == ("https://proxy.example/v1", "proxy-key")
    assert settings.environment_source("openai_chat_api_key") is None
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    settings = LLMConfig()
    assert (settings.openai_chat_api_base, settings.openai_chat_api_key) == (
        "https://api.openai.com/v1",
        "private-process-key",
    )


def test_generic_key_is_not_forwarded_to_uncredentialed_file_proxy(env_file, monkeypatch):
    env_file.write_text("OPENAI_CHAT_API_BASE=https://proxy.example/v1\n")
    monkeypatch.setenv("OPENAI_API_KEY", "private-process-key")
    with pytest.raises(ValueError, match="custom endpoint"):
        LLMConfig()


def test_save_preserves_group_mode_and_plain_values(env_file):
    env_file.write_text("LANGUAGE=EN\n")
    env_file.chmod(0o640)
    settings = LLMConfig()
    settings.window_size = 7
    settings.update_env()
    assert env_file.stat().st_mode & 0o777 == 0o640
    assert "WINDOW_SIZE=7\n" in env_file.read_text()


def test_new_config_file_is_private(env_file):
    settings = LLMConfig()
    settings.window_size = 7
    settings.update_env()
    assert env_file.stat().st_mode & 0o777 == 0o600


def test_thin_write_flag_uses_file_and_process_precedence(env_file, monkeypatch):
    from hugegraph_llm.api import thin_api

    env_file.write_text("HUGEGRAPH_LLM_ENABLE_THIN_WRITES=true\n")
    monkeypatch.setattr(thin_api.admin_settings, "enable_login", "true")
    monkeypatch.delenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", raising=False)
    assert thin_api._thin_write_disabled() is None
    monkeypatch.setenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", "false")
    assert thin_api._thin_write_disabled() is not None


def test_missing_readonly_prompt_uses_memory_without_creating_files(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from hugegraph_llm.config.models import base_prompt_config
    from hugegraph_llm.config.prompt_config import PromptConfig

    path = tmp_path / 'read-only' / 'config_prompt.yaml'
    monkeypatch.setattr(base_prompt_config, "yaml_file_path", str(path))
    settings = PromptConfig(SimpleNamespace(language="EN"))
    settings.ensure_yaml_file_exists()
    assert settings.answer_prompt == settings.answer_prompt_EN
    assert not path.parent.exists()


@pytest.mark.parametrize("provider", ["openai", "litellm"])
def test_chat_cascade_uses_effective_role_configuration(env_file, monkeypatch, provider):
    from hugegraph_llm.demo.rag_demo import configs_block

    field = f"{provider}_extract_api_key"
    monkeypatch.setenv(field.upper(), "managed-extraction-key")
    settings = LLMConfig(extract_llm_type=provider)
    monkeypatch.setattr(configs_block, "llm_settings", settings)
    assert configs_block._role_has_credentials("extract")
    assert not env_file.exists()


@pytest.mark.parametrize(
    ("field", "label", "render_name", "configured", "requested"),
    [
        ("chat_llm_type", "type", "chat_llm_settings", "openai", "ollama/local"),
        ("extract_llm_type", "type", "extract_llm_settings", "openai", "ollama/local"),
        ("text2gql_llm_type", "type", "text2gql_llm_settings", "openai", "ollama/local"),
        ("embedding_type", "Embedding", "embedding_settings", "openai", "ollama/local"),
        ("reranker_type", "Reranker", "reranker_settings", "cohere", "siliconflow"),
    ],
)
def test_managed_dropdown_cannot_poison_later_saves(
    env_file, monkeypatch, field, label, render_name, configured, requested
):
    from fastapi.testclient import TestClient

    from hugegraph_llm.demo.rag_demo import app, configs_block

    monkeypatch.setenv(field.upper(), configured)
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "false")
    settings = LLMConfig()
    monkeypatch.setattr(configs_block, "llm_settings", settings)
    ui = app.init_rag_ui()
    selectors = [component for component in ui.blocks.values() if getattr(component, "label", None) == label]
    assert any(selector.interactive is False for selector in selectors)
    render = next(
        function
        for function in ui.fns.values()
        if getattr(getattr(getattr(function.fn, "__self__", None), "fn", None), "__name__", None) == render_name
    )
    monkeypatch.setattr(app, "init_rag_ui", lambda: ui)
    client = TestClient(app.create_app())
    try:
        response = client.post(
            f"/gradio_api/run/{render.api_name}", json={"data": [requested], "session_hash": "managed-selector"}
        )
        assert response.status_code == 200, response.text
        assert getattr(settings, field) == configured
        settings.window_size = 13
        settings.update_env()
        assert dotenv_values(env_file) == {"WINDOW_SIZE": "13"}
    finally:
        client.close()


def test_endpoint_switch_does_not_reuse_password_from_old_file(env_file, monkeypatch):
    env_file.write_text("GRAPH_URL=http://old.example:8080\nGRAPH_PWD=old-private-password\n")
    monkeypatch.setenv("GRAPH_URL", "http://external.example:8080")
    settings = HugeGraphConfig()
    assert settings.graph_pwd == ""
    assert settings.environment_source("graph_pwd") is None
    monkeypatch.setenv("GRAPH_URL", "http://old.example:8080/")
    assert HugeGraphConfig().graph_pwd == "old-private-password"


def test_unchanged_managed_bare_graph_url_allows_other_ui_changes(env_file, monkeypatch):
    from hugegraph_llm.demo.rag_demo import configs_block

    monkeypatch.setenv("GRAPH_URL", "graph-server:8080")
    settings = HugeGraphConfig()
    assert settings.graph_url == "http://graph-server:8080"
    monkeypatch.setattr(configs_block, "huge_settings", settings)
    monkeypatch.setattr(configs_block, "test_api_connection", lambda *args, **kwargs: 200)
    monkeypatch.setattr(configs_block.gr, "Info", lambda *args: None)
    assert (
        configs_block.apply_graph_config(
            settings.graph_url, "new-graph", settings.graph_user, settings.graph_pwd, settings.graph_space
        )
        == 200
    )
    assert dotenv_values(env_file) == {"GRAPH_NAME": "new-graph"}


def test_runtime_operators_read_bundled_assets_and_write_index_to_data_root(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock

    from hugegraph_llm.config.paths import PACKAGED_RESOURCES
    from hugegraph_llm.indices.vector_index import faiss_vector_store
    from hugegraph_llm.operators.index_op import gremlin_example_index_query
    from hugegraph_llm.operators.llm_op import prompt_generate

    root = tmp_path / 'fresh-data'
    monkeypatch.setattr(prompt_generate, "resource_path", str(root))
    examples = json.loads((PACKAGED_RESOURCES / 'prompt_examples' / 'prompt_examples.json').read_text())
    assert prompt_generate.PromptGenerate(Mock())._load_few_shot_example(examples[0]['name']) == examples[0]
    monkeypatch.setattr(gremlin_example_index_query, "resource_path", str(root))
    monkeypatch.setattr(faiss_vector_store, "resource_path", str(root))
    embedding = SimpleNamespace(
        get_embedding_dim=lambda: 2, get_texts_embeddings=lambda texts: [[float(i), 1.0] for i, _ in enumerate(texts)]
    )
    query = gremlin_example_index_query.GremlinExampleIndexQuery(
        faiss_vector_store.FaissVectorIndex, embedding=embedding
    )
    assert query.vector_index.index.ntotal > 0
    assert (root / 'gremlin_examples' / 'index.faiss').is_file()
    assert not (root / 'demo' / 'text2gremlin.csv').exists()


@pytest.mark.parametrize("role", ["chat", "extract", "text2gql"])
@pytest.mark.parametrize("provider", ["ollama/local", "litellm"])
@pytest.mark.parametrize("source", ["file", "process", "constructor"])
def test_inactive_openai_role_does_not_require_proxy_credentials(env_file, monkeypatch, role, provider, source):
    config = f"OPENAI_{role.upper()}_API_BASE=https://proxy.example/v1\n"
    if source == "file":
        config += f"{role.upper()}_LLM_TYPE={provider}\n"
    env_file.write_text(config)
    monkeypatch.setenv("OPENAI_API_KEY", "private-process-key")
    if source == "process":
        monkeypatch.setenv(f"{role.upper()}_LLM_TYPE", provider)
    data = {f"{role}_llm_type": provider} if source == "constructor" else {}
    settings = LLMConfig(**data)
    assert getattr(settings, f"{role}_llm_type") == provider
    assert getattr(settings, f"openai_{role}_api_key") is None
    assert settings.environment_source(f"openai_{role}_api_key") is None
    # The active roles still receive their own safe default-origin key.
    other_role = "extract" if role == "chat" else "chat"
    assert getattr(settings, f"openai_{other_role}_api_key") == "private-process-key"
    assert env_file.read_text() == config


@pytest.mark.parametrize("role", ["chat", "extract", "text2gql"])
@pytest.mark.parametrize("key_name", ["OPENAI_API_KEY", "role-specific"])
def test_managed_key_blocks_endpoint_change_before_probe_and_remains_reloadable(env_file, monkeypatch, role, key_name):
    from unittest.mock import Mock

    from hugegraph_llm.demo.rag_demo import configs_block

    source = f"OPENAI_{role.upper()}_API_KEY" if key_name == "role-specific" else key_name
    monkeypatch.setenv(source, "private-managed-key")
    settings = LLMConfig()
    monkeypatch.setattr(configs_block, "llm_settings", settings)
    probe = Mock(return_value=200)
    monkeypatch.setattr(configs_block, "test_api_connection", probe)
    before = settings.model_dump()
    assert settings.environment_source(f"openai_{role}_api_base") == source
    with pytest.raises(ValueError, match="managed by environment"):
        configs_block.apply_llm_config(role, "private-managed-key", "https://untrusted.example/v1", "model", 100)
    probe.assert_not_called()
    assert settings.model_dump() == before
    assert not env_file.exists()
    assert LLMConfig().model_dump() == before
    # Direct persistence must enforce the same endpoint boundary.
    setattr(settings, f"openai_{role}_api_base", "https://untrusted.example/v1")
    with pytest.raises(ValueError, match="managed by environment"):
        settings.update_env()
    assert not env_file.exists()


@pytest.mark.parametrize("provider", ["openai", "litellm"])
def test_managed_embedding_key_also_owns_endpoint_before_probe(env_file, monkeypatch, provider):
    from unittest.mock import Mock

    from hugegraph_llm.demo.rag_demo import configs_block

    monkeypatch.setenv(f"{provider.upper()}_EMBEDDING_API_KEY", "private-managed-key")
    settings = LLMConfig(embedding_type=provider)
    monkeypatch.setattr(configs_block, "llm_settings", settings)
    probe = Mock(return_value=200)
    monkeypatch.setattr(configs_block, "test_api_connection", probe)
    monkeypatch.setattr(configs_block, "test_litellm_embedding", probe)
    before = settings.model_dump()
    with pytest.raises(ValueError, match="managed by environment"):
        configs_block.apply_embedding_config("private-managed-key", "https://untrusted.example/v1", "model")
    probe.assert_not_called()
    assert settings.model_dump() == before
    assert not env_file.exists()
