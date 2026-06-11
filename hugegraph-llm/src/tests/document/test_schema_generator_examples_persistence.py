# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import inspect
import json
from types import SimpleNamespace

import gradio as gr
import pytest

from hugegraph_llm.config.models import base_prompt_config
from hugegraph_llm.config.models.base_prompt_config import BasePromptConfig
from hugegraph_llm.demo.rag_demo import vector_graph_block


class DummyPrompt:
    def __init__(self):
        self.doc_input_text = ""
        self.graph_schema = ""
        self.extract_graph_prompt = ""
        self.graph_extract_split_type = "document"
        self.schema_generator_query_examples = ""
        self.schema_generator_few_shot_examples = ""
        self.llm_settings = SimpleNamespace(language="EN")
        self.update_count = 0

    def update_yaml_file(self):
        self.update_count += 1


def _write_bundled_examples(tmp_path):
    prompt_examples_dir = tmp_path / "prompt_examples"
    prompt_examples_dir.mkdir()
    (prompt_examples_dir / "query_examples.json").write_text(
        '[{"bundled_query": true}]',
        encoding="utf-8",
    )
    (prompt_examples_dir / "schema_examples.json").write_text(
        '[{"bundled_schema": true}]',
        encoding="utf-8",
    )


def test_schema_generator_persist_helper_saves_valid_examples(monkeypatch, tmp_path):
    _write_bundled_examples(tmp_path)
    dummy_prompt = DummyPrompt()
    monkeypatch.setattr(vector_graph_block, "prompt", dummy_prompt)
    monkeypatch.setattr(vector_graph_block, "resource_path", str(tmp_path))

    query_examples = '[{"query": "who knows marko?"}]'
    few_shot_examples = '[{"schema": {"vertices": []}}]'

    effective_query, effective_few_shot = vector_graph_block._persist_schema_generator_examples(
        query_examples,
        few_shot_examples,
    )

    assert effective_query == query_examples
    assert effective_few_shot == few_shot_examples
    assert dummy_prompt.schema_generator_query_examples == query_examples
    assert dummy_prompt.schema_generator_few_shot_examples == few_shot_examples
    assert dummy_prompt.update_count == 1


def test_schema_generator_persist_helper_rejects_invalid_query_examples(
    monkeypatch,
    tmp_path,
):
    _write_bundled_examples(tmp_path)
    dummy_prompt = DummyPrompt()
    monkeypatch.setattr(vector_graph_block, "prompt", dummy_prompt)
    monkeypatch.setattr(vector_graph_block, "resource_path", str(tmp_path))

    with pytest.raises(gr.Error, match="Query examples must be valid JSON"):
        vector_graph_block._persist_schema_generator_examples(
            "{invalid json",
            "[]",
        )

    assert dummy_prompt.schema_generator_query_examples == ""
    assert dummy_prompt.schema_generator_few_shot_examples == ""
    assert dummy_prompt.update_count == 0


def test_blank_schema_generator_examples_clear_persisted_overrides_to_bundled(
    monkeypatch,
    tmp_path,
):
    _write_bundled_examples(tmp_path)
    dummy_prompt = DummyPrompt()
    dummy_prompt.schema_generator_query_examples = '[{"saved_query": true}]'
    dummy_prompt.schema_generator_few_shot_examples = '[{"saved_schema": true}]'
    monkeypatch.setattr(vector_graph_block, "prompt", dummy_prompt)
    monkeypatch.setattr(vector_graph_block, "resource_path", str(tmp_path))

    effective_query, effective_few_shot = vector_graph_block._persist_schema_generator_examples(
        "   ",
        "",
    )

    assert dummy_prompt.schema_generator_query_examples == ""
    assert dummy_prompt.schema_generator_few_shot_examples == ""
    assert json.loads(effective_query) == [{"bundled_query": True}]
    assert json.loads(effective_few_shot) == [{"bundled_schema": True}]
    assert dummy_prompt.update_count == 1


def test_build_schema_feedback_persists_examples_before_running_flow(
    monkeypatch,
    tmp_path,
):
    _write_bundled_examples(tmp_path)
    dummy_prompt = DummyPrompt()
    monkeypatch.setattr(vector_graph_block, "prompt", dummy_prompt)
    monkeypatch.setattr(vector_graph_block, "resource_path", str(tmp_path))

    calls = []

    def fake_build_schema(input_text, query_examples, few_shot_schema):
        calls.append((input_text, query_examples, few_shot_schema))
        return "{}"

    monkeypatch.setattr(vector_graph_block, "build_schema", fake_build_schema)

    query_examples = '[{"query": "who knows lop?"}]'
    few_shot_examples = '[{"schema": {"edges": []}}]'

    result = vector_graph_block._build_schema_and_provide_feedback(
        "source text",
        query_examples,
        few_shot_examples,
    )

    assert result == "{}"
    assert dummy_prompt.schema_generator_query_examples == query_examples
    assert dummy_prompt.schema_generator_few_shot_examples == few_shot_examples
    assert calls == [("source text", query_examples, few_shot_examples)]


def test_build_schema_feedback_rejects_invalid_few_shot_before_flow(
    monkeypatch,
    tmp_path,
):
    _write_bundled_examples(tmp_path)
    dummy_prompt = DummyPrompt()
    monkeypatch.setattr(vector_graph_block, "prompt", dummy_prompt)
    monkeypatch.setattr(vector_graph_block, "resource_path", str(tmp_path))

    called = False

    def fake_build_schema(*args):
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr(vector_graph_block, "build_schema", fake_build_schema)

    with pytest.raises(gr.Error, match="Few-shot schema examples must be valid JSON"):
        vector_graph_block._build_schema_and_provide_feedback(
            "source text",
            "[]",
            "{invalid json",
        )

    assert called is False
    assert dummy_prompt.update_count == 0


def test_load_examples_prefers_persisted_prompt_values(monkeypatch):
    dummy_prompt = DummyPrompt()
    dummy_prompt.schema_generator_query_examples = '[{"saved_query": true}]'
    dummy_prompt.schema_generator_few_shot_examples = '[{"saved_schema": true}]'
    monkeypatch.setattr(vector_graph_block, "prompt", dummy_prompt)

    query_examples = json.loads(vector_graph_block.load_query_examples())
    few_shot_examples = json.loads(vector_graph_block.load_schema_fewshot_examples())

    assert query_examples == [{"saved_query": True}]
    assert few_shot_examples == [{"saved_schema": True}]


def test_load_examples_falls_back_to_bundled_resources(monkeypatch, tmp_path):
    _write_bundled_examples(tmp_path)
    dummy_prompt = DummyPrompt()
    monkeypatch.setattr(vector_graph_block, "prompt", dummy_prompt)
    monkeypatch.setattr(vector_graph_block, "resource_path", str(tmp_path))

    query_examples = json.loads(vector_graph_block.load_query_examples())
    few_shot_examples = json.loads(vector_graph_block.load_schema_fewshot_examples())

    assert query_examples == [{"bundled_query": True}]
    assert few_shot_examples == [{"bundled_schema": True}]


def test_invalid_persisted_examples_fall_back_to_bundled_resources(
    monkeypatch,
    tmp_path,
):
    _write_bundled_examples(tmp_path)
    dummy_prompt = DummyPrompt()
    dummy_prompt.schema_generator_query_examples = "{invalid json"
    dummy_prompt.schema_generator_few_shot_examples = "{invalid json"
    monkeypatch.setattr(vector_graph_block, "prompt", dummy_prompt)
    monkeypatch.setattr(vector_graph_block, "resource_path", str(tmp_path))

    query_examples = json.loads(vector_graph_block.load_query_examples())
    few_shot_examples = json.loads(vector_graph_block.load_schema_fewshot_examples())

    assert query_examples == [{"bundled_query": True}]
    assert few_shot_examples == [{"bundled_schema": True}]


def test_generic_store_prompt_does_not_handle_schema_generator_examples():
    parameters = inspect.signature(vector_graph_block.store_prompt).parameters

    assert "query_examples" not in parameters
    assert "few_shot_examples" not in parameters


def test_old_prompt_config_without_schema_generator_examples_still_loads(
    monkeypatch,
    tmp_path,
):
    prompt_path = tmp_path / "config_prompt.yaml"
    prompt_path.write_text(
        "doc_input_text: old doc\ngraph_schema: '{}'\nextract_graph_prompt: old prompt\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(base_prompt_config, "yaml_file_path", str(prompt_path))

    config = BasePromptConfig()
    config.llm_settings = SimpleNamespace(language="EN")
    config.ensure_yaml_file_exists()

    assert config.schema_generator_query_examples == ""
    assert config.schema_generator_few_shot_examples == ""
