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
        '["Find all persons", "Find all webpages"]',
        encoding="utf-8",
    )
    (prompt_examples_dir / "schema_examples.json").write_text(
        '{"vertexlabels": [], "edgelabels": []}',
        encoding="utf-8",
    )


def test_query_examples_normalize_bundled_string_list_to_downstream_shape():
    normalized = vector_graph_block._normalize_schema_generator_query_examples('["Find all persons"]')

    assert json.loads(normalized) == [
        {
            "description": "Find all persons",
            "gremlin": "",
        }
    ]


def test_query_examples_accept_description_gremlin_object_shape():
    normalized = vector_graph_block._normalize_schema_generator_query_examples(
        json.dumps(
            [
                {
                    "description": "Find persons",
                    "gremlin": 'g.V().hasLabel("person")',
                }
            ]
        )
    )

    assert json.loads(normalized) == [
        {
            "description": "Find persons",
            "gremlin": 'g.V().hasLabel("person")',
        }
    ]


def test_query_examples_reject_invalid_shape():
    with pytest.raises(gr.Error, match="description"):
        vector_graph_block._normalize_schema_generator_query_examples('[{"query": "Find persons"}]')


def test_few_shot_examples_must_be_json_object():
    with pytest.raises(gr.Error, match="JSON object"):
        vector_graph_block._validate_schema_generator_few_shot_examples('[{"schema": {"vertices": []}}]')


def test_schema_generator_persist_helper_saves_valid_examples(monkeypatch, tmp_path):
    _write_bundled_examples(tmp_path)
    dummy_prompt = DummyPrompt()
    monkeypatch.setattr(vector_graph_block, "prompt", dummy_prompt)
    monkeypatch.setattr(vector_graph_block, "resource_path", str(tmp_path))

    query_examples = '["who knows marko?"]'
    few_shot_examples = '{"vertexlabels": [], "edgelabels": []}'

    effective_query, effective_few_shot = vector_graph_block._persist_schema_generator_examples(
        query_examples,
        few_shot_examples,
    )

    assert json.loads(effective_query) == [
        {
            "description": "who knows marko?",
            "gremlin": "",
        }
    ]
    assert json.loads(effective_few_shot) == {
        "vertexlabels": [],
        "edgelabels": [],
    }
    assert dummy_prompt.schema_generator_query_examples == effective_query
    assert dummy_prompt.schema_generator_few_shot_examples == effective_few_shot
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
            "{}",
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
    dummy_prompt.schema_generator_query_examples = '[{"description": "saved query", "gremlin": ""}]'
    dummy_prompt.schema_generator_few_shot_examples = '{"vertexlabels": [{"name": "saved"}], "edgelabels": []}'
    monkeypatch.setattr(vector_graph_block, "prompt", dummy_prompt)
    monkeypatch.setattr(vector_graph_block, "resource_path", str(tmp_path))

    effective_query, effective_few_shot = vector_graph_block._persist_schema_generator_examples(
        "   ",
        "",
    )

    assert dummy_prompt.schema_generator_query_examples == ""
    assert dummy_prompt.schema_generator_few_shot_examples == ""
    assert json.loads(effective_query) == [
        {
            "description": "Find all persons",
            "gremlin": "",
        },
        {
            "description": "Find all webpages",
            "gremlin": "",
        },
    ]
    assert json.loads(effective_few_shot) == {
        "vertexlabels": [],
        "edgelabels": [],
    }
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

    result = vector_graph_block._build_schema_and_provide_feedback(
        "source text",
        '["who knows lop?"]',
        '{"vertexlabels": [], "edgelabels": []}',
    )

    assert result == "{}"
    assert calls
    _, query_payload, few_shot_payload = calls[0]
    assert json.loads(query_payload) == [
        {
            "description": "who knows lop?",
            "gremlin": "",
        }
    ]
    assert json.loads(few_shot_payload) == {
        "vertexlabels": [],
        "edgelabels": [],
    }


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
    dummy_prompt.schema_generator_query_examples = '[{"description": "saved query", "gremlin": ""}]'
    dummy_prompt.schema_generator_few_shot_examples = '{"vertexlabels": [], "edgelabels": []}'
    monkeypatch.setattr(vector_graph_block, "prompt", dummy_prompt)

    query_examples = json.loads(vector_graph_block.load_query_examples())
    few_shot_examples = json.loads(vector_graph_block.load_schema_fewshot_examples())

    assert query_examples == [
        {
            "description": "saved query",
            "gremlin": "",
        }
    ]
    assert few_shot_examples == {
        "vertexlabels": [],
        "edgelabels": [],
    }


def test_load_examples_falls_back_to_bundled_resources(monkeypatch, tmp_path):
    _write_bundled_examples(tmp_path)
    dummy_prompt = DummyPrompt()
    monkeypatch.setattr(vector_graph_block, "prompt", dummy_prompt)
    monkeypatch.setattr(vector_graph_block, "resource_path", str(tmp_path))

    query_examples = json.loads(vector_graph_block.load_query_examples())
    few_shot_examples = json.loads(vector_graph_block.load_schema_fewshot_examples())

    assert query_examples == [
        {
            "description": "Find all persons",
            "gremlin": "",
        },
        {
            "description": "Find all webpages",
            "gremlin": "",
        },
    ]
    assert few_shot_examples == {
        "vertexlabels": [],
        "edgelabels": [],
    }


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

    assert query_examples == [
        {
            "description": "Find all persons",
            "gremlin": "",
        },
        {
            "description": "Find all webpages",
            "gremlin": "",
        },
    ]
    assert few_shot_examples == {
        "vertexlabels": [],
        "edgelabels": [],
    }


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
