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

"""Unit tests for :mod:`property_graph_extract_enhanced.evaluator`.

These tests treat the evaluator as strategy-agnostic: they feed pre-built
predicted and expected graphs and verify F1 / property-fidelity math. The
benchmark that actually drives baseline vs. enhanced pipelines lives in
``test_property_graph_benchmark.py``.
"""

from __future__ import annotations

import pytest

from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced import (
    GraphExtractionEvaluator,
    GraphSchemaIndex,
)

pytestmark = pytest.mark.contract


def _schema() -> dict:
    return {
        "propertykeys": [
            {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
            {"name": "age", "data_type": "INT", "cardinality": "SINGLE"},
            {"name": "title", "data_type": "TEXT", "cardinality": "SINGLE"},
            {"name": "year", "data_type": "INT", "cardinality": "SINGLE"},
            {"name": "role", "data_type": "TEXT", "cardinality": "SINGLE"},
        ],
        "vertexlabels": [
            {
                "id": 1,
                "name": "Person",
                "id_strategy": "PRIMARY_KEY",
                "primary_keys": ["name"],
                "properties": ["name", "age"],
                "nullable_keys": ["age"],
            },
            {
                "id": 2,
                "name": "Movie",
                "id_strategy": "PRIMARY_KEY",
                "primary_keys": ["title"],
                "properties": ["title", "year"],
                "nullable_keys": ["year"],
            },
        ],
        "edgelabels": [
            {
                "name": "ACTED_IN",
                "source_label": "Person",
                "target_label": "Movie",
                "properties": ["role"],
            },
        ],
    }


@pytest.fixture()
def evaluator() -> GraphExtractionEvaluator:
    return GraphExtractionEvaluator(GraphSchemaIndex(_schema()))


def _vertex(label: str, vid: str, **props):
    return {"label": label, "type": "vertex", "id": vid, "properties": props}


def _edge(label: str, out_v: str, in_v: str, out_label: str, in_label: str, **props):
    return {
        "label": label,
        "type": "edge",
        "outV": out_v,
        "inV": in_v,
        "outVLabel": out_label,
        "inVLabel": in_label,
        "properties": props,
    }


# -------------------------------------------------------------- structural F1


def test_perfect_prediction_yields_f1_one(evaluator):
    predicted = {
        "vertices": [_vertex("Person", "1:Tom", name="Tom"), _vertex("Movie", "2:X", title="X")],
        "edges": [_edge("ACTED_IN", "1:Tom", "2:X", "Person", "Movie")],
    }
    expected = predicted
    report = evaluator.evaluate(predicted, expected)
    assert report.vertex_metrics.f1 == 1.0
    assert report.edge_metrics.f1 == 1.0
    assert report.overall_f1 == 1.0
    assert report.overall_precision == 1.0
    assert report.overall_recall == 1.0


def test_both_empty_treated_as_perfect_match(evaluator):
    report = evaluator.evaluate({"vertices": [], "edges": []}, {"vertices": [], "edges": []})
    assert report.vertex_metrics.f1 == 1.0
    assert report.edge_metrics.f1 == 1.0
    assert report.overall_f1 == 1.0
    assert report.property_metrics.property_valid_ratio == 1.0
    assert report.property_metrics.property_exact_match_rate == 1.0


def test_missing_predictions_have_zero_recall(evaluator):
    predicted = {"vertices": [], "edges": []}
    expected = {
        "vertices": [_vertex("Person", "1:Tom", name="Tom")],
        "edges": [],
    }
    report = evaluator.evaluate(predicted, expected)
    assert report.vertex_metrics.precision == 1.0
    assert report.vertex_metrics.recall == 0.0
    assert report.vertex_metrics.f1 == 0.0
    assert report.overall_f1 == 0.0


def test_hallucinated_predictions_have_zero_precision(evaluator):
    predicted = {
        "vertices": [_vertex("Person", "1:Ghost", name="Ghost")],
        "edges": [],
    }
    expected = {"vertices": [], "edges": []}
    report = evaluator.evaluate(predicted, expected)
    assert report.vertex_metrics.precision == 0.0
    assert report.vertex_metrics.recall == 1.0
    assert report.vertex_metrics.f1 == 0.0
    assert report.overall_f1 == 0.0


def test_half_recall_reflected_in_f1(evaluator):
    predicted = {"vertices": [_vertex("Person", "1:Tom", name="Tom")], "edges": []}
    expected = {
        "vertices": [
            _vertex("Person", "1:Tom", name="Tom"),
            _vertex("Person", "1:Meg", name="Meg"),
        ],
        "edges": [],
    }
    report = evaluator.evaluate(predicted, expected)
    assert report.vertex_metrics.precision == 1.0
    assert report.vertex_metrics.recall == 0.5
    assert report.vertex_metrics.f1 == pytest.approx(2 / 3)


def test_duplicate_predictions_deduped_for_f1_but_raw_count_preserved(evaluator):
    dup = _vertex("Person", "1:Tom", name="Tom")
    predicted = {"vertices": [dup, dict(dup)], "edges": []}
    expected = {"vertices": [_vertex("Person", "1:Tom", name="Tom")], "edges": []}
    report = evaluator.evaluate(predicted, expected)
    assert report.vertex_metrics.predicted_count_raw == 2
    assert report.vertex_metrics.predicted_count_unique == 1
    assert report.vertex_metrics.f1 == 1.0


def test_edges_matched_by_label_and_endpoints(evaluator):
    predicted = {
        "vertices": [],
        "edges": [_edge("ACTED_IN", "1:Tom", "2:X", "Person", "Movie", role="Star")],
    }
    expected = {
        "vertices": [],
        "edges": [_edge("ACTED_IN", "1:Tom", "2:Y", "Person", "Movie", role="Star")],
    }
    report = evaluator.evaluate(predicted, expected)
    assert report.edge_metrics.f1 == 0.0


# ------------------------------------------------------------ property metrics


def test_property_valid_ratio_excludes_extra_property(evaluator):
    predicted = {
        "vertices": [_vertex("Person", "1:Tom", name="Tom", email="tom@example.com")],
        "edges": [],
    }
    expected = {"vertices": [_vertex("Person", "1:Tom", name="Tom")], "edges": []}
    report = evaluator.evaluate(predicted, expected)
    # 2 predicted properties (name, email); 1 valid (name).
    assert report.property_metrics.predicted_property_count == 2
    assert report.property_metrics.valid_property_count == 1
    assert report.property_metrics.property_valid_ratio == 0.5


def test_property_exact_match_penalizes_type_mismatch(evaluator):
    # Same vertex matches structurally; property comparison is type-strict.
    predicted = {
        "vertices": [_vertex("Person", "1:Tom", name="Tom", age="62")],
        "edges": [],
    }
    expected = {
        "vertices": [_vertex("Person", "1:Tom", name="Tom", age=62)],
        "edges": [],
    }
    report = evaluator.evaluate(predicted, expected)
    # 1 TP vertex, 2 predicted props (name, age), 2 expected props;
    # only name (Tom == Tom) exact matches.
    assert report.property_metrics.expected_tp_property_count == 2
    assert report.property_metrics.predicted_tp_property_count == 2
    assert report.property_metrics.exact_match_property_count == 1
    assert report.property_metrics.property_exact_match_rate == 0.5


def test_property_exact_match_all_when_types_match(evaluator):
    predicted = {
        "vertices": [_vertex("Person", "1:Tom", name="Tom", age=62)],
        "edges": [],
    }
    expected = predicted
    report = evaluator.evaluate(predicted, expected)
    assert report.property_metrics.property_exact_match_rate == 1.0
    assert report.property_metrics.property_valid_ratio == 1.0


# -------------------------------------------------------------- key extraction


def test_vertex_without_id_falls_back_to_canonical(evaluator):
    predicted = {
        "vertices": [
            # No id field; canonical id should be reconstructed from PK.
            {"label": "Person", "type": "vertex", "properties": {"name": "Tom"}}
        ],
        "edges": [],
    }
    expected = {"vertices": [_vertex("Person", "1:Tom", name="Tom")], "edges": []}
    report = evaluator.evaluate(predicted, expected)
    assert report.vertex_metrics.true_positive_count == 1
    assert report.vertex_metrics.f1 == 1.0


def test_vertex_without_id_or_pk_is_skipped(evaluator):
    predicted = {
        "vertices": [
            # No id, no name → canonical id cannot be computed → excluded.
            {"label": "Person", "type": "vertex", "properties": {"age": 62}}
        ],
        "edges": [],
    }
    expected = {"vertices": [], "edges": []}
    report = evaluator.evaluate(predicted, expected)
    assert report.vertex_metrics.predicted_count_raw == 0


def test_edge_without_endpoints_is_skipped(evaluator):
    predicted = {
        "vertices": [],
        "edges": [
            # Missing outV → not a valid comparable item.
            {"label": "ACTED_IN", "type": "edge", "inV": "2:X", "properties": {}}
        ],
    }
    expected = {"vertices": [], "edges": []}
    report = evaluator.evaluate(predicted, expected)
    assert report.edge_metrics.predicted_count_raw == 0


def test_evaluation_report_to_dict_is_serializable(evaluator):
    report = evaluator.evaluate(
        {"vertices": [_vertex("Person", "1:Tom", name="Tom")], "edges": []},
        {"vertices": [_vertex("Person", "1:Tom", name="Tom")], "edges": []},
    )
    payload = report.to_dict()
    # to_dict is nested-serializable; check a handful of leaves rather than
    # locking every key name (avoids brittle golden output).
    assert payload["overall_f1"] == 1.0
    assert payload["vertex_metrics"]["true_positive_count"] == 1
    assert "property_valid_ratio" in payload["property_metrics"]


# ---------------------------------------------------------- overall precision


def test_overall_precision_and_recall_combine_vertices_and_edges(evaluator):
    predicted = {
        "vertices": [_vertex("Person", "1:Tom", name="Tom"), _vertex("Movie", "2:X", title="X")],
        "edges": [
            _edge("ACTED_IN", "1:Tom", "2:X", "Person", "Movie"),
            _edge("ACTED_IN", "1:Tom", "2:Ghost", "Person", "Movie"),
        ],
    }
    expected = {
        "vertices": [_vertex("Person", "1:Tom", name="Tom"), _vertex("Movie", "2:X", title="X")],
        "edges": [_edge("ACTED_IN", "1:Tom", "2:X", "Person", "Movie")],
    }
    report = evaluator.evaluate(predicted, expected)
    # 2 TP vertices + 1 TP edge = 3 TP out of (2+2)=4 predicted, (2+1)=3 expected
    assert report.overall_precision == pytest.approx(0.75)
    assert report.overall_recall == 1.0
    assert report.overall_f1 == pytest.approx(6 / 7)
