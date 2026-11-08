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

"""Regressions for required values and complete-graph endpoint validation."""

import pytest
from fakes import NOW
from support import graph_candidate, graph_input, make_store

from hugegraph_llm_eval.api import evaluate
from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationRecord, EvaluationRecordStatus
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.schema_validity import (
    SchemaValidityEvaluator,
)
from hugegraph_llm_eval.integrations.graph_extraction.materializers import GraphArtifactMaterializer


def _record(candidate: dict[str, object]) -> EvaluationRecord:
    store = make_store()
    evaluator = SchemaValidityEvaluator(GraphArtifactMaterializer(store), clock=lambda: NOW)
    result = evaluate([evaluator], graph_input(store, candidate_payload=candidate))
    record = result.records[0]
    assert record.status is EvaluationRecordStatus.COMPLETED
    return record


@pytest.mark.parametrize("properties", ({}, {"name": None}, {"name": ""}, {"name": " \t "}))
def test_required_properties_reject_absent_null_and_blank_values(properties) -> None:
    candidate = graph_candidate()
    candidate["vertices"][0]["properties"] = properties

    record = _record(candidate)

    assert {item.name: item.value for item in record.measurements}["required_property_fill"] == 0.5
    assert {item.name: item.value for item in record.measurements}["schema_validity"] == 0.0
    assert [item.code for item in record.findings] == ["schema.missing_required_property"]
    assert record.findings[0].evidence[0].locator == "vertices[0]"


@pytest.mark.parametrize("value", (0, False))
def test_required_properties_accept_nonempty_falsy_values(value) -> None:
    candidate = graph_candidate()
    candidate["vertices"][0]["properties"]["name"] = value

    record = _record(candidate)

    assert {item.name: item.value for item in record.measurements}["schema_validity"] == 1.0
    assert {item.name: item.value for item in record.measurements}["required_property_fill"] == 1.0
    assert record.findings == ()


@pytest.mark.parametrize(("vertex_index", "actual_label"), ((0, "Skill"), (1, "Person")))
def test_edge_labels_cannot_override_actual_endpoint_types(vertex_index, actual_label) -> None:
    candidate = graph_candidate()
    vertex = candidate["vertices"][vertex_index]
    vertex["label"] = actual_label
    vertex["properties"] = {"name": vertex["name"]}

    record = _record(candidate)

    assert {item.name: item.value for item in record.measurements}["illegal_edge_rate"] == 1.0
    assert [item.code for item in record.findings] == ["schema.illegal_edge"]
    assert record.findings[0].evidence[0].locator == "edges[0]"


@pytest.mark.parametrize("endpoint", ("outV", "inV"))
def test_complete_graph_rejects_missing_endpoints_even_with_explicit_labels(endpoint) -> None:
    candidate = graph_candidate()
    candidate["edges"][0][endpoint] = "nonexistent vertex"

    record = _record(candidate)

    assert {item.name: item.value for item in record.measurements}["illegal_edge_rate"] == 1.0
    assert [item.code for item in record.findings] == ["schema.illegal_edge"]


@pytest.mark.parametrize("reverse_vertices", (False, True))
@pytest.mark.parametrize("explicit_label", (False, True))
def test_same_name_different_types_require_explicit_disambiguation(explicit_label, reverse_vertices) -> None:
    candidate = graph_candidate()
    candidate["vertices"].append({"label": "Person", "name": "GraphQL", "properties": {"name": "GraphQL"}})
    if reverse_vertices:
        candidate["vertices"].reverse()
    if not explicit_label:
        candidate["edges"][0].pop("inVLabel")

    record = _record(candidate)

    measurements = {item.name: item.value for item in record.measurements}
    assert measurements["schema_validity"] == float(explicit_label)
    assert measurements["illegal_edge_rate"] == float(not explicit_label)
    assert [item.code for item in record.findings] == ([] if explicit_label else ["schema.illegal_edge"])


def test_unique_endpoint_types_can_be_inferred_without_labels() -> None:
    candidate = graph_candidate()
    candidate["edges"][0].pop("outVLabel")
    candidate["edges"][0].pop("inVLabel")

    record = _record(candidate)

    assert {item.name: item.value for item in record.measurements}["schema_validity"] == 1.0
    assert record.findings == ()
