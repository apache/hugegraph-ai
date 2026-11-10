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


import subprocess
import sys
import unittest
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


class TestConfig(unittest.TestCase):
    def test_config(self):
        import nltk

        from hugegraph_llm.config import resource_path

        nltk.data.path.append(resource_path)
        nltk.data.find("corpora/stopwords")

    def test_prompt_yaml_path_is_project_root_independent(self):
        from hugegraph_llm.config.models import base_prompt_config

        expected = Path(__file__).resolve().parents[2] / "hugegraph_llm" / "resources" / "demo" / "config_prompt.yaml"
        self.assertEqual(Path(base_prompt_config.yaml_file_path), expected)

    def test_prompt_yaml_path_prefers_explicit_override(self):
        from hugegraph_llm.config.models import base_prompt_config

        custom_prompt = Path("/tmp/hugegraph-llm-prompt-test.yaml")
        with patch.dict(environ, {base_prompt_config.PROMPT_CONFIG_PATH_ENV_VAR: str(custom_prompt)}):
            self.assertEqual(Path(base_prompt_config.resolve_prompt_yaml_path()), custom_prompt)

    def test_prompt_yaml_path_uses_user_config_outside_source_tree(self):
        from hugegraph_llm.config.models import base_prompt_config

        with TemporaryDirectory() as config_home:
            with patch.dict(environ, {"XDG_CONFIG_HOME": config_home}, clear=False):
                with patch.object(base_prompt_config, "_source_prompt_yaml_path", return_value=None):
                    expected = Path(config_home) / "hugegraph-llm" / "config_prompt.yaml"
                    self.assertEqual(Path(base_prompt_config.resolve_prompt_yaml_path()), expected)

    def test_prompt_save_creates_mutable_config_parent_directory(self):
        from hugegraph_llm.config.models import base_prompt_config
        from hugegraph_llm.config.prompt_config import PromptConfig

        with TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "nested" / "config_prompt.yaml"
            prompt = PromptConfig(SimpleNamespace(language="en"))

            with patch.object(base_prompt_config, "yaml_file_path", str(prompt_path)):
                prompt.save_to_yaml()

            self.assertTrue(prompt_path.exists())

    def test_env_path_is_project_root_independent(self):
        from hugegraph_llm.config.models import base_config

        expected = Path(__file__).resolve().parents[3] / ".env"
        self.assertEqual(Path(base_config.env_path), expected)

    def test_env_path_prefers_explicit_override(self):
        from hugegraph_llm.config.models import base_config

        custom_env = Path("/tmp/hugegraph-llm-test.env")
        with patch.dict(environ, {base_config.ENV_PATH_ENV_VAR: str(custom_env)}):
            self.assertEqual(Path(base_config.resolve_env_path()), custom_env)


_ENV_SCRUB_PREFIXES = (
    "OPENAI_",
    "OLLAMA_",
    "CHAT_",
    "EXTRACT_",
    "TEXT2GQL_",
    "EMBEDDING_",
    "RERANKER_",
    "COHERE_",
    "CO_API_",
    "HUGEGRAPH_LLM_",
)


def _owned_env_names() -> set[str]:
    """Every environment name a config field can source from (field names and aliases).

    Hand-maintained prefixes drift when new fields land (e.g. ``HYBRID_LLM_WEIGHTS``);
    deriving the names from the config models keeps the scrub hermetic.
    """
    import hugegraph_llm.config  # noqa: F401  ensure all BaseConfig subclasses are loaded
    from hugegraph_llm.config.models.base_config import BaseConfig

    names: set[str] = set()
    stack: list[type[BaseConfig]] = [BaseConfig]
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        for field in cls.model_fields:
            names.update(name.upper() for name in cls._source_names(field))
    return names


def _is_scrubbed_env_name(name: str) -> bool:
    upper = name.upper()
    return upper.startswith(_ENV_SCRUB_PREFIXES) or upper in _owned_env_names()


def _scrub_config_env(monkeypatch):
    for name in list(environ):
        if _is_scrubbed_env_name(name):
            monkeypatch.delenv(name)


def _config_import_env(home: Path) -> dict:
    env = dict(environ)
    for name in list(env):
        if _is_scrubbed_env_name(name):
            env.pop(name)
    env["HUGEGRAPH_LLM_ENV_PATH"] = str(home / ".env")
    env["HUGEGRAPH_LLM_SETTINGS_PATH"] = str(home / "settings.yaml")
    env["HUGEGRAPH_LLM_PROMPT_CONFIG_PATH"] = str(home / "config_prompt.yaml")
    return env


def _run_config_import(tmp_path: Path, home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", "import hugegraph_llm.config"],
        env=_config_import_env(home),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_env_export_round_trip_preserves_typed_fields(tmp_path, monkeypatch):
    from hugegraph_llm.config.llm_config import LLMConfig
    from hugegraph_llm.config.models import base_config

    _scrub_config_env(monkeypatch)
    monkeypatch.setattr(base_config, "env_path", str(tmp_path / ".env"))

    settings = LLMConfig()
    settings.ollama_chat_port = 12345
    settings.openai_chat_tokens = 4096
    settings.extract_use_chat = False
    settings.hybrid_llm_weights = 0.0
    settings.generate_env()

    # Assert the exported lines themselves: reloaded falsy values alone do not prove
    # they were written, because LLMConfig derives extract_use_chat from the other
    # extract fields when the variable is absent.
    exported_lines = (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
    assert "OLLAMA_CHAT_PORT='12345'" in exported_lines
    assert "OPENAI_CHAT_TOKENS='4096'" in exported_lines
    assert "EXTRACT_USE_CHAT='False'" in exported_lines
    assert "HYBRID_LLM_WEIGHTS='0.0'" in exported_lines

    reloaded = LLMConfig()
    assert reloaded.ollama_chat_port == 12345
    assert isinstance(reloaded.ollama_chat_port, int)
    assert reloaded.openai_chat_tokens == 4096
    assert isinstance(reloaded.openai_chat_tokens, int)
    assert reloaded.extract_use_chat is False
    assert reloaded.hybrid_llm_weights == 0.0
    assert isinstance(reloaded.hybrid_llm_weights, float)


def test_scrub_config_env_clears_field_aliases(monkeypatch):
    """Ambient variables named after config fields must not leak into the settings."""
    monkeypatch.setenv("HYBRID_LLM_WEIGHTS", "0.5")
    monkeypatch.setenv("UNRELATED_TEST_VAR", "keep")

    _scrub_config_env(monkeypatch)

    assert "HYBRID_LLM_WEIGHTS" not in environ
    assert environ.get("UNRELATED_TEST_VAR") == "keep"


def test_config_import_creates_no_config_files(tmp_path):
    home = tmp_path / "config-home"
    home.mkdir()

    result = _run_config_import(tmp_path, home)

    assert result.returncode == 0, result.stderr
    assert list(home.iterdir()) == []


def test_config_import_does_not_mutate_existing_config_files(tmp_path):
    home = tmp_path / "config-home"
    home.mkdir()
    (home / ".env").write_text("OPENAI_CHAT_LANGUAGE_MODEL='custom-model'\n", encoding="utf-8")
    (home / "settings.yaml").write_text("llm:\n  options:\n    window_size: 7\n", encoding="utf-8")
    (home / "config_prompt.yaml").write_text("_language_generated: en\n", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in home.iterdir()}

    result = _run_config_import(tmp_path, home)

    assert result.returncode == 0, result.stderr
    after = {path.name: path.read_bytes() for path in home.iterdir()}
    assert after == before
