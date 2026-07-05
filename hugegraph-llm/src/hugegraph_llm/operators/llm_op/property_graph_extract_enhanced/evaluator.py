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

"""Offline evaluator for schema-aware graph extraction.

Given a schema plus a predicted graph and a ground-truth graph, the evaluator
computes:

* Vertex / edge / overall precision, recall, F1 (set-based; matched by
  ``(label, id)`` for vertices and ``(label, outV, inV)`` for edges).
* Property fidelity: ``property_valid_ratio`` over all predicted properties
  (schema-allowed keys / total predicted keys) and ``property_exact_match_rate``
  over true-positive-item properties (matched (key, value) / total expected
  (key, value) on TP items).

The evaluator is strategy-agnostic: it accepts any extractor result whose shape
is ``{"vertices": [...], "edges": [...]}``. It powers the offline benchmark
that quantifies the enhanced strategy's quality gains over baseline.

Edge cases:

* Both sides empty → every ratio is 1.0 (nothing to find, nothing predicted).
* Predicted empty, expected non-empty → precision=1.0, recall=0.0, F1=0.0.
* Predicted non-empty, expected empty → precision=0.0, recall=1.0, F1=0.0.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.schema_index import (
    GraphSchemaIndex,
)


@dataclass(frozen=True)
class ItemMetrics:
    """Precision/recall/F1 for one item type (vertex or edge)."""

    predicted_count_raw: int
    predicted_count_unique: int
    expected_count: int
    true_positive_count: int
    precision: float
    recall: float
    f1: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "predicted_count_raw": self.predicted_count_raw,
            "predicted_count_unique": self.predicted_count_unique,
            "expected_count": self.expected_count,
            "true_positive_count": self.true_positive_count,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


@dataclass(frozen=True)
class PropertyMetrics:
    """Property fidelity aggregated across all predicted items."""

    predicted_property_count: int
    valid_property_count: int
    property_valid_ratio: float
    expected_tp_property_count: int
    predicted_tp_property_count: int
    exact_match_property_count: int
    property_exact_match_rate: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "predicted_property_count": self.predicted_property_count,
            "valid_property_count": self.valid_property_count,
            "property_valid_ratio": self.property_valid_ratio,
            "expected_tp_property_count": self.expected_tp_property_count,
            "predicted_tp_property_count": self.predicted_tp_property_count,
            "exact_match_property_count": self.exact_match_property_count,
            "property_exact_match_rate": self.property_exact_match_rate,
        }


@dataclass(frozen=True)
class EvaluationReport:
    """Aggregate evaluation of one predicted graph against ground truth."""

    vertex_metrics: ItemMetrics
    edge_metrics: ItemMetrics
    property_metrics: PropertyMetrics
    overall_precision: float
    overall_recall: float
    overall_f1: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vertex_metrics": self.vertex_metrics.to_dict(),
            "edge_metrics": self.edge_metrics.to_dict(),
            "property_metrics": self.property_metrics.to_dict(),
            "overall_precision": self.overall_precision,
            "overall_recall": self.overall_recall,
            "overall_f1": self.overall_f1,
        }


def _safe_ratio(numerator: int, denominator: int) -> float:
    """Empty-graph safe ratio: 0/0 → 1.0, else numerator/denominator."""
    if denominator == 0:
        return 1.0 if numerator == 0 else 0.0
    return numerator / denominator


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


KeyFn = Callable[[Mapping[str, Any]], Optional[Tuple[Any, ...]]]


class GraphExtractionEvaluator:
    """Compare a predicted graph against a ground-truth graph under a schema.

    ``schema_index`` is used only to classify which predicted property keys are
    schema-allowed and to reconstruct canonical vertex ids when the predicted
    item omits ``id`` (rare, but happens when an extractor emits a legal vertex
    without an id field). Structural matching itself is schema-agnostic.
    """

    def __init__(self, schema_index: GraphSchemaIndex) -> None:
        self._schema_index = schema_index

    def evaluate(
        self,
        predicted: Mapping[str, Sequence[Mapping[str, Any]]],
        expected: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> EvaluationReport:
        vertex_metrics, vertex_tp_pairs = self._score_items(
            list(predicted.get("vertices", [])),
            list(expected.get("vertices", [])),
            key_fn=self._vertex_key,
        )
        edge_metrics, edge_tp_pairs = self._score_items(
            list(predicted.get("edges", [])),
            list(expected.get("edges", [])),
            key_fn=self._edge_key,
        )
        property_metrics = self._score_properties(
            all_predicted=list(predicted.get("vertices", [])) + list(predicted.get("edges", [])),
            tp_pairs=vertex_tp_pairs + edge_tp_pairs,
        )
        overall_precision = _safe_ratio(
            vertex_metrics.true_positive_count + edge_metrics.true_positive_count,
            vertex_metrics.predicted_count_unique + edge_metrics.predicted_count_unique,
        )
        overall_recall = _safe_ratio(
            vertex_metrics.true_positive_count + edge_metrics.true_positive_count,
            vertex_metrics.expected_count + edge_metrics.expected_count,
        )
        overall_f1 = _f1(overall_precision, overall_recall)
        return EvaluationReport(
            vertex_metrics=vertex_metrics,
            edge_metrics=edge_metrics,
            property_metrics=property_metrics,
            overall_precision=overall_precision,
            overall_recall=overall_recall,
            overall_f1=overall_f1,
        )

    # -------------------------------------------------------------- match keys
    def _vertex_key(self, vertex: Mapping[str, Any]) -> Optional[Tuple[str, str]]:
        label = vertex.get("label")
        if not label:
            return None
        raw_id = vertex.get("id")
        if raw_id:
            return (str(label), str(raw_id))
        canonical = self._schema_index.canonical_vertex_id(str(label), dict(vertex.get("properties", {}) or {}))
        if canonical is None:
            return None
        return (str(label), canonical)

    def _edge_key(self, edge: Mapping[str, Any]) -> Optional[Tuple[str, str, str]]:
        label = edge.get("label")
        out_v = edge.get("outV")
        in_v = edge.get("inV")
        if not label or not out_v or not in_v:
            return None
        return (str(label), str(out_v), str(in_v))

    # ------------------------------------------------------------ score helpers
    def _score_items(
        self,
        predicted: Sequence[Mapping[str, Any]],
        expected: Sequence[Mapping[str, Any]],
        key_fn: KeyFn,
    ) -> Tuple[ItemMetrics, List[Tuple[Mapping[str, Any], Mapping[str, Any]]]]:
        pred_raw_keys: List[Tuple[Any, ...]] = []
        pred_by_key: Dict[Tuple[Any, ...], Mapping[str, Any]] = {}
        for item in predicted:
            key = key_fn(item)
            if key is None:
                continue
            pred_raw_keys.append(key)
            pred_by_key.setdefault(key, item)

        exp_by_key: Dict[Tuple[Any, ...], Mapping[str, Any]] = {}
        for item in expected:
            key = key_fn(item)
            if key is None:
                continue
            exp_by_key.setdefault(key, item)

        pred_unique_set = set(pred_by_key)
        exp_set = set(exp_by_key)
        tp_set = pred_unique_set & exp_set

        precision = _safe_ratio(len(tp_set), len(pred_unique_set))
        recall = _safe_ratio(len(tp_set), len(exp_set))
        f1 = _f1(precision, recall)

        tp_pairs: List[Tuple[Mapping[str, Any], Mapping[str, Any]]] = [(pred_by_key[k], exp_by_key[k]) for k in tp_set]

        return (
            ItemMetrics(
                predicted_count_raw=len(pred_raw_keys),
                predicted_count_unique=len(pred_unique_set),
                expected_count=len(exp_set),
                true_positive_count=len(tp_set),
                precision=precision,
                recall=recall,
                f1=f1,
            ),
            tp_pairs,
        )

    def _score_properties(
        self,
        all_predicted: Sequence[Mapping[str, Any]],
        tp_pairs: Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]],
    ) -> PropertyMetrics:
        predicted_property_count = 0
        valid_property_count = 0
        for item in all_predicted:
            label = item.get("label")
            if not label:
                continue
            props = item.get("properties", {}) or {}
            item_type = item.get("type")
            for key in props:
                predicted_property_count += 1
                if self._is_valid_property(str(label), item_type, key):
                    valid_property_count += 1

        expected_tp_property_count = 0
        predicted_tp_property_count = 0
        exact_match_property_count = 0
        for pred, exp in tp_pairs:
            pred_props = pred.get("properties", {}) or {}
            exp_props = exp.get("properties", {}) or {}
            predicted_tp_property_count += len(pred_props)
            expected_tp_property_count += len(exp_props)
            for key, value in pred_props.items():
                if key in exp_props and exp_props[key] == value:
                    exact_match_property_count += 1

        return PropertyMetrics(
            predicted_property_count=predicted_property_count,
            valid_property_count=valid_property_count,
            property_valid_ratio=_safe_ratio(valid_property_count, predicted_property_count),
            expected_tp_property_count=expected_tp_property_count,
            predicted_tp_property_count=predicted_tp_property_count,
            exact_match_property_count=exact_match_property_count,
            property_exact_match_rate=_safe_ratio(exact_match_property_count, expected_tp_property_count),
        )

    def _is_valid_property(self, label: str, item_type: Optional[Any], key: str) -> bool:
        if item_type == "vertex":
            return key in self._schema_index.allowed_properties("vertex", label)
        if item_type == "edge":
            return key in self._schema_index.allowed_properties("edge", label)
        # Unknown type: allow the property if it's declared on either the vertex
        # label or edge label of the same name (item_type is a soft hint).
        if self._schema_index.is_vertex_label(label):
            return key in self._schema_index.allowed_properties("vertex", label)
        if self._schema_index.is_edge_label(label):
            return key in self._schema_index.allowed_properties("edge", label)
        return False
