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
    PENDING_IN_KEY,
    PENDING_OUT_KEY,
    CandidateGraph,
    CandidateGraphParser,
    GraphSchemaIndex,
    SchemaAwareNormalizer,
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
