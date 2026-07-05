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

import pytest

from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced import (
    PENDING_IN_KEY,
    PENDING_OUT_KEY,
    CandidateGraph,
    CandidateGraphParser,
    DocumentGraphAssembler,
    GraphSchemaIndex,
    NormalizedChunkGraph,
    SchemaAwareNormalizer,
    StructuredWarning,
    WarningCode,
)

pytestmark = pytest.mark.contract


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


# ==============================================================================
# SchemaAwareNormalizer
# ==============================================================================


def _schema() -> dict:
    """Minimal schema with vertex-label ids (mirrors HugeGraph server output)."""
    return {
        "propertykeys": [
            {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
            {"name": "title", "data_type": "TEXT", "cardinality": "SINGLE"},
            {"name": "year", "data_type": "INT", "cardinality": "SINGLE"},
            {"name": "role", "data_type": "TEXT", "cardinality": "SINGLE"},
        ],
        "vertexlabels": [
            {
                "id": 1,
                "name": "person",
                "properties": ["name"],
                "primary_keys": ["name"],
                "nullable_keys": [],
                "id_strategy": "PRIMARY_KEY",
            },
            {
                "id": 2,
                "name": "movie",
                "properties": ["title", "year"],
                "primary_keys": ["title"],
                "nullable_keys": ["year"],
                "id_strategy": "PRIMARY_KEY",
            },
        ],
        "edgelabels": [
            {
                "name": "acted_in",
                "source_label": "person",
                "target_label": "movie",
                "properties": ["role"],
            }
        ],
    }


def _normalizer() -> SchemaAwareNormalizer:
    return SchemaAwareNormalizer(GraphSchemaIndex(_schema()))


# --------------------------------------------------------- vertex: label
class TestNormalizerVertexLabel:
    def test_valid_vertex_produces_canonical_id(self):
        norm = _normalizer()
        candidate = CandidateGraph(vertices=[{"type": "vertex", "label": "person", "properties": {"name": "Tom"}}])
        graph, warnings = norm.normalize(candidate)
        assert warnings == []
        assert graph.vertices == [{"type": "vertex", "label": "person", "properties": {"name": "Tom"}, "id": "1:Tom"}]

    def test_unknown_label_drops_vertex(self):
        norm = _normalizer()
        candidate = CandidateGraph(vertices=[{"type": "vertex", "label": "robot", "properties": {"name": "R2D2"}}])
        graph, warnings = norm.normalize(candidate)
        assert _codes(warnings) == [WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA]
        assert graph.vertices == []

    def test_missing_label_drops_vertex(self):
        norm = _normalizer()
        candidate = CandidateGraph(vertices=[{"type": "vertex", "properties": {"name": "Tom"}}])
        graph, warnings = norm.normalize(candidate)
        assert _codes(warnings) == [WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA]
        assert graph.vertices == []


# --------------------------------------------- vertex: property filter/coerce
class TestNormalizerVertexProperties:
    def test_property_not_in_schema_is_dropped(self):
        norm = _normalizer()
        candidate = CandidateGraph(
            vertices=[
                {
                    "type": "vertex",
                    "label": "person",
                    "properties": {"name": "Tom", "planet": "Earth"},
                }
            ]
        )
        graph, warnings = norm.normalize(candidate)
        assert _codes(warnings) == [WarningCode.PROPERTY_NOT_IN_SCHEMA]
        assert graph.vertices[0]["properties"] == {"name": "Tom"}

    def test_string_year_coerced_to_int_with_soft_warning(self):
        norm = _normalizer()
        candidate = CandidateGraph(
            vertices=[{"type": "vertex", "label": "movie", "properties": {"title": "FG", "year": "1994"}}]
        )
        graph, warnings = norm.normalize(candidate)
        assert _codes(warnings) == [WarningCode.PROPERTY_COERCED]
        assert graph.vertices[0]["properties"] == {"title": "FG", "year": 1994}

    def test_non_pk_property_coercion_failure_drops_only_that_property(self):
        norm = _normalizer()
        candidate = CandidateGraph(
            vertices=[{"type": "vertex", "label": "movie", "properties": {"title": "FG", "year": "N/A"}}]
        )
        graph, warnings = norm.normalize(candidate)
        codes = _codes(warnings)
        assert WarningCode.PROPERTY_COERCION_FAILED in codes
        # The vertex survives without the broken property.
        assert graph.vertices[0]["properties"] == {"title": "FG"}

    def test_pk_property_coercion_failure_drops_the_whole_vertex(self):
        norm = _normalizer()
        # `title` is a PK (TEXT) — a bool value fails the TEXT coercion? No,
        # TEXT accepts anything via str(). Use INT PK — build a schema where
        # the PK is INT.
        schema = _schema()
        # Change movie's PK to year (INT).
        schema["vertexlabels"][1]["primary_keys"] = ["year"]
        idx = GraphSchemaIndex(schema)
        norm = SchemaAwareNormalizer(idx)
        candidate = CandidateGraph(
            vertices=[{"type": "vertex", "label": "movie", "properties": {"title": "FG", "year": "N/A"}}]
        )
        graph, warnings = norm.normalize(candidate)
        assert WarningCode.VERTEX_PRIMARY_KEY_INVALID in _codes(warnings)
        assert graph.vertices == []


# ------------------------------------------------ vertex: primary key checks
class TestNormalizerVertexPrimaryKey:
    def test_missing_pk_drops_vertex(self):
        norm = _normalizer()
        candidate = CandidateGraph(vertices=[{"type": "vertex", "label": "person", "properties": {}}])
        graph, warnings = norm.normalize(candidate)
        assert _codes(warnings) == [WarningCode.VERTEX_PRIMARY_KEY_MISSING]
        assert graph.vertices == []

    def test_empty_string_pk_drops_vertex(self):
        norm = _normalizer()
        candidate = CandidateGraph(vertices=[{"type": "vertex", "label": "person", "properties": {"name": ""}}])
        graph, warnings = norm.normalize(candidate)
        assert _codes(warnings) == [WarningCode.VERTEX_PRIMARY_KEY_MISSING]
        assert graph.vertices == []


# ---------------------------------------------------- vertex: id and alias
class TestNormalizerVertexIdAndAlias:
    def test_llm_original_id_becomes_alias(self):
        norm = _normalizer()
        candidate = CandidateGraph(
            vertices=[{"type": "vertex", "id": "v1", "label": "person", "properties": {"name": "Tom"}}]
        )
        graph, warnings = norm.normalize(candidate)
        assert _codes(warnings) == [WarningCode.VERTEX_ALIAS_RECORDED]
        # Alias table contains both the raw-id-to-canonical mapping and the
        # identity mapping for the canonical id itself.
        assert graph.aliases[("person", "v1")] == "1:Tom"
        assert graph.aliases[("person", "1:Tom")] == "1:Tom"

    def test_llm_original_id_matching_canonical_produces_no_alias_warning(self):
        norm = _normalizer()
        candidate = CandidateGraph(
            vertices=[
                {
                    "type": "vertex",
                    "id": "1:Tom",
                    "label": "person",
                    "properties": {"name": "Tom"},
                }
            ]
        )
        graph, warnings = norm.normalize(candidate)
        assert _codes(warnings) == []
        assert graph.aliases[("person", "1:Tom")] == "1:Tom"


# ----------------------------------------------------------- edge: label
class TestNormalizerEdgeLabel:
    def test_unknown_edge_label_drops_edge(self):
        norm = _normalizer()
        candidate = CandidateGraph(edges=[{"type": "edge", "label": "directed", "properties": {}}])
        graph, warnings = norm.normalize(candidate)
        assert _codes(warnings) == [WarningCode.EDGE_LABEL_NOT_IN_SCHEMA]
        assert graph.edges == []


# ----------------------------------------------------- edge: property filter
class TestNormalizerEdgeProperties:
    def test_edge_property_not_in_schema_is_dropped(self):
        norm = _normalizer()
        candidate = CandidateGraph(
            vertices=[
                {"type": "vertex", "label": "person", "properties": {"name": "Tom"}},
                {"type": "vertex", "label": "movie", "properties": {"title": "FG"}},
            ],
            edges=[
                {
                    "type": "edge",
                    "label": "acted_in",
                    "source": {"label": "person", "properties": {"name": "Tom"}},
                    "target": {"label": "movie", "properties": {"title": "FG"}},
                    "properties": {"role": "Forrest", "budget": 999},
                }
            ],
        )
        graph, warnings = norm.normalize(candidate)
        assert WarningCode.PROPERTY_NOT_IN_SCHEMA in _codes(warnings)
        assert graph.edges[0]["properties"] == {"role": "Forrest"}


# --------------------------------------------------- edge: endpoint direction
class TestNormalizerEdgeEndpointCompatibility:
    def test_reversed_endpoints_drop_edge(self):
        norm = _normalizer()
        candidate = CandidateGraph(
            edges=[
                {
                    "type": "edge",
                    "label": "acted_in",
                    "outVLabel": "movie",
                    "inVLabel": "person",
                    "outV": "2:FG",
                    "inV": "1:Tom",
                    "properties": {},
                }
            ]
        )
        graph, warnings = norm.normalize(candidate)
        assert _codes(warnings) == [WarningCode.EDGE_ENDPOINT_MISMATCH]
        assert graph.edges == []

    def test_missing_endpoint_labels_are_filled_from_schema(self):
        """LLM sometimes omits redundant outVLabel/inVLabel; use schema."""
        norm = _normalizer()
        candidate = CandidateGraph(
            vertices=[
                {"type": "vertex", "label": "person", "properties": {"name": "Tom"}},
                {"type": "vertex", "label": "movie", "properties": {"title": "FG"}},
            ],
            edges=[
                {
                    "type": "edge",
                    "label": "acted_in",
                    "outV": "1:Tom",
                    "inV": "2:FG",
                    "properties": {},
                }
            ],
        )
        graph, warnings = norm.normalize(candidate)
        assert warnings == []
        assert graph.edges[0]["outVLabel"] == "person"
        assert graph.edges[0]["inVLabel"] == "movie"


# --------------------------------------------------- edge: endpoint resolution
class TestNormalizerEdgeEndpointResolution:
    def test_legacy_source_target_resolves_to_canonical(self):
        norm = _normalizer()
        candidate = CandidateGraph(
            vertices=[
                {"type": "vertex", "label": "person", "properties": {"name": "Tom"}},
                {"type": "vertex", "label": "movie", "properties": {"title": "FG"}},
            ],
            edges=[
                {
                    "type": "edge",
                    "label": "acted_in",
                    "source": {"label": "person", "properties": {"name": "Tom"}},
                    "target": {"label": "movie", "properties": {"title": "FG"}},
                    "properties": {"role": "Forrest"},
                }
            ],
        )
        graph, warnings = norm.normalize(candidate)
        assert warnings == []
        assert graph.edges[0]["outV"] == "1:Tom"
        assert graph.edges[0]["inV"] == "2:FG"
        assert PENDING_OUT_KEY not in graph.edges[0]
        assert PENDING_IN_KEY not in graph.edges[0]

    def test_llm_raw_id_resolves_via_chunk_aliases(self):
        norm = _normalizer()
        candidate = CandidateGraph(
            vertices=[
                {"type": "vertex", "id": "v1", "label": "person", "properties": {"name": "Tom"}},
                {"type": "vertex", "id": "v2", "label": "movie", "properties": {"title": "FG"}},
            ],
            edges=[
                {
                    "type": "edge",
                    "label": "acted_in",
                    "outV": "v1",
                    "inV": "v2",
                    "outVLabel": "person",
                    "inVLabel": "movie",
                    "properties": {},
                }
            ],
        )
        graph, warnings = norm.normalize(candidate)
        assert not any(w.code is WarningCode.ENDPOINT_PENDING_REPAIR for w in warnings)
        assert graph.edges[0]["outV"] == "1:Tom"
        assert graph.edges[0]["inV"] == "2:FG"

    def test_unresolvable_out_endpoint_marks_pending(self):
        """LLM references an id that has no vertex in this chunk."""
        norm = _normalizer()
        candidate = CandidateGraph(
            vertices=[
                {"type": "vertex", "id": "v2", "label": "movie", "properties": {"title": "FG"}},
            ],
            edges=[
                {
                    "type": "edge",
                    "label": "acted_in",
                    "outV": "v99",
                    "inV": "v2",
                    "outVLabel": "person",
                    "inVLabel": "movie",
                    "properties": {},
                }
            ],
        )
        graph, warnings = norm.normalize(candidate)
        assert WarningCode.ENDPOINT_PENDING_REPAIR in _codes(warnings)
        edge = graph.edges[0]
        assert edge.get("outV") is None
        assert edge[PENDING_OUT_KEY] == {"original_id": "v99"}
        assert edge["inV"] == "2:FG"


# --------------------------------------------------------- integration
class TestNormalizerIntegration:
    def test_end_to_end_document_flow_smoke(self):
        """Parse + normalize round-trip on a mixed-format grouped payload."""
        parser = CandidateGraphParser()
        norm = _normalizer()
        raw = json.dumps(
            {
                "vertices": [
                    {
                        "type": "vertex",
                        "id": "v1",
                        "label": "person",
                        "properties": {"name": "Tom Hanks"},
                    },
                    {
                        "type": "vertex",
                        "id": "v2",
                        "label": "movie",
                        "properties": {"title": "Forrest Gump", "year": "1994"},
                    },
                ],
                "edges": [
                    {
                        "type": "edge",
                        "label": "acted_in",
                        "outV": "v1",
                        "inV": "v2",
                        "outVLabel": "person",
                        "inVLabel": "movie",
                        "properties": {"role": "Forrest"},
                    }
                ],
            }
        )
        candidate, parser_warnings = parser.parse(raw)
        assert parser_warnings == []
        graph, norm_warnings = norm.normalize(candidate, chunk_id=0)
        codes = _codes(norm_warnings)
        # Two alias records (one per vertex) + one soft coerce for year.
        assert codes.count(WarningCode.VERTEX_ALIAS_RECORDED) == 2
        assert codes.count(WarningCode.PROPERTY_COERCED) == 1
        assert graph.vertices[0]["id"] == "1:Tom Hanks"
        assert graph.vertices[1]["id"] == "2:Forrest Gump"
        assert graph.vertices[1]["properties"]["year"] == 1994
        assert graph.edges[0]["outV"] == "1:Tom Hanks"
        assert graph.edges[0]["inV"] == "2:Forrest Gump"

    def test_chunk_id_flows_into_all_normalizer_warnings(self):
        norm = _normalizer()
        candidate = CandidateGraph(vertices=[{"type": "vertex", "label": "robot", "properties": {}}])
        _, warnings = norm.normalize(candidate, chunk_id=5)
        assert warnings[0].chunk_id == 5


# ==============================================================================
# DocumentGraphAssembler
# ==============================================================================


def _assembler() -> DocumentGraphAssembler:
    return DocumentGraphAssembler(GraphSchemaIndex(_schema()))


def _v(label: str, vid: str, **props) -> dict:
    return {"type": "vertex", "label": label, "id": vid, "properties": dict(props)}


def _e_resolved(label: str, out_v: str, in_v: str, out_label: str, in_label: str, **props) -> dict:
    return {
        "type": "edge",
        "label": label,
        "outV": out_v,
        "inV": in_v,
        "outVLabel": out_label,
        "inVLabel": in_label,
        "properties": dict(props),
    }


# ---------------------------------------------------------- vertex merge
class TestAssemblerVertexMerge:
    def test_same_key_across_chunks_merges_and_emits_warning(self):
        asm = _assembler()
        chunk_a = NormalizedChunkGraph(vertices=[_v("person", "1:Tom", name="Tom")])
        chunk_b = NormalizedChunkGraph(vertices=[_v("person", "1:Tom", name="Tom")])
        graph, warnings = asm.assemble([chunk_a, chunk_b])
        assert len(graph.vertices) == 1
        assert graph.pre_merge_vertex_count == 2
        codes = _codes(warnings)
        assert codes.count(WarningCode.DUPLICATE_VERTEX_MERGED) == 1

    def test_property_conflict_first_wins(self):
        asm = _assembler()
        chunk_a = NormalizedChunkGraph(vertices=[_v("movie", "2:FG", title="FG", year=1994)])
        chunk_b = NormalizedChunkGraph(vertices=[_v("movie", "2:FG", title="FG", year=1993)])
        graph, warnings = asm.assemble([chunk_a, chunk_b])
        assert graph.vertices[0]["properties"]["year"] == 1994
        codes = _codes(warnings)
        assert WarningCode.PROPERTY_CONFLICT in codes
        conflict = next(w for w in warnings if w.code is WarningCode.PROPERTY_CONFLICT)
        assert conflict.context == {"property": "year", "kept": 1994, "discarded": 1993}

    def test_missing_property_completed_from_later_chunk(self):
        asm = _assembler()
        chunk_a = NormalizedChunkGraph(vertices=[_v("movie", "2:FG", title="FG")])
        chunk_b = NormalizedChunkGraph(vertices=[_v("movie", "2:FG", title="FG", year=1994)])
        graph, _ = asm.assemble([chunk_a, chunk_b])
        assert graph.vertices[0]["properties"] == {"title": "FG", "year": 1994}

    def test_different_keys_stay_separate(self):
        asm = _assembler()
        chunk_a = NormalizedChunkGraph(vertices=[_v("person", "1:Tom", name="Tom")])
        chunk_b = NormalizedChunkGraph(vertices=[_v("person", "1:Alice", name="Alice")])
        graph, warnings = asm.assemble([chunk_a, chunk_b])
        assert len(graph.vertices) == 2
        assert WarningCode.DUPLICATE_VERTEX_MERGED not in _codes(warnings)

    def test_output_order_preserves_first_appearance(self):
        asm = _assembler()
        chunk_a = NormalizedChunkGraph(
            vertices=[
                _v("person", "1:Tom", name="Tom"),
                _v("movie", "2:FG", title="FG"),
            ]
        )
        chunk_b = NormalizedChunkGraph(
            vertices=[
                _v("movie", "2:FG", title="FG"),
                _v("person", "1:Tom", name="Tom"),
            ]
        )
        graph, _ = asm.assemble([chunk_a, chunk_b])
        assert [v["id"] for v in graph.vertices] == ["1:Tom", "2:FG"]

    def test_vertex_without_id_is_kept_verbatim(self):
        asm = _assembler()
        vertex_no_id = {"type": "vertex", "label": "person", "properties": {"name": "Anon"}}
        chunk = NormalizedChunkGraph(vertices=[vertex_no_id, vertex_no_id])
        graph, warnings = asm.assemble([chunk])
        # Both occurrences kept — no merge (no way to identify).
        assert len(graph.vertices) == 2
        assert WarningCode.DUPLICATE_VERTEX_MERGED not in _codes(warnings)


# --------------------------------------------------------- endpoint repair
class TestAssemblerEndpointRepair:
    def test_pending_out_endpoint_repaired_via_cross_chunk_alias(self):
        """Chunk A has the vertex + alias; chunk B has the edge referencing the raw id."""
        asm = _assembler()
        chunk_a = NormalizedChunkGraph(
            vertices=[_v("person", "1:Tom", name="Tom"), _v("movie", "2:FG", title="FG")],
            aliases={("person", "v1"): "1:Tom", ("movie", "2:FG"): "2:FG", ("person", "1:Tom"): "1:Tom"},
        )
        edge = {
            "type": "edge",
            "label": "acted_in",
            "inV": "2:FG",
            "inVLabel": "movie",
            "outVLabel": "person",
            "properties": {},
            PENDING_OUT_KEY: {"original_id": "v1"},
        }
        chunk_b = NormalizedChunkGraph(edges=[edge])
        graph, warnings = asm.assemble([chunk_a, chunk_b])
        assert graph.endpoint_repair_count == 1
        assert graph.edges[0]["outV"] == "1:Tom"
        # No leftover pending marker.
        assert PENDING_OUT_KEY not in graph.edges[0]
        # Also no ENDPOINT_UNRESOLVED / AMBIGUOUS.
        codes = _codes(warnings)
        assert WarningCode.ENDPOINT_UNRESOLVED not in codes
        assert WarningCode.ENDPOINT_AMBIGUOUS not in codes

    def test_pending_endpoint_with_no_alias_is_dropped_as_unresolved(self):
        asm = _assembler()
        edge = {
            "type": "edge",
            "label": "acted_in",
            "inV": "2:FG",
            "inVLabel": "movie",
            "outVLabel": "person",
            "properties": {},
            PENDING_OUT_KEY: {"original_id": "ghost"},
        }
        chunk_b = NormalizedChunkGraph(edges=[edge])
        graph, warnings = asm.assemble([chunk_b])
        assert graph.edges == []
        assert WarningCode.ENDPOINT_UNRESOLVED in _codes(warnings)

    def test_ambiguous_alias_yields_endpoint_ambiguous(self):
        """The same LLM raw id maps to different canonical ids across chunks."""
        asm = _assembler()
        chunk_a = NormalizedChunkGraph(aliases={("person", "v1"): "1:Tom"})
        chunk_b = NormalizedChunkGraph(aliases={("person", "v1"): "1:Alice"})
        edge = {
            "type": "edge",
            "label": "acted_in",
            "inV": "2:FG",
            "inVLabel": "movie",
            "outVLabel": "person",
            "properties": {},
            PENDING_OUT_KEY: {"original_id": "v1"},
        }
        chunk_c = NormalizedChunkGraph(edges=[edge])
        graph, warnings = asm.assemble([chunk_a, chunk_b, chunk_c])
        assert graph.edges == []
        assert WarningCode.ENDPOINT_AMBIGUOUS in _codes(warnings)
        assert WarningCode.ENDPOINT_UNRESOLVED not in _codes(warnings)

    def test_edge_already_resolved_at_chunk_level_passes_through(self):
        asm = _assembler()
        chunk = NormalizedChunkGraph(
            vertices=[_v("person", "1:Tom", name="Tom"), _v("movie", "2:FG", title="FG")],
            edges=[_e_resolved("acted_in", "1:Tom", "2:FG", "person", "movie", role="Forrest")],
        )
        graph, warnings = asm.assemble([chunk])
        assert graph.endpoint_repair_count == 0
        assert len(graph.edges) == 1
        assert graph.edges[0]["outV"] == "1:Tom"


# --------------------------------------------------------------- edge dedup
class TestAssemblerEdgeDedupe:
    def test_identical_edges_deduped(self):
        asm = _assembler()
        edge_1 = _e_resolved("acted_in", "1:Tom", "2:FG", "person", "movie", role="Forrest")
        edge_2 = _e_resolved("acted_in", "1:Tom", "2:FG", "person", "movie", role="Forrest")
        chunk = NormalizedChunkGraph(
            vertices=[_v("person", "1:Tom", name="Tom"), _v("movie", "2:FG", title="FG")],
            edges=[edge_1, edge_2],
        )
        graph, warnings = asm.assemble([chunk])
        assert len(graph.edges) == 1
        assert graph.pre_merge_edge_count == 2
        assert WarningCode.DUPLICATE_EDGE_MERGED in _codes(warnings)

    def test_same_endpoints_different_properties_are_both_kept(self):
        """Different property signatures represent distinct facts — don't merge."""
        asm = _assembler()
        edge_1 = _e_resolved("acted_in", "1:Tom", "2:FG", "person", "movie", role="Forrest")
        edge_2 = _e_resolved("acted_in", "1:Tom", "2:FG", "person", "movie", role="Narrator")
        chunk = NormalizedChunkGraph(
            vertices=[_v("person", "1:Tom", name="Tom"), _v("movie", "2:FG", title="FG")],
            edges=[edge_1, edge_2],
        )
        graph, warnings = asm.assemble([chunk])
        assert len(graph.edges) == 2
        assert WarningCode.DUPLICATE_EDGE_MERGED not in _codes(warnings)

    def test_dedupe_handles_nested_list_property_values(self):
        """LIST/SET cardinality property values (unhashable as tuples) still dedupe."""
        asm = _assembler()
        edge = {
            "type": "edge",
            "label": "acted_in",
            "outV": "1:Tom",
            "inV": "2:FG",
            "outVLabel": "person",
            "inVLabel": "movie",
            "properties": {"tags": ["lead", "drama"]},
        }
        chunk = NormalizedChunkGraph(edges=[dict(edge), dict(edge)])
        graph, warnings = asm.assemble([chunk])
        assert len(graph.edges) == 1
        assert WarningCode.DUPLICATE_EDGE_MERGED in _codes(warnings)


# --------------------------------------------------------------- integration
class TestAssemblerIntegration:
    def test_multi_chunk_end_to_end(self):
        """Two chunks reference the same entity — merged, deduped, endpoint repaired across chunks."""
        asm = _assembler()
        # Chunk 0: Tom + Forrest Gump + acted_in edge (fully local).
        chunk_0 = NormalizedChunkGraph(
            vertices=[_v("person", "1:Tom", name="Tom"), _v("movie", "2:FG", title="FG")],
            edges=[_e_resolved("acted_in", "1:Tom", "2:FG", "person", "movie", role="Forrest")],
        )
        # Chunk 1: Duplicate Tom + duplicate edge with same shape (should merge/dedupe).
        chunk_1 = NormalizedChunkGraph(
            vertices=[_v("person", "1:Tom", name="Tom"), _v("movie", "2:FG", title="FG")],
            edges=[_e_resolved("acted_in", "1:Tom", "2:FG", "person", "movie", role="Forrest")],
        )
        graph, warnings = asm.assemble([chunk_0, chunk_1])
        assert len(graph.vertices) == 2
        assert len(graph.edges) == 1
        assert graph.pre_merge_vertex_count == 4
        assert graph.pre_merge_edge_count == 2
        codes = _codes(warnings)
        assert codes.count(WarningCode.DUPLICATE_VERTEX_MERGED) == 2
        assert codes.count(WarningCode.DUPLICATE_EDGE_MERGED) == 1

    def test_full_pipeline_parser_normalizer_assembler(self):
        """Parse two chunks' raw output, normalize, assemble; verify the whole loop."""
        parser = CandidateGraphParser()
        norm = _normalizer()
        asm = _assembler()

        chunk_0_raw = json.dumps(
            {
                "vertices": [
                    {"type": "vertex", "id": "v1", "label": "person", "properties": {"name": "Tom Hanks"}},
                    {
                        "type": "vertex",
                        "id": "v2",
                        "label": "movie",
                        "properties": {"title": "Forrest Gump", "year": "1994"},
                    },
                ],
                "edges": [
                    {
                        "type": "edge",
                        "label": "acted_in",
                        "outV": "v1",
                        "inV": "v2",
                        "outVLabel": "person",
                        "inVLabel": "movie",
                        "properties": {"role": "Forrest"},
                    }
                ],
            }
        )
        chunk_1_raw = json.dumps(
            {
                "vertices": [{"type": "vertex", "id": "u1", "label": "person", "properties": {"name": "Tom Hanks"}}],
                "edges": [
                    {
                        "type": "edge",
                        "label": "acted_in",
                        "source": {"label": "person", "properties": {"name": "Tom Hanks"}},
                        "target": {"label": "movie", "properties": {"title": "Forrest Gump"}},
                        "properties": {},
                    }
                ],
            }
        )

        chunk_graphs = []
        for i, raw in enumerate([chunk_0_raw, chunk_1_raw]):
            cand, _ = parser.parse(raw, chunk_id=i)
            ng, _ = norm.normalize(cand, chunk_id=i)
            chunk_graphs.append(ng)

        doc, warnings = asm.assemble(chunk_graphs)
        # Two unique vertices (Tom + Forrest Gump); one unique edge shape after dedup
        # (chunk_0 has role=Forrest, chunk_1 has empty properties → both kept as
        # distinct signatures — that matches the "different property sig, keep both"
        # rule).
        assert len(doc.vertices) == 2
        assert len(doc.edges) == 2
        # Vertex Tom appeared twice → 1 merge.
        codes = _codes(warnings)
        assert codes.count(WarningCode.DUPLICATE_VERTEX_MERGED) == 1
