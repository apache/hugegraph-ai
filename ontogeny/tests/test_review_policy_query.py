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

import shutil
from datetime import UTC, datetime

import pytest
import yaml
from doc_fixtures import make_context
from sqlalchemy import select

from ontogeny.core import validate
from ontogeny.documents.models import ExtractAssertionRow, ExtractPacketRow
from ontogeny.documents.protocol import ChunkResult
from ontogeny.policy.engine import PolicyEngine
from ontogeny.registry.compiled import compile_package


def test_unsupported_forbid_condition_cannot_publish(golden_pkg):
    golden_pkg.source_texts[("PolicySet", "default")] = """
        permit(principal, action == Action::"open", resource);
        forbid(principal, action == Action::"open", resource) when { !resource.approved };
    """
    report = validate(golden_pkg)
    assert any(issue.code == "POLICY-FORBID" for issue in report.issues)


@pytest.mark.parametrize("condition", ["!resource.approved", "1 / resource.divisor > 0"])
def test_unevaluable_forbid_denies_existing_published_policy(golden_pkg, condition):
    golden_pkg.source_texts[("PolicySet", "default")] = f"""
        permit(principal, action == Action::"open", resource);
        forbid(principal, action == Action::"open", resource) when {{ {condition} }};
    """
    engine = PolicyEngine(compile_package(golden_pkg))
    decision = engine.decide({"id": "operator"}, "open", {"approved": False, "divisor": 0})
    assert not decision.allow


@pytest.mark.parametrize("op", ["eq", "ne", "lt", "le", "gt", "ge", "in"])
async def test_rest_timestamp_filter_coerces_iso_operands(client, op):
    http, sc = client
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    async with sc.sessionmaker() as session:
        await sc.repo.action_insert(
            session,
            "process-step",
            {"step_id": "001", "lot_id": "lot", "seq": 1, "name": "step", "completed_at": timestamp},
            timestamp,
        )
        await session.commit()
    value = "2026-01-01T00:00:00Z"
    if op == "in":
        value = [value, timestamp.isoformat()]
    response = await http.post(
        "/api/v1/objects/process-step/query",
        json={"filter": {"field": "completed_at", "op": op, "value": value}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == int(op in {"ne", "gt", "ge", "in"})
    # Coercing filter values must preserve string primary keys with leading zeros.
    response = await http.post("/api/v1/objects/process-step/query", json={"filter": {"step_id": "001"}})
    assert response.json()["objects"][0]["step_id"] == "001"


async def test_invalid_rest_timestamp_filter_is_a_client_error(client):
    http, _ = client
    response = await http.post(
        "/api/v1/objects/process-step/query",
        json={"filter": {"field": "completed_at", "op": "ge", "value": "invalid"}},
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "TYPE_MISMATCH"


class _ScopedNoteExtractor:
    async def extract(self, request):
        label = next(item["name"] for item in request.schema["vertexlabels"] if item["name"].endswith("note"))
        return [
            ChunkResult(
                doc.doc_id,
                0,
                doc.text,
                {
                    "vertices": [
                        {
                            "id": "note",
                            "label": label,
                            "properties": {
                                "supplier_name": "Acme Components",
                                "effective_date": "2026-03-01",
                                "risk_level": "HIGH",
                            },
                        }
                    ],
                    "edges": [],
                },
            )
            for doc in request.docs
        ]


async def test_identical_documents_in_different_stores_have_independent_provenance(tmp_path):
    def add_store(pkg):
        store_path = pkg / "stores" / "supplier-docs.yaml"
        store = yaml.safe_load(store_path.read_text())
        store["metadata"]["name"] = "other-docs"
        store["spec"]["connection"] = "data/other-docs"
        (pkg / "stores" / "other-docs.yaml").write_text(yaml.safe_dump(store))
        note = yaml.safe_load((pkg / "objects" / "supplier-note.yaml").read_text())
        note["metadata"]["name"] = "other-note"
        note["spec"]["backing"]["store"] = "other-docs"
        (pkg / "objects" / "other-note.yaml").write_text(yaml.safe_dump(note))
        notes = pkg / "data" / "docs" / "supplier-notes"
        for item in notes.iterdir():
            if item.name != "acme-2026-03.md":
                item.unlink()
        shutil.copytree(pkg / "data" / "docs", pkg / "data" / "other-docs")

    sc, pkg, _ = await make_context(tmp_path, extractor=_ScopedNoteExtractor(), mutate=add_store)
    try:
        first = (await sc.documents.list_documents("supplier-docs"))["documents"]
        second = (await sc.documents.list_documents("other-docs"))["documents"]
        assert len(first) == len(second) == 1
        assert first[0]["id"] != second[0]["id"]
        # A stable store identity must also be stable across unchanged scans.
        assert (await sc.documents.list_documents("supplier-docs"))["documents"][0]["id"] == first[0]["id"]
        for store_name in ("supplier-docs", "other-docs"):
            result = await sc.documents.ingest(store_name)
            assert result["inserted"] == 1
        async with sc.sessionmaker() as session:
            assertions = (await session.execute(select(ExtractAssertionRow))).scalars().all()
            packets = (await session.execute(select(ExtractPacketRow))).scalars().all()
            assert {r.doc_id for r in assertions} == {first[0]["id"], second[0]["id"]}
            assert {r.doc_id for r in packets} == {first[0]["id"], second[0]["id"]}
        (pkg / "data" / "docs" / "supplier-notes" / "acme-2026-03.md").unlink()
        removed = await sc.documents.ingest("supplier-docs")
        assert removed["archived"] == 1
        async with sc.sessionmaker() as session:
            other_rows, total = await sc.repo.query(session, "other-note")
            assert total == 1 and other_rows[0]["risk_level"] == "HIGH"
            remaining = (await session.execute(select(ExtractAssertionRow))).scalars().all()
            assert {r.doc_id for r in remaining} == {second[0]["id"]}
    finally:
        await sc.engine.dispose()
