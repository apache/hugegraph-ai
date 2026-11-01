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

"""The extraction schema is the ontology, not a model guess."""

from __future__ import annotations

from doc_fixtures import DOMAIN

from ontogeny.core import load_package
from ontogeny.core.validator import validate
from ontogeny.documents.schema import compile_extraction_schema
from ontogeny.registry import compile_package


def _compiled():
    pkg = load_package(DOMAIN)
    report = validate(pkg)
    assert report.ok, report.entries
    return compile_package(pkg)


def test_schema_uses_ontology_labels_and_reference_types():
    bundle = compile_extraction_schema(_compiled(), ["supplier-note"], reference_types=["supplier"])
    labels = {v["name"]: v for v in bundle.schema["vertexlabels"]}
    assert set(labels) == {"supplier", "supplier-note"}
    note = labels["supplier-note"]
    # the declared key excludes the primary key -> the corpus must not invent it
    assert note["id_strategy"] == "CUSTOMIZE_STRING"
    assert note["primary_keys"] == ["supplier_name"]
    assert "note_id" not in note["properties"]
    assert "supplier_name" not in note["nullable_keys"]
    assert "risk_level" in note["nullable_keys"]
    assert bundle.references == {"supplier"}

    keys = {p["name"]: p for p in bundle.schema["propertykeys"]}
    assert keys["effective_date"]["data_type"] == "DATE"
    assert keys["risk_level"]["data_type"] == "TEXT"
    assert "LOW" in keys["risk_level"]["description"] and "HIGH" in keys["risk_level"]["description"]

    edges = bundle.schema["edgelabels"]
    assert [e["name"] for e in edges] == ["supplier-risk-note"]
    assert edges[0]["source_label"] == "supplier"
    assert edges[0]["target_label"] == "supplier-note"


def test_schema_hash_is_stable_and_content_sensitive(tmp_path):
    compiled = _compiled()
    a = compile_extraction_schema(compiled, ["supplier-note"], reference_types=["supplier"])
    b = compile_extraction_schema(compiled, ["supplier-note"], reference_types=["supplier"])
    assert a.hash == b.hash
    changed = dict(a.schema)
    changed["vertexlabels"] = [dict(x) for x in a.schema["vertexlabels"]]
    changed["vertexlabels"][0]["description"] = "different"
    from ontogeny.documents.schema import SchemaBundle

    c = SchemaBundle(schema=changed, fields=a.fields, reverse=a.reverse, labels=a.labels, references=a.references)
    assert c.hash != a.hash


def test_derived_properties_are_never_extracted():
    compiled = _compiled()
    bundle = compile_extraction_schema(compiled, ["supplier-note"])
    fields = bundle.fields["supplier-note"]
    assert "note_id" not in fields  # system-generated PK
    assert "supplier_name" in fields


def test_extraction_schema_is_a_neutral_graph_contract():
    """It is an agent request/response contract, not graph-server DDL."""
    bundle = compile_extraction_schema(_compiled(), ["supplier-note"])
    names = {v["name"] for v in bundle.schema["vertexlabels"]}
    assert "supplier-note" in names


def test_local_scope_filters_properties_and_keeps_identity_fields():
    compiled = _compiled()
    bundle = compile_extraction_schema(
        compiled,
        ["supplier-note"],
        reference_types=["supplier"],
        properties={"supplier-note": ["risk_level"]},
        links=["supplier-risk-note"],
    )
    fields = bundle.fields["supplier-note"]
    assert "risk_level" in fields
    assert "summary" not in fields
    # supplier_name/effective_date are the identity even though they were not selected
    assert "supplier_name" in fields
    assert "effective_date" in fields
    note = next(v for v in bundle.schema["vertexlabels"] if v["name"] == "supplier-note")
    assert "summary" not in note["properties"]
    assert [e["name"] for e in bundle.schema["edgelabels"]] == ["supplier-risk-note"]


def test_local_scope_rejects_unknown_properties_and_links():
    compiled = _compiled()
    import pytest

    with pytest.raises(ValueError):
        compile_extraction_schema(compiled, ["supplier-note"], properties={"supplier-note": ["nope"]})
    with pytest.raises(ValueError):
        compile_extraction_schema(compiled, ["supplier-note"], links=["nope"])


def test_scope_without_links_keeps_vertices_only():
    compiled = _compiled()
    bundle = compile_extraction_schema(
        compiled,
        ["supplier-note"],
        reference_types=["supplier"],
        properties={"supplier-note": ["risk_level"]},
        links=[],
    )
    assert bundle.schema["edgelabels"] == []
