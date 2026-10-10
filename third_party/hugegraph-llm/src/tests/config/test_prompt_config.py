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
from unittest.mock import MagicMock

import pytest

from hugegraph_llm.config.prompt_config import PromptConfig
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.operators.llm_op.property_graph_extract import PropertyGraphExtract

pytestmark = pytest.mark.contract

# FIXME: add contract coverage for runtime-loaded config_prompt.yaml, not only
# PromptConfig class constants and prompt_examples.json fixtures.
# FIXME: verify omitted API prompt fields resolve the current PromptConfig
# object instead of import-time default prompt strings.


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


def test_extract_graph_prompt_en_example_matches_parser_contract():
    _assert_prompt_example_contract(PromptConfig.extract_graph_prompt_EN, "## Example")


def test_extract_graph_prompt_cn_example_matches_parser_contract():
    _assert_prompt_example_contract(PromptConfig.extract_graph_prompt_CN, "## 示例")


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
