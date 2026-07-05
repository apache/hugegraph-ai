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

"""Graph quality gate for the enhanced graph extraction strategy.

Aggregates the warnings emitted throughout the pipeline plus the counts
tracked by ``DocumentGraph`` into a single ``QualityMetrics`` bundle that:

* powers ``meta.quality_metrics`` in the API response,
* feeds the baseline-vs-enhanced comparison report in ``docs/quality/``,
* stays stable across zero-input cases (empty documents, zero-candidate
  chunks) — no NaN, no divide-by-zero.

The gate is stateless: one call to ``compute`` gives a snapshot for the
inputs at hand. Nothing here mutates the passed-in graph or warning list.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Sequence

from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.types import DocumentGraph
from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.warnings import (
    StructuredWarning,
    WarningCode,
    warning_code_distribution,
)

# Codes that cause a candidate item to disappear from the emitted graph.
# Excludes DUPLICATE_*_MERGED (item consolidated, not dropped) and
# PROPERTY_COERCED (value changed, item survived).
_VERTEX_DROP_CODES: FrozenSet[WarningCode] = frozenset(
    {
        WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA,
        WarningCode.VERTEX_PRIMARY_KEY_MISSING,
        WarningCode.VERTEX_PRIMARY_KEY_INVALID,
    }
)
_EDGE_DROP_CODES: FrozenSet[WarningCode] = frozenset(
    {
        WarningCode.EDGE_LABEL_NOT_IN_SCHEMA,
        WarningCode.EDGE_ENDPOINT_MISMATCH,
        WarningCode.ENDPOINT_UNRESOLVED,
        WarningCode.ENDPOINT_AMBIGUOUS,
    }
)
_ITEM_DROP_CODES: FrozenSet[WarningCode] = frozenset(
    {
        WarningCode.ITEM_NOT_OBJECT,
        WarningCode.ITEM_TYPE_MISMATCH,
    }
)
_PROPERTY_DROP_CODES: FrozenSet[WarningCode] = frozenset(
    {
        WarningCode.PROPERTY_NOT_IN_SCHEMA,
        WarningCode.PROPERTY_COERCION_FAILED,
    }
)


@dataclass(frozen=True)
class QualityMetrics:
    """Aggregate quality metrics for one enhanced-strategy invocation.

    Ratios live in ``[0.0, 1.0]``. Zero-candidate cases record ``1.0``
    (no candidates, no problems) — this matches the design contract that
    ratios never surface ``NaN``.
    """

    # Must metrics per design section 6.6.
    schema_valid_vertex_ratio: float
    schema_valid_edge_ratio: float
    endpoint_resolution_rate: float
    duplicate_vertex_reduction: float
    duplicate_edge_reduction: float
    property_valid_ratio: float
    dropped_item_count: int
    coerced_property_count: int
    endpoint_repair_count: int
    # Should metrics we can produce cheaply from the same inputs.
    property_conflict_count: int
    warning_code_distribution: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dict suitable for the API response.

        Ratios are rounded to 4 decimals to keep the response compact and
        stable across floating-point noise; integer counters flow through
        unmodified.
        """
        return {
            "schema_valid_vertex_ratio": round(self.schema_valid_vertex_ratio, 4),
            "schema_valid_edge_ratio": round(self.schema_valid_edge_ratio, 4),
            "endpoint_resolution_rate": round(self.endpoint_resolution_rate, 4),
            "duplicate_vertex_reduction": round(self.duplicate_vertex_reduction, 4),
            "duplicate_edge_reduction": round(self.duplicate_edge_reduction, 4),
            "property_valid_ratio": round(self.property_valid_ratio, 4),
            "dropped_item_count": self.dropped_item_count,
            "coerced_property_count": self.coerced_property_count,
            "endpoint_repair_count": self.endpoint_repair_count,
            "property_conflict_count": self.property_conflict_count,
            "warning_code_distribution": dict(self.warning_code_distribution),
        }


class GraphQualityGate:
    """Compute ``QualityMetrics`` from a document graph and its warnings.

    Callers supply the pre-normalize candidate counts (typically the parser's
    output totals) so the gate can compute schema-validity ratios without
    re-scanning the raw LLM output.
    """

    @staticmethod
    def compute(
        document_graph: DocumentGraph,
        warnings: Sequence[StructuredWarning],
        *,
        candidate_vertex_count: int,
        candidate_edge_count: int,
    ) -> QualityMetrics:
        counter: Counter[WarningCode] = Counter()
        for w in warnings:
            if isinstance(w, StructuredWarning):
                counter[w.code] += 1

        post_merge_vertex = len(document_graph.vertices)
        post_merge_edge = len(document_graph.edges)
        pre_merge_vertex = document_graph.pre_merge_vertex_count
        pre_merge_edge = document_graph.pre_merge_edge_count

        # Schema-validity ratios: fraction of candidate items that survived
        # normalization. Duplicates count as valid (they made it through
        # normalization); the merge step reduces them separately.
        vertex_drops = sum(counter.get(c, 0) for c in _VERTEX_DROP_CODES)
        edge_drops = sum(counter.get(c, 0) for c in _EDGE_DROP_CODES)
        schema_valid_vertex_ratio = _safe_ratio(pre_merge_vertex, candidate_vertex_count)
        schema_valid_edge_ratio = _safe_ratio(pre_merge_edge, candidate_edge_count)

        # Endpoint resolution: edges the normalizer left pending vs. how
        # many the assembler either resolved or dropped as unresolved/
        # ambiguous. Using code counts ties the metric to observable
        # warning surface rather than internal state.
        pending_edges = counter.get(WarningCode.ENDPOINT_PENDING_REPAIR, 0)
        unresolved_edges = counter.get(WarningCode.ENDPOINT_UNRESOLVED, 0) + counter.get(
            WarningCode.ENDPOINT_AMBIGUOUS, 0
        )
        resolved_edges = max(0, pending_edges - unresolved_edges)
        endpoint_resolution_rate = _safe_ratio(resolved_edges, pending_edges)

        # Duplicate reduction from the assembler's merge step.
        duplicate_vertex_reduction = _safe_ratio(
            max(0, pre_merge_vertex - post_merge_vertex), pre_merge_vertex, default=0.0
        )
        duplicate_edge_reduction = _safe_ratio(max(0, pre_merge_edge - post_merge_edge), pre_merge_edge, default=0.0)

        # Property validity: kept properties over kept-plus-invalidated ones.
        # Merge-time conflicts do not count as invalid (the first value stays
        # in the emitted graph).
        kept_properties = _count_emitted_properties(document_graph)
        property_drops = sum(counter.get(c, 0) for c in _PROPERTY_DROP_CODES)
        property_valid_ratio = _safe_ratio(kept_properties, kept_properties + property_drops)

        item_drops = sum(counter.get(c, 0) for c in _ITEM_DROP_CODES)
        dropped_item_count = vertex_drops + edge_drops + item_drops + property_drops
        coerced_property_count = counter.get(WarningCode.PROPERTY_COERCED, 0)
        property_conflict_count = counter.get(WarningCode.PROPERTY_CONFLICT, 0)

        return QualityMetrics(
            schema_valid_vertex_ratio=schema_valid_vertex_ratio,
            schema_valid_edge_ratio=schema_valid_edge_ratio,
            endpoint_resolution_rate=endpoint_resolution_rate,
            duplicate_vertex_reduction=duplicate_vertex_reduction,
            duplicate_edge_reduction=duplicate_edge_reduction,
            property_valid_ratio=property_valid_ratio,
            dropped_item_count=dropped_item_count,
            coerced_property_count=coerced_property_count,
            endpoint_repair_count=document_graph.endpoint_repair_count,
            property_conflict_count=property_conflict_count,
            warning_code_distribution=warning_code_distribution(warnings),
        )


def _safe_ratio(numerator: int, denominator: int, *, default: float = 1.0) -> float:
    """Return ``numerator / denominator`` with a deterministic zero fallback.

    Design contract: ratios never surface NaN. When both numerator and
    denominator would be zero (no candidates, no problems) the ratio is
    ``1.0`` by default. Callers can override to ``0.0`` for
    reduction-style metrics where "nothing to reduce" should read as
    "no reduction achieved".
    """
    if denominator <= 0:
        return default
    return float(numerator) / float(denominator)


def _count_emitted_properties(graph: DocumentGraph) -> int:
    total = 0
    for v in graph.vertices:
        props = v.get("properties") or {}
        total += len(props)
    for e in graph.edges:
        props = e.get("properties") or {}
        total += len(props)
    return total
