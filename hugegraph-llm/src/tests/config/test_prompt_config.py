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

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from hugegraph_llm.config.prompt_config import PromptConfig
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.operators.llm_op.property_graph_extract import PropertyGraphExtract

pytestmark = pytest.mark.contract


def _json_objects_after_marker(prompt, marker):
    start = prompt.index(marker) + len(marker)
    decoder = json.JSONDecoder()
    objects = []
    index = start
    while True:
        index = prompt.find("{", index)
        if index == -1:
            return objects
        try:
            value, end = decoder.raw_decode(prompt[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        objects.append(value)
        index += end


def _example_schema_and_output(prompt, example_marker):
    objects = _json_objects_after_marker(prompt, example_marker)
    schema = next(obj for obj in objects if "vertexlabels" in obj and "edgelabels" in obj)
    output = next(obj for obj in objects if "vertices" in obj and "edges" in obj)
    return schema, output


def _assert_prompt_example_contract(prompt, example_marker):
    schema, output = _example_schema_and_output(prompt, example_marker)
    _assert_output_matches_schema_contract(schema, output)


def _assert_output_matches_schema_contract(schema, output):
    assert set(output) == {"vertices", "edges"}
    assert output["vertices"]
    assert output["edges"]

    vertex_ids = {vertex["id"] for vertex in output["vertices"]}
    vertex_labels = {vertex["label"] for vertex in output["vertices"]}
    schema_vertices = {vertex["name"]: vertex for vertex in schema["vertexlabels"]}
    schema_edges = {edge["name"]: edge for edge in schema["edgelabels"]}

    for vertex in output["vertices"]:
        assert set(vertex) == {"id", "label", "properties"}
        schema_vertex = schema_vertices[vertex["label"]]
        primary_values = [str(vertex["properties"][key]) for key in schema_vertex["primary_keys"]]
        expected_id = f"{schema_vertex['id']}:{'!'.join(primary_values)}"
        assert vertex["id"] == expected_id
        assert not vertex["id"].startswith(f"{vertex['label']}:")
        assert isinstance(vertex["properties"], dict)

    for edge in output["edges"]:
        assert set(edge) == {"label", "outV", "outVLabel", "inV", "inVLabel", "properties"}
        assert edge["label"] in schema_edges
        assert edge["outV"] in vertex_ids
        assert edge["inV"] in vertex_ids
        assert edge["outVLabel"] in vertex_labels
        assert edge["inVLabel"] in vertex_labels
        assert edge["outVLabel"] == schema_edges[edge["label"]]["source_label"]
        assert edge["inVLabel"] == schema_edges[edge["label"]]["target_label"]
        assert isinstance(edge["properties"], dict)

    extractor = PropertyGraphExtract(llm=MagicMock(spec=BaseLLM))
    parsed_items = extractor._extract_and_filter_label(schema, json.dumps(output))
    assert {item["type"] for item in parsed_items} == {"vertex", "edge"}
    assert len(parsed_items) == len(output["vertices"]) + len(output["edges"])


def _prompt_api_client():
    from unittest.mock import Mock

    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    from hugegraph_llm.api.rag_api import rag_http_api

    callbacks = {
        "rag_answer_func": Mock(return_value=("raw", "vector", "graph", "graph_vector")),
        "graph_rag_recall_func": Mock(return_value={"query": "q", "keywords": []}),
        "apply_graph_conf": Mock(return_value=200),
        "apply_llm_conf": Mock(return_value=200),
        "apply_embedding_conf": Mock(return_value=200),
        "apply_reranker_conf": Mock(return_value=200),
        "gremlin_generate_selective_func": Mock(return_value={"gremlin": "g.V()"}),
    }
    router = APIRouter()
    rag_http_api(router, **callbacks)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), callbacks


def test_extract_graph_prompt_en_example_matches_parser_contract():
    _assert_prompt_example_contract(PromptConfig.extract_graph_prompt_EN, "## Example")


def test_extract_graph_prompt_cn_example_matches_parser_contract():
    _assert_prompt_example_contract(PromptConfig.extract_graph_prompt_CN, "## 示例")


def test_omitted_api_prompt_fields_resolve_current_prompt_config(monkeypatch):
    from hugegraph_llm.config import prompt

    monkeypatch.setattr(prompt, "answer_prompt", "live-answer-prompt")
    monkeypatch.setattr(prompt, "keywords_extract_prompt", "live-keywords-prompt")
    monkeypatch.setattr(prompt, "gremlin_generate_prompt", "live-gremlin-prompt")

    client, callbacks = _prompt_api_client()
    response = client.post("/rag", json={"query": "q"})
    assert response.status_code == 200
    kwargs = callbacks["rag_answer_func"].call_args.kwargs
    assert kwargs["answer_prompt"] == "live-answer-prompt"
    assert kwargs["keywords_extract_prompt"] == "live-keywords-prompt"
    assert kwargs["gremlin_prompt"] == "live-gremlin-prompt"


def test_omitted_graph_rag_prompt_resolves_current_prompt_config(monkeypatch):
    from hugegraph_llm.config import prompt

    monkeypatch.setattr(prompt, "gremlin_generate_prompt", "live-gremlin-prompt")

    client, callbacks = _prompt_api_client()
    response = client.post("/rag/graph", json={"query": "q"})
    assert response.status_code == 200
    assert callbacks["graph_rag_recall_func"].call_args.kwargs["gremlin_prompt"] == "live-gremlin-prompt"


def test_omitted_text2gremlin_prompt_resolves_current_prompt_config(monkeypatch):
    from hugegraph_llm.config import prompt

    monkeypatch.setattr(prompt, "gremlin_generate_prompt", "live-gremlin-prompt")

    client, callbacks = _prompt_api_client()
    response = client.post("/text2gremlin", json={"query": "q"})
    assert response.status_code == 200
    kwargs = callbacks["gremlin_generate_selective_func"].call_args.kwargs
    assert kwargs["gremlin_prompt_input"] == "live-gremlin-prompt"


def test_keyword_extract_template_resolves_current_prompt_config(monkeypatch):
    from hugegraph_llm.config import prompt
    from hugegraph_llm.operators.llm_op.keyword_extract import KeywordExtract

    monkeypatch.setattr(prompt, "keywords_extract_prompt", "live-keywords-prompt")

    extractor = KeywordExtract(text="q")
    assert extractor._extract_template == "live-keywords-prompt"


@pytest.mark.parametrize("language", ["en", "cn"])
def test_snapshot_default_prompts_use_conditional_default_id_strategy(language, monkeypatch):
    from hugegraph_llm.extraction_runtime import property_graph as app_runtime

    config = PromptConfig(SimpleNamespace(language=language))
    config._set_language_defaults()
    monkeypatch.setattr(app_runtime, "prompt", config)

    prompts = app_runtime.snapshot_graph_prompts()
    if language == "en":
        assert "DEFAULT or an undeclared ID strategy when primary_keys is non-empty" in prompts.extract
        assert "without primary_keys uses AUTOMATIC" in prompts.extract
        assert "temporary IDs for edge references" in prompts.extract
    else:
        assert "primary_keys 非空的 DEFAULT 与未声明 ID 策略" in prompts.extract
        assert "primary_keys 为空时使用 AUTOMATIC" in prompts.extract
        assert "边引用应使用一致的临时 ID" in prompts.extract

    for instruction in (prompts.review, prompts.repair):
        assert "DEFAULT or an undeclared ID strategy when primary_keys is non-empty" in instruction
        assert "without primary_keys uses AUTOMATIC" in instruction
        assert "temporary IDs for edge references" in instruction


def test_review_and_repair_prompts_survive_yaml_save_and_load(tmp_path, monkeypatch):
    from hugegraph_llm.config.models import base_prompt_config

    path = tmp_path / "prompts.yaml"
    monkeypatch.setattr(base_prompt_config, "yaml_file_path", str(path))
    config = PromptConfig(SimpleNamespace(language="en"))
    config.extract_graph_prompt = "Existing extraction override"
    config.review_graph_prompt = "Review override\nwith a second line"
    config.repair_graph_prompt = "Repair override"
    config.save_to_yaml()
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["review_graph_prompt"] == config.review_graph_prompt
    assert saved["repair_graph_prompt"] == config.repair_graph_prompt
    loaded = PromptConfig(SimpleNamespace(language="en"))
    loaded.ensure_yaml_file_exists()
    assert loaded.review_graph_prompt == config.review_graph_prompt
    assert loaded.repair_graph_prompt == config.repair_graph_prompt
    assert loaded.extract_graph_prompt == "Existing extraction override"


def test_existing_yaml_uses_default_review_and_repair_prompts(tmp_path, monkeypatch):
    from hugegraph_llm.config.models import base_prompt_config

    path = tmp_path / "prompts.yaml"
    path.write_text("extract_graph_prompt: custom\n_language_generated: en\n", encoding="utf-8")
    monkeypatch.setattr(base_prompt_config, "yaml_file_path", str(path))
    config = PromptConfig(SimpleNamespace(language="en"))
    config.ensure_yaml_file_exists()
    assert config.extract_graph_prompt == "custom"
    assert config.review_graph_prompt == PromptConfig.review_graph_prompt
    assert config.repair_graph_prompt == PromptConfig.repair_graph_prompt


@pytest.mark.parametrize(("language", "example_marker"), [("en", "## Example"), ("cn", "## 示例")])
def test_runtime_loaded_yaml_extract_prompt_matches_parser_contract(language, example_marker, tmp_path, monkeypatch):
    from hugegraph_llm.config.models import base_prompt_config

    path = tmp_path / "config_prompt.yaml"
    monkeypatch.setattr(base_prompt_config, "yaml_file_path", str(path))
    writer = PromptConfig(SimpleNamespace(language=language))
    writer._set_language_defaults()
    writer.save_to_yaml()

    loaded = PromptConfig(SimpleNamespace(language=language))
    loaded.ensure_yaml_file_exists()

    class_constant = getattr(PromptConfig, f"extract_graph_prompt_{language.upper()}")
    assert loaded.extract_graph_prompt == class_constant
    _assert_prompt_example_contract(loaded.extract_graph_prompt, example_marker)


def test_extract_graph_prompt_example_contract_rejects_label_name_vertex_id():
    schema, output = _example_schema_and_output(PromptConfig.extract_graph_prompt_EN, "## Example")
    output["vertices"][0]["id"] = "person:Sarah"

    try:
        _assert_output_matches_schema_contract(schema, output)
    except AssertionError:
        return

    raise AssertionError("Prompt example contract accepted a label-name vertex id")


def test_extract_graph_prompt_example_contract_rejects_dangling_edge_reference():
    schema, output = _example_schema_and_output(PromptConfig.extract_graph_prompt_EN, "## Example")
    output["edges"][0]["outV"] = "1:Missing"

    try:
        _assert_output_matches_schema_contract(schema, output)
    except AssertionError:
        return

    raise AssertionError("Prompt example contract accepted an edge reference outside vertices")


def test_prompt_examples_match_extraction_contract():
    examples_path = (
        Path(__file__).parents[2] / "hugegraph_llm" / "resources" / "prompt_examples" / "prompt_examples.json"
    )
    examples = json.loads(examples_path.read_text(encoding="utf-8"))

    for example in examples:
        prompt = example["prompt"]
        assert '"type":"vertex"' not in prompt
        assert '"type":"edge"' not in prompt
        _assert_prompt_example_contract(prompt, "## Example")


def test_prompt_examples_use_matching_domain_examples():
    examples_path = (
        Path(__file__).parents[2] / "hugegraph_llm" / "resources" / "prompt_examples" / "prompt_examples.json"
    )
    examples = json.loads(examples_path.read_text(encoding="utf-8"))
    domain_markers = {
        "Official Person-Relationship Extraction": ["Sarah", "James"],
        "Traffic Accident Element Extraction": ["John Smith", "NY-88888"],
        "Financial Event Extraction": ["Company A", "$2 billion"],
        "Medical Diagnosis Extraction": ["Li Hua", "Gankang"],
    }

    for example in examples:
        prompt = example["prompt"]
        for marker in domain_markers[example["name"]]:
            assert marker in prompt
