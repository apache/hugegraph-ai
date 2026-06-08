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


import unittest
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

# FIXME: add config tests proving .env sync preserves typed numeric/boolean
# fields and that imports do not create or mutate files implicitly.


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

    def test_demo_config_block_uses_shared_env_path(self):
        from hugegraph_llm.config.models import base_config
        from hugegraph_llm.demo.rag_demo import configs_block

        self.assertEqual(configs_block.env_path, base_config.env_path)
