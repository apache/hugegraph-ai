# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json

import pytest

from hugegraph_llm_sdk.extraction_runtime.property_graph import PropertyGraphBundle, _primary_keys
from hugegraph_llm_sdk.extraction_runtime.review import ChunkInput, ExtractionOptions, run_chunk
from hugegraph_llm_sdk.graph_utils import primary_key_id
from hugegraph_llm_sdk.prompts import DEFAULT_EXTRACT_PROMPT_CN, GraphPrompts
from hugegraph_llm_sdk.schema import validate_schema


@pytest.mark.parametrize("strategy", [None, "DEFAULT", "PRIMARY_KEY"])
def test_primary_key_strategy_generates_identity(strategy):
    label = {"id": 1, "id_strategy": strategy, "primary_keys": ["name"]}
    assert primary_key_id(label, {"name": "alice"}) == "1:alice"
    assert primary_key_id(label, {}) is None
    assert _primary_keys(label) == ["name"]


def test_automatic_strategy_does_not_generate_primary_identity():
    label = {"id": 1, "id_strategy": "AUTOMATIC", "primary_keys": ["name"]}
    assert primary_key_id(label, {"name": "alice"}) is None
    assert _primary_keys(label) == []


@pytest.mark.parametrize("strategy", [None, "DEFAULT", "PRIMARY_KEY"])
def test_primary_key_must_not_be_nullable(strategy):
    schema = {
        "vertexlabels": [
            {
                "id": 1,
                "name": "person",
                "properties": ["name"],
                "id_strategy": strategy,
                "primary_keys": ["name"],
                "nullable_keys": ["name"],
            }
        ],
        "edgelabels": [],
        "propertykeys": [{"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"}],
    }
    issues = validate_schema(schema)
    assert any("cannot be nullable" in issue.message for issue in issues)


@pytest.mark.parametrize("chinese", [False, True])
def test_default_strategy_rules_reach_all_prompt_stages(chinese):
    schema = {
        "vertexlabels": [
            {
                "id": 1,
                "name": "person",
                "id_strategy": "DEFAULT",
                "primary_keys": ["name"],
                "properties": ["name"],
                "nullable_keys": [],
            },
            {
                "id": 2,
                "name": "company",
                "id_strategy": "DEFAULT",
                "primary_keys": [],
                "properties": ["name"],
                "nullable_keys": [],
            },
        ],
        "edgelabels": [{"name": "works_for", "source_label": "person", "target_label": "company", "properties": []}],
        "propertykeys": [{"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"}],
    }
    graph = {
        "vertices": [
            {"id": "person-ref", "label": "person", "properties": {"name": "Alice"}},
            {"id": "company-ref", "label": "company", "properties": {"name": "Acme"}},
        ],
        "edges": [
            {
                "label": "works_for",
                "outV": "person-ref",
                "outVLabel": "person",
                "inV": "company-ref",
                "inVLabel": "company",
                "properties": {},
            }
        ],
    }

    class ScriptedModel:
        def __init__(self):
            self.requests = []
            self.responses = iter(
                (
                    graph,
                    {"decision": "fix", "issues": [{"path": "graph", "message": "Review"}]},
                    graph,
                    {"decision": "pass", "issues": []},
                )
            )

        def generate(self, *, prompt):
            self.requests.append(prompt)
            return json.dumps(next(self.responses))

    model = ScriptedModel()
    prompts = GraphPrompts(extract=DEFAULT_EXTRACT_PROMPT_CN) if chinese else GraphPrompts()
    domain = PropertyGraphBundle(llm=model, schema=schema, prompts=prompts)
    result = run_chunk(bundle=domain, chunk=ChunkInput(0, "Alice works for Acme"), options=ExtractionOptions())

    assert result.status == "final"
    assert result.graph["vertices"][0]["id"] == "1:Alice"
    assert result.graph["vertices"][1]["id"] == "company-ref"
    assert result.graph["edges"][0]["outV"] == "1:Alice"
    assert result.graph["edges"][0]["inV"] == "company-ref"
    assert len(model.requests) == 4

    if chinese:
        assert "DEFAULT 或未声明 ID 策略且 primary_keys 非空" in model.requests[0]
        assert "primary_keys 为空时使用 AUTOMATIC" in model.requests[0]
    else:
        assert "DEFAULT or an undeclared ID strategy when primary_keys is non-empty" in model.requests[0]
        assert "without primary_keys is AUTOMATIC" in model.requests[0]
    for request in model.requests[1:]:
        assert "DEFAULT or an undeclared ID strategy when primary_keys is non-empty" in request
        assert "without primary_keys is AUTOMATIC" in request
