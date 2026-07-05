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

"""Unit tests for CandidateGraphParser and CandidateGraph (Issue #74)."""

from __future__ import annotations

import json
from typing import List

from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced import (
    CandidateGraph,
    CandidateGraphParser,
    StructuredWarning,
    WarningCode,
)


def _codes(warnings: List[StructuredWarning]) -> List[WarningCode]:
    return [w.code for w in warnings]


# --------------------------------------------------------------- CandidateGraph
class TestCandidateGraphDataclass:
    def test_default_construction_is_empty(self):
        g = CandidateGraph()
        assert g.vertices == []
        assert g.edges == []
        assert g.is_empty is True

    def test_populated_graph_is_not_empty(self):
        g = CandidateGraph(vertices=[{"label": "person"}], edges=[])
        assert not g.is_empty

    def test_defaults_do_not_alias_across_instances(self):
        """Frozen dataclass with default_factory must not share the list across instances."""
        a = CandidateGraph()
        b = CandidateGraph()
        a.vertices.append({"label": "x"})
        assert b.vertices == []


# ---------------------------------------------------- Format 1: plain grouped JSON
class TestGroupedJson:
    def test_grouped_object_with_both_sections(self):
        parser = CandidateGraphParser()
        graph, warnings = parser.parse(
            json.dumps(
                {
                    "vertices": [{"type": "vertex", "label": "person", "properties": {"name": "Tom"}}],
                    "edges": [
                        {
                            "type": "edge",
                            "label": "acted_in",
                            "outV": "v1",
                            "inV": "v2",
                            "properties": {},
                        }
                    ],
                }
            )
        )
        assert warnings == []
        assert len(graph.vertices) == 1
        assert graph.vertices[0]["label"] == "person"
        assert graph.vertices[0]["type"] == "vertex"
        assert len(graph.edges) == 1

    def test_missing_edges_section_emits_warning_and_leaves_empty(self):
        parser = CandidateGraphParser()
        graph, warnings = parser.parse(
            json.dumps({"vertices": [{"type": "vertex", "label": "person", "properties": {}}]})
        )
        assert _codes(warnings) == [WarningCode.GRAPH_SECTION_MISSING]
        assert warnings[0].reason.startswith("'edges'")
        assert graph.edges == []

    def test_missing_vertices_section_emits_warning_and_leaves_empty(self):
        parser = CandidateGraphParser()
        graph, warnings = parser.parse(json.dumps({"edges": []}))
        assert _codes(warnings) == [WarningCode.GRAPH_SECTION_MISSING]
        assert warnings[0].reason.startswith("'vertices'")
        assert graph.vertices == []

    def test_both_sections_missing_emits_two_warnings(self):
        parser = CandidateGraphParser()
        graph, warnings = parser.parse(json.dumps({"unrelated": "value"}))
        codes = _codes(warnings)
        assert codes.count(WarningCode.GRAPH_SECTION_MISSING) == 2
        assert graph.is_empty

    def test_section_value_not_list_falls_back_to_empty(self):
        parser = CandidateGraphParser()
        graph, warnings = parser.parse(json.dumps({"vertices": "oops", "edges": []}))
        # Non-list section is coerced to empty; no warning about it (the collector
        # sees an empty list and has nothing to complain about).
        assert graph.vertices == []
        assert graph.edges == []
        # But GRAPH_SECTION_MISSING is not emitted because the key was present.
        assert WarningCode.GRAPH_SECTION_MISSING not in _codes(warnings)


# ------------------------------------------------------- Format 2: fenced JSON
class TestFencedJson:
    def test_json_fence_with_language_tag(self):
        parser = CandidateGraphParser()
        raw = '```json\n{"vertices": [{"type": "vertex", "label": "person", "properties": {}}], "edges": []}\n```'
        graph, warnings = parser.parse(raw)
        assert warnings == []
        assert len(graph.vertices) == 1

    def test_plain_fence_without_language_tag(self):
        parser = CandidateGraphParser()
        raw = '```\n{"vertices": [], "edges": []}\n```'
        graph, warnings = parser.parse(raw)
        assert warnings == []
        assert graph.is_empty

    def test_uppercase_fence_language_tag(self):
        parser = CandidateGraphParser()
        raw = '```JSON\n{"vertices": [], "edges": []}\n```'
        graph, warnings = parser.parse(raw)
        assert warnings == []


# ------------------------------------------------- Format 3: JSON with prose
class TestJsonWithProse:
    def test_prose_before_and_after_json(self):
        parser = CandidateGraphParser()
        raw = (
            "Based on the input text, here is the extracted graph:\n"
            '{"vertices": [{"type": "vertex", "label": "person", "properties": {"name": "Tom"}}], "edges": []}\n'
            "Note: some entities may be uncertain."
        )
        graph, warnings = parser.parse(raw)
        assert warnings == []
        assert graph.vertices[0]["label"] == "person"

    def test_only_prose_no_json_emits_json_not_found(self):
        parser = CandidateGraphParser()
        graph, warnings = parser.parse("This chunk does not contain any structured output.")
        assert _codes(warnings) == [WarningCode.JSON_NOT_FOUND]
        assert graph.is_empty

    def test_empty_string_emits_json_not_found(self):
        parser = CandidateGraphParser()
        graph, warnings = parser.parse("")
        assert _codes(warnings) == [WarningCode.JSON_NOT_FOUND]
        assert graph.is_empty

    def test_whitespace_only_after_fence_stripping_emits_json_not_found(self):
        parser = CandidateGraphParser()
        graph, warnings = parser.parse("```\n```\n")
        assert _codes(warnings) == [WarningCode.JSON_NOT_FOUND]


# ------------------------------------------------------ Format 4: flat array
class TestFlatArray:
    def test_flat_array_partitions_by_type(self):
        parser = CandidateGraphParser()
        raw = json.dumps(
            [
                {"type": "vertex", "label": "person", "properties": {"name": "Tom"}},
                {"type": "edge", "label": "acted_in", "outV": "v1", "inV": "v2", "properties": {}},
                {"type": "vertex", "label": "movie", "properties": {"title": "FG"}},
            ]
        )
        graph, warnings = parser.parse(raw)
        assert warnings == []
        assert len(graph.vertices) == 2
        assert len(graph.edges) == 1

    def test_flat_array_item_without_type_is_dropped(self):
        parser = CandidateGraphParser()
        raw = json.dumps(
            [
                {"label": "person", "properties": {}},  # no type
                {"type": "vertex", "label": "movie", "properties": {}},
            ]
        )
        graph, warnings = parser.parse(raw)
        assert _codes(warnings) == [WarningCode.ITEM_TYPE_MISMATCH]
        assert warnings[0].context == {"label": "person"}
        assert len(graph.vertices) == 1
        assert graph.vertices[0]["label"] == "movie"

    def test_flat_array_with_non_dict_items(self):
        parser = CandidateGraphParser()
        raw = json.dumps(
            [
                "not a dict",
                42,
                {"type": "vertex", "label": "person", "properties": {}},
            ]
        )
        graph, warnings = parser.parse(raw)
        codes = _codes(warnings)
        assert codes.count(WarningCode.ITEM_NOT_OBJECT) == 2
        assert len(graph.vertices) == 1


# ------------------------------------------------------ Broken JSON handling
class TestBrokenJson:
    def test_truncated_json_emits_json_decode_failed(self):
        parser = CandidateGraphParser()
        raw = '{"vertices": [{"label": "person", "properties":'
        graph, warnings = parser.parse(raw)
        assert _codes(warnings) == [WarningCode.JSON_DECODE_FAILED]
        assert graph.is_empty

    def test_scalar_payload_emits_section_missing_and_empties(self):
        """`42` parses cleanly but is not a graph — treat as section-missing."""
        parser = CandidateGraphParser()
        graph, warnings = parser.parse("42")
        assert _codes(warnings) == [WarningCode.GRAPH_SECTION_MISSING]
        assert graph.is_empty


# ------------------------------- Explicit type conflict inside grouped format
class TestGroupedItemTypeConflict:
    def test_edge_typed_item_inside_vertices_array_is_dropped(self):
        parser = CandidateGraphParser()
        raw = json.dumps(
            {
                "vertices": [
                    {"type": "edge", "label": "acted_in", "properties": {}},
                    {"type": "vertex", "label": "person", "properties": {}},
                ],
                "edges": [],
            }
        )
        graph, warnings = parser.parse(raw)
        assert _codes(warnings) == [WarningCode.ITEM_TYPE_MISMATCH]
        assert warnings[0].label == "acted_in"
        assert len(graph.vertices) == 1
        assert graph.vertices[0]["label"] == "person"

    def test_vertex_typed_item_inside_edges_array_is_dropped(self):
        parser = CandidateGraphParser()
        raw = json.dumps(
            {
                "vertices": [],
                "edges": [
                    {"type": "vertex", "label": "person", "properties": {}},
                    {"type": "edge", "label": "acted_in", "outV": "v1", "inV": "v2", "properties": {}},
                ],
            }
        )
        graph, warnings = parser.parse(raw)
        assert _codes(warnings) == [WarningCode.ITEM_TYPE_MISMATCH]
        assert warnings[0].label == "person"
        assert len(graph.edges) == 1

    def test_non_dict_item_in_grouped_section_emits_item_not_object(self):
        parser = CandidateGraphParser()
        raw = json.dumps(
            {
                "vertices": ["not-a-dict"],
                "edges": [{"type": "edge", "label": "acted_in", "outV": "v1", "inV": "v2", "properties": {}}],
            }
        )
        graph, warnings = parser.parse(raw)
        assert _codes(warnings) == [WarningCode.ITEM_NOT_OBJECT]
        assert len(graph.vertices) == 0
        assert len(graph.edges) == 1


# --------------------------------------------------------------- chunk_id
class TestChunkIdPropagation:
    def test_warning_carries_chunk_id(self):
        parser = CandidateGraphParser()
        _, warnings = parser.parse("no json here", chunk_id=7)
        assert warnings[0].chunk_id == 7

    def test_omitted_chunk_id_stays_none(self):
        parser = CandidateGraphParser()
        _, warnings = parser.parse("no json here")
        assert warnings[0].chunk_id is None


# --------------------------------------------------- item type normalization
class TestItemTypeNormalization:
    def test_grouped_vertex_without_type_is_typed_by_the_parser(self):
        """The collector fills in item['type'] so downstream never needs the check."""
        parser = CandidateGraphParser()
        raw = json.dumps(
            {
                "vertices": [{"label": "person", "properties": {"name": "Tom"}}],
                "edges": [],
            }
        )
        graph, warnings = parser.parse(raw)
        assert warnings == []
        assert graph.vertices[0]["type"] == "vertex"

    def test_original_item_is_not_mutated(self):
        parser = CandidateGraphParser()
        original = {"label": "person", "properties": {"name": "Tom"}}
        raw = json.dumps({"vertices": [original], "edges": []})
        graph, _ = parser.parse(raw)
        # graph.vertices[0] is a copy — modifying it should not affect any
        # dict that the caller may still be referencing.
        assert "type" not in original  # 'original' was the pre-JSON literal
        assert graph.vertices[0]["type"] == "vertex"
