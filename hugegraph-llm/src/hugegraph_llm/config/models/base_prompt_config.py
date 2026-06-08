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

import os
from pathlib import Path

import yaml

from hugegraph_llm.utils.log import log

dir_name = os.path.dirname
F_NAME = "config_prompt.yaml"
PROMPT_CONFIG_PATH_ENV_VAR = "HUGEGRAPH_LLM_PROMPT_CONFIG_PATH"


def _source_prompt_yaml_path() -> Path | None:
    package_root = Path(__file__).resolve().parents[2]
    if package_root.parent.name != "src":
        return None
    project_root = package_root.parent.parent
    if (project_root / "pyproject.toml").exists():
        return package_root / "resources" / "demo" / F_NAME
    return None


def _user_prompt_yaml_path() -> Path:
    config_home = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser()
    return config_home / "hugegraph-llm" / F_NAME


def resolve_prompt_yaml_path() -> str:
    explicit_prompt_path = os.getenv(PROMPT_CONFIG_PATH_ENV_VAR)
    if explicit_prompt_path:
        return str(Path(explicit_prompt_path).expanduser())

    source_prompt_path = _source_prompt_yaml_path()
    if source_prompt_path is not None:
        return str(source_prompt_path)

    return str(_user_prompt_yaml_path())


yaml_file_path = resolve_prompt_yaml_path()


class LiteralStr(str):
    pass


def literal_str_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(LiteralStr, literal_str_representer)


class BasePromptConfig:
    graph_schema: str = ""
    extract_graph_prompt: str = ""
    default_question: str = ""
    custom_rerank_info: str = ""
    answer_prompt: str = ""
    keywords_extract_prompt: str = ""
    text2gql_graph_schema: str = ""
    gremlin_generate_prompt: str = ""
    doc_input_text: str = ""
    graph_extract_split_type: str = "document"
    _language_generated: str = ""
    generate_extract_prompt_template: str = ""

    def ensure_yaml_file_exists(self):
        if os.path.exists(yaml_file_path):
            log.info("Loading prompt file '%s' successfully.", F_NAME)
            with open(yaml_file_path, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
                # Load existing values from the YAML file into the class attributes
                for key, value in data.items():
                    setattr(self, key, value)

            # Check if the language in the .env file matches the language in the YAML file
            env_lang = (
                self.llm_settings.language.lower()
                if hasattr(self, "llm_settings") and self.llm_settings.language
                else "en"
            )
            yaml_lang = data.get("_language_generated", "en").lower()
            if env_lang.strip() != yaml_lang.strip():
                log.warning(
                    "Prompt was changed '.env' language is '%s', "
                    "but '%s' was generated for '%s'. "
                    "Regenerating the prompt file...",
                    env_lang,
                    F_NAME,
                    yaml_lang,
                )
                if self.llm_settings.language.lower() == "cn":
                    self.answer_prompt = self.answer_prompt_CN
                    self.extract_graph_prompt = self.extract_graph_prompt_CN
                    self.gremlin_generate_prompt = self.gremlin_generate_prompt_CN
                    self.keywords_extract_prompt = self.keywords_extract_prompt_CN
                    self.doc_input_text = self.doc_input_text_CN
                else:
                    self.answer_prompt = self.answer_prompt_EN
                    self.extract_graph_prompt = self.extract_graph_prompt_EN
                    self.gremlin_generate_prompt = self.gremlin_generate_prompt_EN
                    self.keywords_extract_prompt = self.keywords_extract_prompt_EN
                    self.doc_input_text = self.doc_input_text_EN
        else:
            self.generate_yaml_file()
            log.info("Prompt file '%s' doesn't exist, create it.", yaml_file_path)

    def save_to_yaml(self):
        def to_literal(val):
            return LiteralStr(val) if isinstance(val, str) else val

        data = {
            "graph_schema": to_literal(self.graph_schema),
            "text2gql_graph_schema": to_literal(self.text2gql_graph_schema),
            "extract_graph_prompt": to_literal(self.extract_graph_prompt),
            "default_question": to_literal(self.default_question),
            "custom_rerank_info": to_literal(self.custom_rerank_info),
            "answer_prompt": to_literal(self.answer_prompt),
            "keywords_extract_prompt": to_literal(self.keywords_extract_prompt),
            "gremlin_generate_prompt": to_literal(self.gremlin_generate_prompt),
            "doc_input_text": to_literal(self.doc_input_text),
            "graph_extract_split_type": to_literal(self.graph_extract_split_type),
            "_language_generated": str(self.llm_settings.language).lower().strip(),
            "generate_extract_prompt_template": to_literal(self.generate_extract_prompt_template),
        }
        Path(yaml_file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(yaml_file_path, "w", encoding="utf-8") as file:
            yaml.dump(data, file, allow_unicode=True, sort_keys=False, default_flow_style=False)

    def generate_yaml_file(self):
        if os.path.exists(yaml_file_path):
            log.info(
                "%s already exists, do you want to override with the default configuration? (y/n)",
                yaml_file_path,
            )
            update = input()
            if update.lower() != "y":
                return

        if self.llm_settings.language.lower() == "cn":
            self.answer_prompt = self.answer_prompt_CN
            self.extract_graph_prompt = self.extract_graph_prompt_CN
            self.gremlin_generate_prompt = self.gremlin_generate_prompt_CN
            self.keywords_extract_prompt = self.keywords_extract_prompt_CN
            self.doc_input_text = self.doc_input_text_CN
        else:
            self.answer_prompt = self.answer_prompt_EN
            self.extract_graph_prompt = self.extract_graph_prompt_EN
            self.gremlin_generate_prompt = self.gremlin_generate_prompt_EN
            self.keywords_extract_prompt = self.keywords_extract_prompt_EN
            self.doc_input_text = self.doc_input_text_EN
        self.save_to_yaml()
        log.info("Prompt file '%s' has been generated with default values.", yaml_file_path)

    def update_yaml_file(self):
        self.save_to_yaml()
        log.info("Prompt file '%s' updated successfully.", F_NAME)
