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

import pytest

from tests.fixtures.fake_llm import FakeLLM

pytestmark = [pytest.mark.smoke, pytest.mark.integration]


PROPERTY_GRAPH_SCHEMA = {
    "vertexlabels": [
        {
            "id": 1,
            "name": "person",
            "properties": ["name", "occupation"],
            "primary_keys": ["name"],
            "nullable_keys": ["occupation"],
        },
        {
            "id": 2,
            "name": "company",
            "properties": ["name", "industry"],
            "primary_keys": ["name"],
            "nullable_keys": ["industry"],
        },
    ],
    "edgelabels": [
        {
            "name": "works_for",
            "source_label": "person",
            "target_label": "company",
            "properties": ["since"],
        }
    ],
}


def test_graph_extract_flow_builds_production_property_graph_pipeline():
    from hugegraph_llm.flows.graph_extract import GraphExtractFlow

    pipeline = GraphExtractFlow().build_flow(
        schema=PROPERTY_GRAPH_SCHEMA,
        texts=["Marko works for HugeGraph."],
        example_prompt="extract property graph",
        extract_type="property_graph",
        language="en",
    )
    prepared = pipeline.getGParamWithNoEmpty("wkflow_input")
    dot = pipeline.dump()

    assert prepared.extract_type == "property_graph"
    assert prepared.texts == ["Marko works for HugeGraph."]
    assert 'label="schema_node"' in dot
    assert 'label="chunk_split"' in dot
    assert 'label="graph_extract"' in dot


def test_property_graph_extract_uses_production_operator_with_deterministic_llm():
    from hugegraph_llm.operators.llm_op.property_graph_extract import PropertyGraphExtract

    llm = FakeLLM(
        [
            """{
                "vertices": [
                    {"label": "person", "properties": {"name": "Marko", "occupation": "developer"}},
                    {"label": "company", "properties": {"name": "HugeGraph", "industry": "graph"}}
                ],
                "edges": [
                    {
                        "label": "works_for",
                        "properties": {"since": "2024"},
                        "source": {"label": "person", "properties": {"name": "Marko"}},
                        "target": {"label": "company", "properties": {"name": "HugeGraph"}}
                    }
                ]
            }"""
        ]
    )
    context = PropertyGraphExtract(llm=llm, example_prompt=None).run(
        {
            "schema": PROPERTY_GRAPH_SCHEMA,
            "chunks": ["Marko works for HugeGraph."],
        }
    )

    assert [vertex["label"] for vertex in context["vertices"]] == ["person", "company"]
    assert context["edges"][0]["label"] == "works_for"
    assert context["edges"][0]["outV"] == "1:Marko"
    assert context["edges"][0]["inV"] == "2:HugeGraph"
