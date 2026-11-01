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

"""Binder rules: identity, coercion, references, edge direction, evidence."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from ontogeny.core.types import PropertyType
from ontogeny.documents.binder import Binder, _quote, coerce_value
from ontogeny.documents.schema import compile_extraction_schema

TEXT = "Supplier: Acme Components\nEffective date: 2026/03/01\nRisk level: high\nSummary: A fire stopped two lines.\n"


def test_coercion_is_forgiving_before_validation():
    assert coerce_value(PropertyType.parse("enum[LOW, HIGH]"), " high ", prop="risk") == "HIGH"
    assert coerce_value(PropertyType.parse("date"), "2026/03/01", prop="d") == dt.date(2026, 3, 1)
    assert coerce_value(PropertyType.parse("decimal(10,2)"), "$1,234.50", prop="x") == 1234.5
    assert coerce_value(PropertyType.parse("integer"), "1,200", prop="n") == 1200
    assert coerce_value(PropertyType.parse("boolean"), "yes", prop="b") is True


def test_quote_finds_the_sentence():
    assert "Effective date" in _quote(TEXT, "2026/03/01")
    assert _quote(TEXT, "not present") == ""


async def test_binder_maps_identities_references_and_edges(doc_context):
    sc, _, _ = doc_context
    schema = compile_extraction_schema(sc.compiled, ["supplier-note"], reference_types=["supplier"])
    graph = {
        "vertices": [
            {"id": "ref", "label": "supplier", "properties": {"name": "Acme Components"}},
            {
                "id": "n1",
                "label": "supplier-note",
                "properties": {
                    "supplier_name": "Acme Components",
                    "risk_level": "high",
                    "effective_date": "2026/03/01",
                    "summary": "A fire stopped two lines.",
                    "unknown_prop": "ignored",
                },
            },
        ],
        "edges": [
            {
                "label": "supplier-risk-note",
                "outV": "ref",
                "outVLabel": "supplier",
                "inV": "n1",
                "inVLabel": "supplier-note",
                "properties": {},
            }
        ],
    }
    packet = SimpleNamespace(doc_id="doc-1", chunk_index=0, text=TEXT)
    async with sc.sessionmaker() as session:
        binder = Binder(sc.compiled, schema, sc.repo, session, run_id=0)
        out = await binder.bind([(packet, graph)])

    assert out.references == {("supplier", "SUP-001")}
    assert len(out.objects) == 1
    bound = next(iter(out.objects.values()))
    assert bound.object_id.startswith("supplier-note:")
    assert bound.created is True
    assert bound.props["risk_level"] == "HIGH"
    assert bound.props["effective_date"] == dt.date(2026, 3, 1)
    assert "unknown_prop" not in bound.props
    assert "unknown_prop" in " ".join(out.gaps)
    assert bound.evidence["risk_level"].quote
    assert len(out.links) == 1
    link = next(iter(out.links.values()))
    assert link.src_id == "SUP-001" and link.dst_id == bound.object_id


async def test_binder_rejects_reversed_edges(doc_context):
    sc, _, _ = doc_context
    schema = compile_extraction_schema(sc.compiled, ["supplier-note"], reference_types=["supplier"])
    graph = {
        "vertices": [
            {"id": "ref", "label": "supplier", "properties": {"name": "Acme Components"}},
            {
                "id": "n1",
                "label": "supplier-note",
                "properties": {"supplier_name": "Acme Components", "effective_date": "2026-01-01"},
            },
        ],
        "edges": [
            {
                "label": "supplier-risk-note",
                "outV": "n1",
                "outVLabel": "supplier-note",
                "inV": "ref",
                "inVLabel": "supplier",
                "properties": {},
            }
        ],
    }
    packet = SimpleNamespace(
        doc_id="doc-2", chunk_index=0, text="Supplier: Acme Components\nEffective date: 2026-01-01"
    )
    async with sc.sessionmaker() as session:
        out = await Binder(sc.compiled, schema, sc.repo, session, run_id=0).bind([(packet, graph)])
    assert any(c.reason == "WRONG_DIRECTION" for c in out.candidates)
    assert not out.links


async def test_binder_never_invents_an_unresolved_reference(doc_context):
    sc, _, _ = doc_context
    schema = compile_extraction_schema(sc.compiled, ["supplier-note"], reference_types=["supplier"])
    graph = {
        "vertices": [
            {"id": "ref", "label": "supplier", "properties": {"name": "Unknown Supplier Ltd"}},
            {
                "id": "n1",
                "label": "supplier-note",
                "properties": {"supplier_name": "Unknown Supplier Ltd", "effective_date": "2026-05-01"},
            },
        ],
        "edges": [
            {
                "label": "supplier-risk-note",
                "outV": "ref",
                "outVLabel": "supplier",
                "inV": "n1",
                "inVLabel": "supplier-note",
                "properties": {},
            }
        ],
    }
    packet = SimpleNamespace(
        doc_id="doc-3", chunk_index=0, text="Supplier: Unknown Supplier Ltd\nEffective date: 2026-05-01"
    )
    async with sc.sessionmaker() as session:
        out = await Binder(sc.compiled, schema, sc.repo, session, run_id=0).bind([(packet, graph)])
    assert any(c.reason == "UNRESOLVED_REFERENCE" for c in out.candidates)
    assert any(c.reason == "UNRESOLVED_ENDPOINT" for c in out.candidates)
    assert not out.links
