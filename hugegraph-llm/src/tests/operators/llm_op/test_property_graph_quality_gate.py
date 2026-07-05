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

"""Unit tests for GraphQualityGate and QualityMetrics (Issue #74)."""

from __future__ import annotations

import json

import pytest

from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced import (
    DocumentGraph,
    GraphQualityGate,
    QualityMetrics,
    StructuredWarning,
    WarningCode,
)

pytestmark = pytest.mark.contract


def _w(code: WarningCode, item_type: str = "vertex", **kwargs) -> StructuredWarning:
    return StructuredWarning(code=code, item_type=item_type, reason="test", **kwargs)


# ------------------------------------------------------------ zero-input safety
class TestZeroInputSafety:
    def test_empty_graph_no_warnings_all_ratios_one(self):
        """No candidates, no problems → every ratio reports 1.0 (design contract)."""
        metrics = GraphQualityGate.compute(
            DocumentGraph(),
            warnings=[],
            candidate_vertex_count=0,
            candidate_edge_count=0,
        )
        assert metrics.schema_valid_vertex_ratio == 1.0
        assert metrics.schema_valid_edge_ratio == 1.0
        assert metrics.endpoint_resolution_rate == 1.0
        # Reduction metrics stay at 0.0 for the empty case (no reduction achieved).
        assert metrics.duplicate_vertex_reduction == 0.0
        assert metrics.duplicate_edge_reduction == 0.0
        assert metrics.property_valid_ratio == 1.0

    def test_no_nan_ever(self):
        """Every ratio field must be a plain float, no matter the input state."""
        metrics = GraphQualityGate.compute(
            DocumentGraph(),
            warnings=[],
            candidate_vertex_count=0,
            candidate_edge_count=0,
        )
        for name in [
            "schema_valid_vertex_ratio",
            "schema_valid_edge_ratio",
            "endpoint_resolution_rate",
            "duplicate_vertex_reduction",
            "duplicate_edge_reduction",
            "property_valid_ratio",
        ]:
            value = getattr(metrics, name)
            assert value == value  # NaN != NaN, so this catches NaN.
            assert 0.0 <= value <= 1.0


# ------------------------------------------------------ schema-validity ratios
class TestSchemaValidRatios:
    def test_vertex_ratio_reflects_normalization_drops(self):
        """4 candidate vertices, 3 survived normalization → 3/4."""
        graph = DocumentGraph(vertices=[{}, {}, {}], pre_merge_vertex_count=3)
        metrics = GraphQualityGate.compute(
            graph,
            warnings=[_w(WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA)],
            candidate_vertex_count=4,
            candidate_edge_count=0,
        )
        assert metrics.schema_valid_vertex_ratio == 0.75

    def test_edge_ratio_reflects_normalization_drops(self):
        graph = DocumentGraph(edges=[{}, {}], pre_merge_edge_count=2)
        metrics = GraphQualityGate.compute(
            graph,
            warnings=[
                _w(WarningCode.EDGE_LABEL_NOT_IN_SCHEMA, item_type="edge"),
                _w(WarningCode.EDGE_ENDPOINT_MISMATCH, item_type="edge"),
            ],
            candidate_vertex_count=0,
            candidate_edge_count=4,
        )
        assert metrics.schema_valid_edge_ratio == 0.5

    def test_zero_candidates_ratio_is_one_regardless_of_kept(self):
        """Downstream should never divide by zero; empty candidate → 1.0 by contract."""
        metrics = GraphQualityGate.compute(
            DocumentGraph(),
            warnings=[],
            candidate_vertex_count=0,
            candidate_edge_count=0,
        )
        assert metrics.schema_valid_vertex_ratio == 1.0


# --------------------------------------------------- endpoint resolution rate
class TestEndpointResolution:
    def test_all_pending_resolved(self):
        """2 pending edges, 0 unresolved / 0 ambiguous → 1.0."""
        graph = DocumentGraph(edges=[{}, {}], pre_merge_edge_count=2, endpoint_repair_count=2)
        warnings = [
            _w(WarningCode.ENDPOINT_PENDING_REPAIR, item_type="edge"),
            _w(WarningCode.ENDPOINT_PENDING_REPAIR, item_type="edge"),
        ]
        metrics = GraphQualityGate.compute(
            graph,
            warnings=warnings,
            candidate_vertex_count=0,
            candidate_edge_count=2,
        )
        assert metrics.endpoint_resolution_rate == 1.0
        assert metrics.endpoint_repair_count == 2

    def test_partial_resolution(self):
        """3 pending, 1 unresolved → 2/3."""
        warnings = [
            _w(WarningCode.ENDPOINT_PENDING_REPAIR, item_type="edge"),
            _w(WarningCode.ENDPOINT_PENDING_REPAIR, item_type="edge"),
            _w(WarningCode.ENDPOINT_PENDING_REPAIR, item_type="edge"),
            _w(WarningCode.ENDPOINT_UNRESOLVED, item_type="edge"),
        ]
        metrics = GraphQualityGate.compute(
            DocumentGraph(),
            warnings=warnings,
            candidate_vertex_count=0,
            candidate_edge_count=0,
        )
        assert metrics.endpoint_resolution_rate == 2 / 3

    def test_ambiguous_counts_toward_unresolved(self):
        warnings = [
            _w(WarningCode.ENDPOINT_PENDING_REPAIR, item_type="edge"),
            _w(WarningCode.ENDPOINT_PENDING_REPAIR, item_type="edge"),
            _w(WarningCode.ENDPOINT_AMBIGUOUS, item_type="edge"),
        ]
        metrics = GraphQualityGate.compute(
            DocumentGraph(),
            warnings=warnings,
            candidate_vertex_count=0,
            candidate_edge_count=0,
        )
        assert metrics.endpoint_resolution_rate == 0.5

    def test_zero_pending_rate_is_one(self):
        metrics = GraphQualityGate.compute(
            DocumentGraph(),
            warnings=[],
            candidate_vertex_count=0,
            candidate_edge_count=0,
        )
        assert metrics.endpoint_resolution_rate == 1.0


# ------------------------------------------------------ duplicate reduction
class TestDuplicateReduction:
    def test_half_of_vertices_merged(self):
        graph = DocumentGraph(vertices=[{}, {}], pre_merge_vertex_count=4)
        metrics = GraphQualityGate.compute(graph, warnings=[], candidate_vertex_count=4, candidate_edge_count=0)
        assert metrics.duplicate_vertex_reduction == 0.5

    def test_all_edges_merged(self):
        graph = DocumentGraph(edges=[{}], pre_merge_edge_count=5)
        metrics = GraphQualityGate.compute(graph, warnings=[], candidate_vertex_count=0, candidate_edge_count=5)
        assert metrics.duplicate_edge_reduction == 0.8

    def test_no_pre_merge_yields_zero_reduction(self):
        """Empty document should not surface reduction as 1.0 — nothing was reduced."""
        graph = DocumentGraph()
        metrics = GraphQualityGate.compute(graph, warnings=[], candidate_vertex_count=0, candidate_edge_count=0)
        assert metrics.duplicate_vertex_reduction == 0.0
        assert metrics.duplicate_edge_reduction == 0.0


# ------------------------------------------------------ property valid ratio
class TestPropertyValidRatio:
    def test_full_valid(self):
        graph = DocumentGraph(
            vertices=[{"properties": {"name": "Tom", "aliases": []}}],
            edges=[{"properties": {"role": "Forrest"}}],
        )
        metrics = GraphQualityGate.compute(graph, warnings=[], candidate_vertex_count=1, candidate_edge_count=1)
        assert metrics.property_valid_ratio == 1.0

    def test_half_dropped(self):
        """2 kept, 2 dropped → 2/4 = 0.5."""
        graph = DocumentGraph(vertices=[{"properties": {"name": "Tom", "aliases": []}}])
        warnings = [
            _w(WarningCode.PROPERTY_NOT_IN_SCHEMA),
            _w(WarningCode.PROPERTY_COERCION_FAILED),
        ]
        metrics = GraphQualityGate.compute(graph, warnings=warnings, candidate_vertex_count=1, candidate_edge_count=0)
        assert metrics.property_valid_ratio == 0.5

    def test_property_conflict_is_not_counted_as_invalid(self):
        """First-wins conflict preserves the value; it must not depress property_valid_ratio."""
        graph = DocumentGraph(vertices=[{"properties": {"name": "Tom"}}])
        warnings = [_w(WarningCode.PROPERTY_CONFLICT)]
        metrics = GraphQualityGate.compute(graph, warnings=warnings, candidate_vertex_count=1, candidate_edge_count=0)
        assert metrics.property_valid_ratio == 1.0
        assert metrics.property_conflict_count == 1


# -------------------------------------------------------------- counters
class TestCounters:
    def test_dropped_item_count_sums_all_drop_codes(self):
        warnings = [
            _w(WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA),
            _w(WarningCode.EDGE_LABEL_NOT_IN_SCHEMA, item_type="edge"),
            _w(WarningCode.ENDPOINT_UNRESOLVED, item_type="edge"),
            _w(WarningCode.ITEM_NOT_OBJECT, item_type="graph"),
            _w(WarningCode.PROPERTY_NOT_IN_SCHEMA),
        ]
        metrics = GraphQualityGate.compute(
            DocumentGraph(),
            warnings=warnings,
            candidate_vertex_count=0,
            candidate_edge_count=0,
        )
        assert metrics.dropped_item_count == 5

    def test_dropping_codes_exclude_duplicates_and_coercions(self):
        """DUPLICATE_*_MERGED / PROPERTY_COERCED must NOT inflate dropped_item_count."""
        warnings = [
            _w(WarningCode.DUPLICATE_VERTEX_MERGED),
            _w(WarningCode.DUPLICATE_EDGE_MERGED, item_type="edge"),
            _w(WarningCode.PROPERTY_COERCED),
            _w(WarningCode.PROPERTY_CONFLICT),
        ]
        metrics = GraphQualityGate.compute(
            DocumentGraph(),
            warnings=warnings,
            candidate_vertex_count=0,
            candidate_edge_count=0,
        )
        assert metrics.dropped_item_count == 0

    def test_coerced_property_count(self):
        warnings = [_w(WarningCode.PROPERTY_COERCED), _w(WarningCode.PROPERTY_COERCED)]
        metrics = GraphQualityGate.compute(
            DocumentGraph(),
            warnings=warnings,
            candidate_vertex_count=0,
            candidate_edge_count=0,
        )
        assert metrics.coerced_property_count == 2

    def test_endpoint_repair_count_pulled_from_graph(self):
        graph = DocumentGraph(endpoint_repair_count=7)
        metrics = GraphQualityGate.compute(graph, warnings=[], candidate_vertex_count=0, candidate_edge_count=0)
        assert metrics.endpoint_repair_count == 7


# ------------------------------------------------ warning_code_distribution
class TestWarningCodeDistribution:
    def test_distribution_matches_warning_stream(self):
        warnings = [
            _w(WarningCode.PROPERTY_COERCED),
            _w(WarningCode.PROPERTY_COERCED),
            _w(WarningCode.DUPLICATE_VERTEX_MERGED),
        ]
        metrics = GraphQualityGate.compute(
            DocumentGraph(),
            warnings=warnings,
            candidate_vertex_count=0,
            candidate_edge_count=0,
        )
        assert metrics.warning_code_distribution == {
            "PROPERTY_COERCED": 2,
            "DUPLICATE_VERTEX_MERGED": 1,
        }

    def test_distribution_empty_for_no_warnings(self):
        metrics = GraphQualityGate.compute(
            DocumentGraph(),
            warnings=[],
            candidate_vertex_count=0,
            candidate_edge_count=0,
        )
        assert metrics.warning_code_distribution == {}


# ------------------------------------------------------ serialization
class TestQualityMetricsSerialization:
    def test_to_dict_rounds_ratios_to_four_decimals(self):
        graph = DocumentGraph(vertices=[{}], pre_merge_vertex_count=3)
        metrics = GraphQualityGate.compute(
            graph,
            warnings=[
                _w(WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA),
                _w(WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA),
                _w(WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA),
                _w(WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA),
            ],
            candidate_vertex_count=7,  # → 3/7 = 0.42857...
            candidate_edge_count=0,
        )
        d = metrics.to_dict()
        assert d["schema_valid_vertex_ratio"] == 0.4286

    def test_to_dict_is_pure_json(self):
        """Round-trip through json.dumps to prove the shape is JSON-safe."""
        graph = DocumentGraph(vertices=[{"properties": {"n": 1}}], pre_merge_vertex_count=1)
        metrics = GraphQualityGate.compute(graph, warnings=[], candidate_vertex_count=1, candidate_edge_count=0)
        encoded = json.dumps(metrics.to_dict())
        decoded = json.loads(encoded)
        assert set(decoded) == {
            "schema_valid_vertex_ratio",
            "schema_valid_edge_ratio",
            "endpoint_resolution_rate",
            "duplicate_vertex_reduction",
            "duplicate_edge_reduction",
            "property_valid_ratio",
            "dropped_item_count",
            "coerced_property_count",
            "endpoint_repair_count",
            "property_conflict_count",
            "warning_code_distribution",
        }

    def test_metrics_are_frozen(self):
        """QualityMetrics is a frozen dataclass — no post-hoc mutation."""
        import dataclasses

        metrics = GraphQualityGate.compute(
            DocumentGraph(),
            warnings=[],
            candidate_vertex_count=0,
            candidate_edge_count=0,
        )
        try:
            metrics.dropped_item_count = 99  # type: ignore[misc]
            failed = False
        except dataclasses.FrozenInstanceError:
            failed = True
        assert failed


# ------------------------------------------------------ robustness
class TestGateRobustness:
    def test_ignores_non_structured_warning_entries(self):
        """A malformed warning at the tail should not sink the metrics."""
        warnings = [
            _w(WarningCode.PROPERTY_COERCED),
            "not a warning",  # type: ignore[list-item]
            {"code": "also not a warning"},  # type: ignore[list-item]
        ]
        metrics = GraphQualityGate.compute(
            DocumentGraph(),
            warnings=warnings,  # type: ignore[arg-type]
            candidate_vertex_count=0,
            candidate_edge_count=0,
        )
        # The single valid warning is counted; the malformed entries are skipped.
        assert metrics.coerced_property_count == 1
        assert metrics.warning_code_distribution == {"PROPERTY_COERCED": 1}


# ------------------------------------------------------ integration
class TestGateIntegration:
    def test_realistic_multi_metric_scenario(self):
        """Everything hits at once: drops, coercions, merges, repairs."""
        graph = DocumentGraph(
            vertices=[{"properties": {"name": "Tom"}}, {"properties": {"title": "FG", "year": 1994}}],
            edges=[{"properties": {"role": "Forrest"}}],
            pre_merge_vertex_count=4,
            pre_merge_edge_count=3,
            endpoint_repair_count=1,
        )
        warnings = [
            _w(WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA),
            _w(WarningCode.PROPERTY_NOT_IN_SCHEMA),
            _w(WarningCode.PROPERTY_COERCED),
            _w(WarningCode.ENDPOINT_PENDING_REPAIR, item_type="edge"),
            _w(WarningCode.DUPLICATE_VERTEX_MERGED),
            _w(WarningCode.DUPLICATE_VERTEX_MERGED),
            _w(WarningCode.DUPLICATE_EDGE_MERGED, item_type="edge"),
            _w(WarningCode.DUPLICATE_EDGE_MERGED, item_type="edge"),
            _w(WarningCode.PROPERTY_CONFLICT),
        ]
        metrics = GraphQualityGate.compute(
            graph,
            warnings=warnings,
            candidate_vertex_count=5,
            candidate_edge_count=3,
        )
        # Sanity checks — every field populated with a plausible value.
        assert metrics.schema_valid_vertex_ratio == 0.8  # 4/5
        assert metrics.schema_valid_edge_ratio == 1.0  # 3/3
        assert metrics.endpoint_resolution_rate == 1.0  # 1 pending, 0 unresolved
        assert metrics.duplicate_vertex_reduction == 0.5  # (4-2)/4
        assert metrics.duplicate_edge_reduction == 2 / 3
        assert metrics.dropped_item_count == 2  # 1 vertex + 1 property
        assert metrics.coerced_property_count == 1
        assert metrics.endpoint_repair_count == 1
        assert metrics.property_conflict_count == 1
        assert isinstance(metrics, QualityMetrics)
