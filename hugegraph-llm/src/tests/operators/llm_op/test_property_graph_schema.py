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

"""Unit tests for the schema-aware graph extraction index (Issue #74)."""

from __future__ import annotations

import json

import pytest

from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced import GraphSchemaIndex


def _schema_with_ids() -> dict:
    """A minimal but complete schema with vertex-label ids populated.

    Mirrors what SchemaManager returns from a live HugeGraph server (the ``id``
    field is required for baseline canonical id generation).
    """
    return {
        "propertykeys": [
            {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
            {"name": "title", "data_type": "TEXT", "cardinality": "SINGLE"},
            {"name": "year", "data_type": "INT", "cardinality": "SINGLE"},
            {"name": "rating", "data_type": "FLOAT", "cardinality": "SINGLE"},
            {"name": "is_lead", "data_type": "BOOLEAN", "cardinality": "SINGLE"},
            {"name": "released_on", "data_type": "DATE", "cardinality": "SINGLE"},
            {"name": "aliases", "data_type": "TEXT", "cardinality": "LIST"},
            {"name": "genres", "data_type": "TEXT", "cardinality": "SET"},
            {"name": "role", "data_type": "TEXT", "cardinality": "SINGLE"},
        ],
        "vertexlabels": [
            {
                "id": 1,
                "name": "person",
                "properties": ["name", "aliases"],
                "primary_keys": ["name"],
                "nullable_keys": ["aliases"],
                "id_strategy": "PRIMARY_KEY",
            },
            {
                "id": 2,
                "name": "movie",
                "properties": ["title", "year", "rating", "released_on", "genres"],
                "primary_keys": ["title", "year"],
                "nullable_keys": ["rating", "released_on", "genres"],
                "id_strategy": "PRIMARY_KEY",
            },
        ],
        "edgelabels": [
            {
                "name": "acted_in",
                "source_label": "person",
                "target_label": "movie",
                "properties": ["role", "is_lead"],
            }
        ],
    }


def _schema_without_ids() -> dict:
    """A schema that mimics an inline user dict (no vertex-label ``id``)."""
    schema = _schema_with_ids()
    for v in schema["vertexlabels"]:
        v.pop("id", None)
    return schema


# --------------------------------------------------------------------------- constructor
class TestConstructor:
    def test_accepts_dict_schema(self):
        idx = GraphSchemaIndex(_schema_with_ids())
        assert idx.is_vertex_label("person")
        assert idx.is_edge_label("acted_in")

    def test_accepts_json_string_schema(self):
        idx = GraphSchemaIndex.from_schema(json.dumps(_schema_with_ids()))
        assert idx.is_vertex_label("person")

    def test_rejects_non_mapping_input(self):
        with pytest.raises(TypeError):
            GraphSchemaIndex(["not", "a", "dict"])  # type: ignore[arg-type]

    def test_rejects_schema_missing_required_sections(self):
        with pytest.raises(ValueError):
            GraphSchemaIndex({"vertexlabels": []})

    def test_rejects_named_graph_string(self):
        with pytest.raises(ValueError):
            GraphSchemaIndex.from_schema("hugegraph")

    def test_rejects_unparseable_json_string(self):
        with pytest.raises(ValueError):
            GraphSchemaIndex.from_schema("{not valid json")


# ------------------------------------------------------------------------------- labels
class TestLabels:
    def setup_method(self):
        self.idx = GraphSchemaIndex(_schema_with_ids())

    def test_vertex_label_lookup(self):
        assert self.idx.is_vertex_label("person")
        assert not self.idx.is_vertex_label("robot")
        assert self.idx.vertex_label("person")["primary_keys"] == ["name"]
        assert self.idx.vertex_label("nope") is None

    def test_edge_label_lookup(self):
        assert self.idx.is_edge_label("acted_in")
        assert not self.idx.is_edge_label("directed")
        assert self.idx.edge_label("acted_in")["source_label"] == "person"

    def test_label_name_sets(self):
        assert self.idx.vertex_label_names() == frozenset({"person", "movie"})
        assert self.idx.edge_label_names() == frozenset({"acted_in"})


# --------------------------------------------------------------------------- properties
class TestProperties:
    def setup_method(self):
        self.idx = GraphSchemaIndex(_schema_with_ids())

    def test_allowed_properties_for_vertex(self):
        assert self.idx.allowed_properties("vertex", "person") == frozenset({"name", "aliases"})
        assert self.idx.allowed_properties("vertex", "movie") == frozenset(
            {"title", "year", "rating", "released_on", "genres"}
        )

    def test_allowed_properties_for_edge(self):
        assert self.idx.allowed_properties("edge", "acted_in") == frozenset({"role", "is_lead"})

    def test_allowed_properties_unknown_label_or_type(self):
        assert self.idx.allowed_properties("vertex", "robot") == frozenset()
        assert self.idx.allowed_properties("edge", "directed") == frozenset()
        assert self.idx.allowed_properties("triple", "person") == frozenset()

    def test_property_type_and_cardinality_lookup(self):
        assert self.idx.property_data_type("year") == "INT"
        assert self.idx.property_data_type("released_on") == "DATE"
        assert self.idx.property_cardinality("aliases") == "LIST"
        assert self.idx.property_cardinality("genres") == "SET"
        assert self.idx.property_cardinality("name") == "SINGLE"

    def test_unknown_property_defaults_to_text_single(self):
        assert self.idx.property_data_type("mystery") == "TEXT"
        assert self.idx.property_cardinality("mystery") == "SINGLE"


# ------------------------------------------------------------------------ primary key id
class TestCanonicalVertexId:
    def setup_method(self):
        self.idx = GraphSchemaIndex(_schema_with_ids())

    def test_single_primary_key(self):
        assert self.idx.canonical_vertex_id("person", {"name": "Tom Hanks"}) == "1:Tom Hanks"

    def test_multi_primary_key_uses_bang_separator(self):
        assert self.idx.canonical_vertex_id("movie", {"title": "Forrest Gump", "year": 1994}) == "2:Forrest Gump!1994"

    def test_missing_primary_key_returns_none(self):
        assert self.idx.canonical_vertex_id("person", {}) is None
        assert self.idx.canonical_vertex_id("movie", {"title": "Forrest Gump"}) is None

    def test_empty_string_primary_key_returns_none(self):
        assert self.idx.canonical_vertex_id("person", {"name": ""}) is None

    def test_unknown_label_returns_none(self):
        assert self.idx.canonical_vertex_id("robot", {"name": "R2D2"}) is None

    def test_customize_id_strategy_returns_none(self):
        schema = _schema_with_ids()
        schema["vertexlabels"][0]["id_strategy"] = "CUSTOMIZE_STRING"
        idx = GraphSchemaIndex(schema)
        assert idx.canonical_vertex_id("person", {"name": "Tom Hanks"}) is None

    def test_schema_without_id_falls_back_to_none(self):
        """Inline user schemas without vertex label ``id`` cannot use baseline canonical."""
        idx = GraphSchemaIndex(_schema_without_ids())
        assert idx.canonical_vertex_id("person", {"name": "Tom Hanks"}) is None

    def test_stringifies_non_string_primary_key_values(self):
        assert self.idx.canonical_vertex_id("movie", {"title": "Forrest Gump", "year": 1994}) == "2:Forrest Gump!1994"


# ------------------------------------------------------------------------------- edges
class TestEdgeEndpoints:
    def setup_method(self):
        self.idx = GraphSchemaIndex(_schema_with_ids())

    def test_endpoint_spec_returns_tuple(self):
        assert self.idx.edge_endpoint_spec("acted_in") == ("person", "movie")

    def test_endpoint_spec_unknown_edge_returns_none(self):
        assert self.idx.edge_endpoint_spec("directed") is None

    def test_endpoint_compatible_matches_direction(self):
        assert self.idx.is_endpoint_compatible("acted_in", "person", "movie")
        assert not self.idx.is_endpoint_compatible("acted_in", "movie", "person")

    def test_endpoint_compatible_unknown_edge(self):
        assert not self.idx.is_endpoint_compatible("directed", "person", "movie")


# ---------------------------------------------------------------------- coercion: TEXT
class TestCoerceText:
    def setup_method(self):
        self.idx = GraphSchemaIndex(_schema_with_ids())

    def test_text_passthrough(self):
        assert self.idx.coerce_property_value("name", "Tom Hanks") == ("Tom Hanks", None)

    def test_text_stringifies_number(self):
        assert self.idx.coerce_property_value("name", 42) == ("42", None)

    def test_text_none_rejected(self):
        value, reason = self.idx.coerce_property_value("name", None)
        assert value is None
        assert reason is not None


# --------------------------------------------------------------------- coercion: INT
class TestCoerceInt:
    def setup_method(self):
        self.idx = GraphSchemaIndex(_schema_with_ids())

    def test_int_passthrough(self):
        assert self.idx.coerce_property_value("year", 1994) == (1994, None)

    def test_int_from_lossless_string(self):
        assert self.idx.coerce_property_value("year", "1994") == (1994, None)

    def test_int_from_whole_float(self):
        assert self.idx.coerce_property_value("year", 1994.0) == (1994, None)

    def test_int_rejects_lossy_float(self):
        value, reason = self.idx.coerce_property_value("year", 1994.5)
        assert value is None
        assert "lossless" in reason

    def test_int_rejects_lossy_string(self):
        value, reason = self.idx.coerce_property_value("year", "1994.5")
        assert value is None
        assert reason is not None

    def test_int_rejects_bool(self):
        value, reason = self.idx.coerce_property_value("year", True)
        assert value is None
        assert "bool" in reason


# ------------------------------------------------------------------- coercion: FLOAT
class TestCoerceFloat:
    def setup_method(self):
        self.idx = GraphSchemaIndex(_schema_with_ids())

    def test_float_from_int_and_float(self):
        assert self.idx.coerce_property_value("rating", 5) == (5.0, None)
        assert self.idx.coerce_property_value("rating", 8.5) == (8.5, None)

    def test_float_from_string(self):
        assert self.idx.coerce_property_value("rating", "8.5") == (8.5, None)

    def test_float_rejects_garbage(self):
        value, reason = self.idx.coerce_property_value("rating", "eight")
        assert value is None
        assert reason is not None

    def test_float_rejects_bool(self):
        value, reason = self.idx.coerce_property_value("rating", False)
        assert value is None
        assert "bool" in reason


# -------------------------------------------------------------- coercion: BOOLEAN
class TestCoerceBoolean:
    def setup_method(self):
        self.idx = GraphSchemaIndex(_schema_with_ids())

    def test_bool_passthrough(self):
        assert self.idx.coerce_property_value("is_lead", True) == (True, None)
        assert self.idx.coerce_property_value("is_lead", False) == (False, None)

    def test_bool_from_yes_no_true_false_strings(self):
        assert self.idx.coerce_property_value("is_lead", "yes")[0] is True
        assert self.idx.coerce_property_value("is_lead", "True")[0] is True
        assert self.idx.coerce_property_value("is_lead", "NO")[0] is False
        assert self.idx.coerce_property_value("is_lead", "false")[0] is False

    def test_bool_from_zero_or_one(self):
        assert self.idx.coerce_property_value("is_lead", 1)[0] is True
        assert self.idx.coerce_property_value("is_lead", 0)[0] is False

    def test_bool_rejects_unrelated_strings(self):
        value, reason = self.idx.coerce_property_value("is_lead", "maybe")
        assert value is None
        assert reason is not None


# ------------------------------------------------------------------ coercion: DATE
class TestCoerceDate:
    def setup_method(self):
        self.idx = GraphSchemaIndex(_schema_with_ids())

    def test_iso_date_passthrough(self):
        assert self.idx.coerce_property_value("released_on", "1994-07-06") == (
            "1994-07-06",
            None,
        )

    def test_alt_format_rejected(self):
        value, reason = self.idx.coerce_property_value("released_on", "1994/07/06")
        assert value is None
        assert reason is not None

    def test_non_string_date_rejected(self):
        value, reason = self.idx.coerce_property_value("released_on", 19940706)
        assert value is None
        assert reason is not None


# ----------------------------------------------------------- coercion: LIST / SET
class TestCoerceCardinality:
    def setup_method(self):
        self.idx = GraphSchemaIndex(_schema_with_ids())

    def test_list_of_text_coerces_each_item(self):
        value, reason = self.idx.coerce_property_value("aliases", ["Tom", 42, "Hanks"])
        assert value == ["Tom", "42", "Hanks"]
        assert reason is None

    def test_list_expects_list_input(self):
        value, reason = self.idx.coerce_property_value("aliases", "not-a-list")
        assert value is None
        assert reason is not None

    def test_list_drops_none_items_with_warning(self):
        value, reason = self.idx.coerce_property_value("aliases", ["Tom", None, "Hanks"])
        assert value == ["Tom", "Hanks"]
        assert reason is not None
        assert "1 items" in reason

    def test_set_deduplicates_after_coercion(self):
        value, reason = self.idx.coerce_property_value("genres", ["drama", "Drama", "drama", "romance"])
        # Deduplication is exact-string on coerced values (case-sensitive by design).
        assert value == ["drama", "Drama", "romance"]
        assert reason is None
