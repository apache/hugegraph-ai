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

"""Unit tests for the structured warning registry (Issue #74)."""

from __future__ import annotations

import dataclasses
import json

import pytest

from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced import (
    StructuredWarning,
    WarningCode,
    warning_code_distribution,
)


# ---------------------------------------------------------------- WarningCode
class TestWarningCode:
    def test_code_is_str_subclass_for_json_encoding(self):
        """A ``str, Enum`` code JSON-serializes to its bare name without a custom encoder."""
        payload = {"code": WarningCode.ENDPOINT_UNRESOLVED}
        assert json.loads(json.dumps(payload, default=str)) == {"code": "ENDPOINT_UNRESOLVED"}

    def test_code_equals_its_string_value(self):
        assert WarningCode.JSON_NOT_FOUND == "JSON_NOT_FOUND"
        assert WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA == "VERTEX_LABEL_NOT_IN_SCHEMA"

    def test_code_registry_covers_full_design_surface(self):
        """Guard against silent removal — every code the design contract names must exist."""
        expected = {
            "JSON_NOT_FOUND",
            "JSON_DECODE_FAILED",
            "GRAPH_SECTION_MISSING",
            "ITEM_NOT_OBJECT",
            "ITEM_TYPE_MISMATCH",
            "VERTEX_LABEL_NOT_IN_SCHEMA",
            "VERTEX_PRIMARY_KEY_MISSING",
            "VERTEX_PRIMARY_KEY_INVALID",
            "VERTEX_ALIAS_RECORDED",
            "EDGE_LABEL_NOT_IN_SCHEMA",
            "EDGE_ENDPOINT_MISMATCH",
            "PROPERTY_NOT_IN_SCHEMA",
            "PROPERTY_COERCED",
            "PROPERTY_COERCION_FAILED",
            "ENDPOINT_PENDING_REPAIR",
            "ENDPOINT_UNRESOLVED",
            "ENDPOINT_AMBIGUOUS",
            "DUPLICATE_VERTEX_MERGED",
            "DUPLICATE_EDGE_MERGED",
            "PROPERTY_CONFLICT",
        }
        actual = {c.value for c in WarningCode}
        missing = expected - actual
        assert not missing, f"missing codes: {sorted(missing)}"


# ---------------------------------------------------------- StructuredWarning
class TestStructuredWarningConstruction:
    def test_full_construction(self):
        w = StructuredWarning(
            code=WarningCode.ENDPOINT_UNRESOLVED,
            item_type="edge",
            reason="target vertex cannot be resolved",
            label="acted_in",
            chunk_id=2,
            strategy="enhanced",
            context={"edge_key": "acted_in|1:Tom Hanks|?"},
        )
        assert w.code is WarningCode.ENDPOINT_UNRESOLVED
        assert w.item_type == "edge"
        assert w.label == "acted_in"
        assert w.chunk_id == 2
        assert w.strategy == "enhanced"
        assert w.context == {"edge_key": "acted_in|1:Tom Hanks|?"}

    def test_defaults_are_sensible(self):
        w = StructuredWarning(
            code=WarningCode.GRAPH_SECTION_MISSING,
            item_type="graph",
            reason="edges missing",
        )
        assert w.label is None
        assert w.chunk_id is None
        assert w.strategy == "enhanced"
        assert w.context is None

    def test_accepts_raw_string_code(self):
        """Callers may pass the bare string without importing WarningCode."""
        w = StructuredWarning(code="JSON_NOT_FOUND", item_type="graph", reason="no json")
        assert w.code is WarningCode.JSON_NOT_FOUND

    def test_rejects_unknown_string_code(self):
        with pytest.raises(ValueError):
            StructuredWarning(code="WHATEVER", item_type="graph", reason="")

    def test_rejects_invalid_item_type(self):
        with pytest.raises(ValueError):
            StructuredWarning(
                code=WarningCode.JSON_NOT_FOUND,
                item_type="triple",
                reason="oops",
            )

    def test_rejects_negative_chunk_id(self):
        with pytest.raises(ValueError):
            StructuredWarning(
                code=WarningCode.JSON_NOT_FOUND,
                item_type="graph",
                reason="",
                chunk_id=-1,
            )


# ---------------------------------------------------- StructuredWarning shape
class TestStructuredWarningShape:
    def test_is_frozen_dataclass(self):
        w = StructuredWarning(code=WarningCode.JSON_NOT_FOUND, item_type="graph", reason="")
        with pytest.raises(dataclasses.FrozenInstanceError):
            w.reason = "mutated"  # type: ignore[misc]

    def test_hashable_and_dedupable(self):
        a = StructuredWarning(code=WarningCode.JSON_NOT_FOUND, item_type="graph", reason="x")
        b = StructuredWarning(code=WarningCode.JSON_NOT_FOUND, item_type="graph", reason="x")
        assert hash(a) == hash(b)
        # Warnings without context can be placed in a set.
        assert len({a, b}) == 1

    def test_context_is_copied_defensively(self):
        source_ctx = {"key": "value"}
        w = StructuredWarning(
            code=WarningCode.JSON_NOT_FOUND,
            item_type="graph",
            reason="",
            context=source_ctx,
        )
        source_ctx["key"] = "mutated"
        assert w.context == {"key": "value"}


# ----------------------------------------------------- StructuredWarning.to_dict
class TestSerialization:
    def test_to_dict_full(self):
        w = StructuredWarning(
            code=WarningCode.PROPERTY_COERCED,
            item_type="vertex",
            reason="year converted from string to INT",
            label="movie",
            chunk_id=0,
            context={"property": "year"},
        )
        assert w.to_dict() == {
            "code": "PROPERTY_COERCED",
            "item_type": "vertex",
            "reason": "year converted from string to INT",
            "strategy": "enhanced",
            "label": "movie",
            "chunk_id": 0,
            "context": {"property": "year"},
        }

    def test_to_dict_omits_none_optional_fields(self):
        w = StructuredWarning(
            code=WarningCode.JSON_NOT_FOUND,
            item_type="graph",
            reason="no json",
        )
        d = w.to_dict()
        assert d == {
            "code": "JSON_NOT_FOUND",
            "item_type": "graph",
            "reason": "no json",
            "strategy": "enhanced",
        }
        # Explicit — None fields are absent, not present with a None value.
        assert "label" not in d
        assert "chunk_id" not in d
        assert "context" not in d

    def test_to_dict_is_json_serializable_without_custom_encoder(self):
        w = StructuredWarning(
            code=WarningCode.DUPLICATE_EDGE_MERGED,
            item_type="edge",
            reason="merged",
            label="acted_in",
            chunk_id=3,
            context={"count": 2, "keys": ["a", "b"]},
        )
        encoded = json.dumps(w.to_dict())
        assert json.loads(encoded)["code"] == "DUPLICATE_EDGE_MERGED"


# ------------------------------------------------------- surface-affecting
class TestSurfaceAffecting:
    def test_dropped_items_are_surface_affecting(self):
        assert (
            StructuredWarning(
                code=WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA,
                item_type="vertex",
                reason="",
            ).is_surface_affecting
            is True
        )
        assert (
            StructuredWarning(
                code=WarningCode.ENDPOINT_UNRESOLVED,
                item_type="edge",
                reason="",
            ).is_surface_affecting
            is True
        )

    def test_merges_and_aliases_are_surface_affecting_or_not_per_design(self):
        """DUPLICATE_*_MERGED is surface-affecting (item was removed / consolidated);
        VERTEX_ALIAS_RECORDED is not (purely observational)."""
        assert (
            StructuredWarning(
                code=WarningCode.DUPLICATE_VERTEX_MERGED, item_type="vertex", reason=""
            ).is_surface_affecting
            is True
        )
        assert (
            StructuredWarning(
                code=WarningCode.VERTEX_ALIAS_RECORDED, item_type="vertex", reason=""
            ).is_surface_affecting
            is False
        )

    def test_pending_repair_and_section_missing_not_surface_affecting(self):
        """Intermediate-state markers do not, by themselves, drop or alter output."""
        assert (
            StructuredWarning(
                code=WarningCode.ENDPOINT_PENDING_REPAIR, item_type="edge", reason=""
            ).is_surface_affecting
            is False
        )
        assert (
            StructuredWarning(code=WarningCode.GRAPH_SECTION_MISSING, item_type="graph", reason="").is_surface_affecting
            is False
        )

    def test_property_conflict_not_surface_affecting(self):
        """First-wins merge conflict retains a value; the conflict is reported but no data is lost."""
        assert (
            StructuredWarning(code=WarningCode.PROPERTY_CONFLICT, item_type="vertex", reason="").is_surface_affecting
            is False
        )


# ----------------------------------------------------- code distribution helper
class TestWarningCodeDistribution:
    def test_empty_input(self):
        assert warning_code_distribution([]) == {}

    def test_counts_by_code(self):
        warnings = [
            StructuredWarning(code=WarningCode.JSON_NOT_FOUND, item_type="graph", reason=""),
            StructuredWarning(code=WarningCode.JSON_NOT_FOUND, item_type="graph", reason=""),
            StructuredWarning(code=WarningCode.ENDPOINT_UNRESOLVED, item_type="edge", reason=""),
        ]
        dist = warning_code_distribution(warnings)
        assert dist == {"JSON_NOT_FOUND": 2, "ENDPOINT_UNRESOLVED": 1}

    def test_silently_skips_foreign_objects(self):
        """A malformed entry at the tail of a long pipeline should not sink the report."""
        warnings = [
            StructuredWarning(code=WarningCode.JSON_NOT_FOUND, item_type="graph", reason=""),
            "not a warning",
            {"code": "also not a warning"},
        ]
        assert warning_code_distribution(warnings) == {"JSON_NOT_FOUND": 1}
