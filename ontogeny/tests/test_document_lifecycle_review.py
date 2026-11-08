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

"""Regression coverage for document evidence, packet caching and review retraction."""

from __future__ import annotations

from dataclasses import replace

import pytest
import pytest_asyncio
import yaml
from doc_fixtures import make_context
from sqlalchemy import select

from ontogeny.documents.models import (
    DocumentRow,
    ExtractAssertionRow,
    ExtractCandidateRow,
    ExtractPacketRow,
)


@pytest_asyncio.fixture()
async def lifecycle_context(tmp_path):
    sc, pkg, db = await make_context(tmp_path)
    try:
        yield sc, pkg, db
    finally:
        await sc.engine.dispose()


async def _rows(sc, model):
    async with sc.sessionmaker() as session:
        return list((await session.execute(select(model))).scalars().all())


async def _acme_note(sc):
    async with sc.sessionmaker() as session:
        rows, _ = await sc.repo.query(session, "supplier-note", limit=50)
    return next((r for r in rows if r["supplier_name"] == "Acme Components"), None)


async def test_replacement_records_support_without_a_new_object_revision(lifecycle_context):
    sc, pkg, _ = lifecycle_context
    await sc.sync("supplier-note")
    before = await _acme_note(sc)
    path = pkg / "data/docs/supplier-notes/acme-2026-03.md"
    path.write_text(path.read_text() + "\nEditorial change without new facts.\n")

    summary = await sc.sync("supplier-note")
    after = await _acme_note(sc)
    assert summary["archived"] == 0
    assert after is not None
    assert after["_rev"] == before["_rev"]
    current_doc = next(d for d in await _rows(sc, DocumentRow) if d.path == str(path) and d.status == "active")
    assertions = [a for a in await _rows(sc, ExtractAssertionRow) if a.kind == "object" and a.doc_id == current_doc.id]
    assert any(a.prop == "risk_level" and a.value == "HIGH" for a in assertions)


async def test_corroborating_document_survives_original_document_removal(lifecycle_context):
    sc, pkg, _ = lifecycle_context
    await sc.sync("supplier-note")
    original = pkg / "data/docs/supplier-notes/acme-2026-03.md"
    corroborating = original.with_name("acme-corroborating.md")
    corroborating.write_bytes(original.read_bytes())
    await sc.sync("supplier-note")
    original_doc = next(d for d in await _rows(sc, DocumentRow) if d.path == str(original))

    await sc.documents.remove_document(original_doc.id)
    assert await _acme_note(sc) is not None
    corroborating_doc = next(d for d in await _rows(sc, DocumentRow) if d.path == str(corroborating))
    await sc.documents.remove_document(corroborating_doc.id)
    assert await _acme_note(sc) is None


async def test_conflicting_noop_does_not_assert_the_unaccepted_value(lifecycle_context):
    sc, pkg, _ = lifecycle_context
    await sc.sync("supplier-note")
    path = pkg / "data/docs/supplier-notes/acme-2026-03.md"
    content = path.read_text().replace("Risk level: HIGH", "Risk level: LOW")
    path.write_text(content)
    await sc.sync("supplier-note")
    current_doc = next(d for d in await _rows(sc, DocumentRow) if d.path == str(path) and d.status == "active")
    assertions = [a for a in await _rows(sc, ExtractAssertionRow) if a.kind == "object" and a.doc_id == current_doc.id]
    assert assertions
    assert not any(a.prop == "risk_level" for a in assertions)
    assert (await _acme_note(sc))["risk_level"] == "HIGH"
    assert any(c.reason == "CONFLICT" for c in await _rows(sc, ExtractCandidateRow))


async def test_packet_cache_reuses_one_run_and_preserves_all_audit_trails(lifecycle_context):
    sc, _, _ = lifecycle_context
    runs = []
    for _ in range(4):
        summary = await sc.sync("supplier-note")
        runs.append(summary["run_id"])
    assert sc.document_extractor.calls == 3
    packets = await _rows(sc, ExtractPacketRow)
    for run_id in runs:
        assert sum(p.run_id == run_id for p in packets) == 3
        detail = await sc.documents.run_detail(run_id)
        assert sum(len(d["chunks"]) for d in detail["documents"]) == 3


@pytest.mark.parametrize("withdrawal", ["document", "extraction"])
async def test_manually_accepted_link_records_assertion_and_retracts(tmp_path, withdrawal):
    def mutate(pkg):
        path = pkg / "objects/supplier-note.yaml"
        obj = yaml.safe_load(path.read_text())
        obj["spec"]["backing"]["extract"]["create"] = "review"
        path.write_text(yaml.safe_dump(obj, sort_keys=False))

    sc, _, _ = await make_context(tmp_path, mutate=mutate)
    try:
        await sc.sync("supplier-note")
        candidates = await _rows(sc, ExtractCandidateRow)
        obj = next(
            c
            for c in candidates
            if c.reason == "NEW_OBJECT" and c.payload["props"]["supplier_name"] == "Acme Components"
        )
        link = next(c for c in candidates if c.reason == "ENDPOINT_NOT_COMMITTED" and c.doc_id == obj.doc_id)
        await sc.documents.accept_candidate(obj.id, principal="reviewer")
        await sc.documents.accept_candidate(link.id, principal="reviewer")
        assertions = [a for a in await _rows(sc, ExtractAssertionRow) if a.kind == "link" and a.doc_id == obj.doc_id]
        assert len(assertions) == 1
        assert assertions[0].value == {"src": "SUP-001", "dst": obj.object_id}
        assert assertions[0].run_id == link.run_id
        assert assertions[0].evidence["doc_id"] == obj.doc_id

        if withdrawal == "document":
            await sc.documents.remove_document(obj.doc_id)
        else:
            # Re-extract the same document version with an agent that reports
            # no relationships, including the previously accepted link.
            sc.document_extractor.skip_supplier_edge = True
            sc.settings = replace(sc.settings, doc_agent_cmd="updated-agent-without-links")
            await sc.sync("supplier-note")
        async with sc.sessionmaker() as session:
            assert await sc.repo.link_members(session, "supplier-risk-note") == []
    finally:
        await sc.engine.dispose()
