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

"""Document ingestion end to end: corpus -> packets -> objects/links -> review."""

from __future__ import annotations

import base64
import re

import pytest
from doc_fixtures import FakeExtractor, add_note, make_context
from sqlalchemy import select

from ontogeny.documents.models import (
    DocumentRow,
    ExtractAssertionRow,
    ExtractCandidateRow,
    ExtractPacketRow,
    ExtractRunRow,
)
from ontogeny.documents.protocol import ChunkResult


async def _rows(sc, model):
    async with sc.sessionmaker() as s:
        return (await s.execute(select(model))).scalars().all()


async def _note(sc, supplier: str):
    async with sc.sessionmaker() as s:
        rows = await sc.repo.query(s, "supplier-note", limit=50)
    return next((r for r in rows[0] if r["supplier_name"] == supplier), None)


async def _link_pairs(sc):
    async with sc.sessionmaker() as s:
        return await sc.repo.link_members(s, "supplier-risk-note")


async def test_ingest_writes_objects_and_links(doc_context):
    sc, _, _ = doc_context
    summary = await sc.sync("supplier-note")
    assert summary["documents"] == 3
    assert summary["chunks"] == 3
    assert summary["inserted"] == 2
    assert summary["links"] == 2
    assert summary["candidates"] == 0
    assert summary["quarantined"] == 0

    acme = await _note(sc, "Acme Components")
    assert acme is not None
    assert acme["risk_level"] == "HIGH"
    assert str(acme["effective_date"]) == "2026-03-01"
    assert acme["note_id"].startswith("supplier-note:")

    pairs = await _link_pairs(sc)
    assert ("SUP-001", acme["note_id"]) in pairs
    assert len(pairs) == 2

    # provenance: one assertion per written field, and the packet keeps the text
    assertions = await _rows(sc, ExtractAssertionRow)
    assert any(a.prop == "risk_level" and a.object_id == acme["note_id"] for a in assertions)
    packets = await _rows(sc, ExtractPacketRow)
    assert len(packets) == 3
    assert any("fire at the Acme" in p.text for p in packets)

    runs = await _rows(sc, ExtractRunRow)
    assert runs[-1].status == "ok"
    assert runs[-1].n_inserted == 2


async def test_rerun_is_idempotent_and_uses_packet_cache(doc_context):
    sc, _, _ = doc_context
    await sc.sync("supplier-note")
    extractor = sc.document_extractor
    calls = extractor.calls
    before = await _note(sc, "Acme Components")

    again = await sc.sync("supplier-note")
    assert again["inserted"] == 0
    assert again["updated"] == 0
    assert again["noop"] == 2
    assert again["links"] == 2
    # unchanged documents + unchanged schema -> no second model call
    assert extractor.calls == calls
    after = await _note(sc, "Acme Components")
    assert after["_rev"] == before["_rev"]
    # the cached rerun still has a per-chunk audit trail for the UI
    detail = await sc.documents.run_detail(again["run_id"])
    assert sum(len(d["chunks"]) for d in detail["documents"]) == 3


async def test_changed_document_replaces_the_same_note(doc_context):
    sc, pkg, _ = doc_context
    await sc.sync("supplier-note")
    # same supplier+date -> same identity; a changed value conflicts (fill-empty)
    add_note(pkg, "acme-update.md", "Acme Components", "2026-03-01", "MEDIUM", "Updated finding")
    summary = await sc.sync("supplier-note")
    # both disagreeing fields (risk level, summary) become candidates
    assert summary["candidates"] == 2
    # the existing value is never silently overwritten
    after = await _note(sc, "Acme Components")
    assert after["risk_level"] == "HIGH"
    candidates = await _rows(sc, ExtractCandidateRow)
    conflict = next(c for c in candidates if c.reason == "CONFLICT" and c.payload.get("field") == "risk_level")
    assert conflict.payload["current"] == "HIGH"
    assert conflict.payload["proposed"] == "MEDIUM"


async def test_review_accept_applies_overrides_and_audits(doc_context):
    sc, pkg, _ = doc_context
    await sc.sync("supplier-note")
    add_note(pkg, "acme-update.md", "Acme Components", "2026-03-01", "MEDIUM", "Updated finding")
    await sc.sync("supplier-note")
    conflict = next(
        c
        for c in await _rows(sc, ExtractCandidateRow)
        if c.reason == "CONFLICT" and c.payload.get("field") == "risk_level"
    )

    out = await sc.documents.accept_candidate(
        conflict.id, {"risk_level": "MEDIUM"}, principal="reviewer-1", note="confirmed with procurement"
    )
    assert out["ok"] is True
    after = await _note(sc, "Acme Components")
    assert after["risk_level"] == "MEDIUM"
    # only the chosen field moved; the summary was not replayed from the
    # candidate's stale props
    assert after["summary"].startswith("A fire")
    assert after["_rev"] == 2
    from ontogeny.action.models import RevisionRow

    revisions = await _rows(sc, RevisionRow)
    assert any(r.action == "ingest.accept" and r.principal == "reviewer-1" for r in revisions)


async def test_review_reject_writes_nothing(doc_context):
    sc, pkg, _ = doc_context
    await sc.sync("supplier-note")
    add_note(pkg, "globex-conflict.md", "Globex Materials", "2026-02-14", "HIGH", "Different finding")
    await sc.sync("supplier-note")
    candidate = next(c for c in await _rows(sc, ExtractCandidateRow) if c.reason == "CONFLICT")
    await sc.documents.reject_candidate(candidate.id, principal="reviewer-1", reason="not credible")
    assert (await _note(sc, "Globex Materials"))["risk_level"] == "LOW"
    refreshed = await _rows(sc, ExtractCandidateRow)
    assert next(c for c in refreshed if c.id == candidate.id).status == "rejected"


async def test_document_removal_retracts_links_and_archives(doc_context):
    sc, _, _ = doc_context
    await sc.sync("supplier-note")
    acme = await _note(sc, "Acme Components")
    docs = await _rows(sc, DocumentRow)
    target = next(d for d in docs if d.path.endswith("acme-2026-03.md"))

    out = await sc.documents.remove_document(target.id)
    assert out["archived"] == 1
    pairs = await _link_pairs(sc)
    assert ("SUP-001", acme["note_id"]) not in pairs
    assert await _note(sc, "Acme Components") is None
    # the other note is untouched
    assert await _note(sc, "Globex Materials") is not None


async def test_dry_run_never_writes(doc_context):
    sc, _, _ = doc_context
    summary = await sc.documents.ingest("supplier-docs", dry_run=True)
    assert summary["objects"] == 2
    assert summary["links"] == 2
    assert len(summary["preview"]["objects"]) == 2
    assert await _note(sc, "Acme Components") is None
    assert await _rows(sc, ExtractPacketRow) == []
    assert await _rows(sc, ExtractRunRow) == []


async def test_upload_then_ingest(doc_context):
    sc, _, _ = doc_context
    content = (
        "Supplier: Initech Fasteners\nEffective date: 2026-04-02\nRisk level: MEDIUM\n"
        "Summary: A customs hold delayed one shipment.\n"
    )
    out = await sc.documents.upload(
        "supplier-docs",
        [{"name": "initech.md", "content_b64": base64.b64encode(content.encode()).decode()}],
    )
    assert out["written"] == ["supplier-notes/initech.md"]
    summary = await sc.sync("supplier-note")
    assert summary["inserted"] == 3  # the three shipped notes + the uploaded one
    note = await _note(sc, "Initech Fasteners")
    assert note["risk_level"] == "MEDIUM"
    pairs = await _link_pairs(sc)
    assert ("SUP-003", note["note_id"]) in pairs


async def test_extractor_failure_isolated_to_one_document(doc_context):
    sc, _, _ = doc_context
    sc.document_extractor = FakeExtractor(fail_names={"globex-2026-02.md"})
    summary = await sc.sync("supplier-note")
    assert summary["inserted"] == 1  # Acme still lands
    docs = {d.path: d for d in await _rows(sc, DocumentRow)}
    failed = next(d for p, d in docs.items() if p.endswith("globex-2026-02.md"))
    assert failed.error and "simulated" in failed.error
    runs = await _rows(sc, ExtractRunRow)
    assert "simulated" in (runs[-1].error or "")


async def test_unresolved_reference_goes_to_review_not_a_new_object(doc_context):
    sc, pkg, _ = doc_context
    # an unknown supplier name must not create supplier rows (reference-only)
    add_note(pkg, "unknown.md", "Unknown Supplier Ltd", "2026-05-01", "HIGH")
    summary = await sc.sync("supplier-note")
    # the reference AND the edge that needed it are both queued for a human
    assert summary["candidates"] == 2
    candidate = next(c for c in await _rows(sc, ExtractCandidateRow) if c.reason == "UNRESOLVED_REFERENCE")
    assert candidate.payload["object_type"] == "supplier"
    async with sc.sessionmaker() as s:
        assert await sc.repo.get(s, "supplier", "Unknown Supplier Ltd") is None
    # the note is created, but no link is asserted
    pairs = await _link_pairs(sc)
    assert all(src.startswith("SUP-") for src, _ in pairs)


async def test_disabled_extractor_fails_with_actionable_error(tmp_path):
    sc, _, _ = await make_context(tmp_path)
    sc.document_extractor = None
    with pytest.raises(Exception) as exc:
        await sc.documents.ingest("supplier-docs")
    assert "extractor" in str(exc.value).lower()


async def test_run_detail_exposes_chunks_and_graphs(doc_context):
    sc, _, _ = doc_context
    summary = await sc.sync("supplier-note")
    detail = await sc.documents.run_detail(summary["run_id"])
    assert detail["run"]["inserted"] == 2
    assert len(detail["documents"]) == 3
    acme = next(d for d in detail["documents"] if d["name"] == "acme-2026-03.md")
    assert len(acme["chunks"]) == 1
    assert any(v["label"] == "supplier-note" for v in acme["chunks"][0]["graph"]["vertices"])


class ChunkedExtractor(FakeExtractor):
    """Two packets: the supplier reference in chunk 0, the note+edge in chunk 1."""

    async def extract(self, request):
        self.calls += 1
        doc = request.docs[0]
        text = doc.text
        fields = {}
        for line in text.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fields[k.strip().lower()] = v.strip()
        supplier = fields.get("supplier")
        date = fields.get("effective date")
        if not supplier or not date:
            return [ChunkResult(doc.doc_id, 0, text, {"vertices": [], "edges": []}, [], "final")]
        supplier_id = "s-" + re.sub(r"[^a-z0-9]+", "-", supplier.lower())
        note_id = "n-" + doc.doc_id[:8]
        first = {
            "vertices": [{"id": supplier_id, "label": "supplier", "properties": {"name": supplier}}],
            "edges": [],
        }
        second = {
            "vertices": [
                {
                    "id": note_id,
                    "label": "supplier-note",
                    "properties": {
                        "supplier_name": supplier,
                        "risk_level": fields.get("risk level"),
                        "effective_date": date,
                        "summary": fields.get("summary"),
                    },
                }
            ],
            "edges": [
                {
                    "label": "supplier-risk-note",
                    "outV": supplier_id,
                    "outVLabel": "supplier",
                    "inV": note_id,
                    "inVLabel": "supplier-note",
                    "properties": {},
                }
            ],
        }
        return [
            ChunkResult(doc.doc_id, 0, text[: len(text) // 2], first, [], "final"),
            ChunkResult(doc.doc_id, 1, text[len(text) // 2 :], second, [], "final"),
        ]


async def test_cross_chunk_edges_resolve_through_the_global_id_map(doc_context):
    sc, _, _ = doc_context
    sc.document_extractor = ChunkedExtractor()
    summary = await sc.sync("supplier-note")
    # two notes -> two chunks each, plus the non-note file's single chunk
    assert summary["chunks"] == 5
    assert summary["links"] == 2
    pairs = await _link_pairs(sc)
    assert len(pairs) == 2 and all(src.startswith("SUP-") for src, _ in pairs)


async def test_document_removed_before_ingest_is_still_retracted(doc_context):
    sc, pkg, _ = doc_context
    await sc.sync("supplier-note")
    acme = await _note(sc, "Acme Components")
    (pkg / "data" / "docs" / "supplier-notes" / "acme-2026-03.md").unlink()
    # listing the corpus registers the removal without extracting
    await sc.documents.list_documents("supplier-docs")
    summary = await sc.sync("supplier-note")
    assert summary["archived"] == 1
    assert ("SUP-001", acme["note_id"]) not in await _link_pairs(sc)
    assert await _note(sc, "Acme Components") is None


async def test_create_review_candidate_can_be_accepted(tmp_path):
    def mutate(pkg):
        import yaml

        path = pkg / "objects" / "supplier-note.yaml"
        doc = yaml.safe_load(path.read_text())
        doc["spec"]["backing"]["extract"]["create"] = "review"
        path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    sc, _, _ = await make_context(tmp_path, mutate=mutate)
    summary = await sc.sync("supplier-note")
    assert summary["inserted"] == 0
    assert summary["candidates"] >= 2
    assert await _note(sc, "Acme Components") is None
    candidate = next(c for c in await _rows(sc, ExtractCandidateRow) if c.reason == "NEW_OBJECT")
    await sc.documents.accept_candidate(candidate.id, principal="reviewer-1")
    assert await _note(sc, "Acme Components") is not None
    # the edge parked because its endpoint was pending; now it can be asserted
    link_candidate = next(c for c in await _rows(sc, ExtractCandidateRow) if c.reason == "ENDPOINT_NOT_COMMITTED")
    await sc.documents.accept_candidate(link_candidate.id, principal="reviewer-1")
    pairs = await _link_pairs(sc)
    assert any(src == "SUP-001" for src, _ in pairs)


async def test_agent_extension_registers_only_when_configured(doc_context):
    sc, pkg, _ = doc_context
    from dataclasses import replace

    from ontogeny_ext_agent_extract import register

    class Host:
        def __init__(self):
            self.caps = {}

        def provide(self, name, payload):
            self.caps[name] = payload

    host = Host()
    register(sc, host)
    assert "capability:document-extractor" in host.caps
    # unconfigured: the capability exists but no extractor is wired
    assert sc.document_extractor_factory is None

    sc.settings = replace(sc.settings, doc_agent_cmd="python tools/doc_agent_reference.py")
    register(sc, host)
    assert sc.document_extractor_factory is not None
    await sc.publish(str(pkg))
    assert sc.document_extractor is not None


async def test_failed_apply_marks_the_run_error(doc_context, monkeypatch):
    sc, _, _ = doc_context

    async def boom(*_a, **_k):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(sc.repo, "apply_extracted", boom)
    with pytest.raises(RuntimeError):
        await sc.sync("supplier-note")
    runs = await _rows(sc, ExtractRunRow)
    assert runs[-1].status == "error"
    assert "simulated database failure" in (runs[-1].error or "")


async def test_document_removal_never_archives_a_pre_existing_row(doc_context):
    sc, _, _ = doc_context
    # a row that existed before any document (manual/SQL/action) must survive
    # the removal of the only document that mentioned it
    from ontogeny.stores.repo import utcnow

    async with sc.sessionmaker() as s:
        await sc.repo.apply_extracted(
            s,
            "supplier-note",
            {
                "note_id": "manual-note",
                "supplier_name": "Acme Components",
                "effective_date": __import__("datetime").date(2026, 3, 1),
                "risk_level": "HIGH",
                "summary": "entered by a human",
            },
            utcnow(),
        )
        await s.commit()
    await sc.sync("supplier-note")
    docs = await _rows(sc, DocumentRow)
    target = next(d for d in docs if d.path.endswith("acme-2026-03.md"))
    await sc.documents.remove_document(target.id)
    assert await _note(sc, "Acme Components") is not None


async def test_action_link_sharing_an_edge_survives_document_removal(doc_context):
    sc, _, _ = doc_context
    await sc.sync("supplier-note")
    acme = await _note(sc, "Acme Components")
    from ontogeny.stores.repo import utcnow

    async with sc.sessionmaker() as s:
        # an explicit write (action/join-table path) shares the same pair
        await sc.repo.link_add(s, "supplier-risk-note", "SUP-001", acme["note_id"], utcnow())
        await s.commit()
    docs = await _rows(sc, DocumentRow)
    target = next(d for d in docs if d.path.endswith("acme-2026-03.md"))
    await sc.documents.remove_document(target.id)
    pairs = await _link_pairs(sc)
    assert ("SUP-001", acme["note_id"]) in pairs


async def test_identical_content_at_two_paths_is_two_documents(doc_context):
    sc, pkg, _ = doc_context
    first = (pkg / "data" / "docs" / "supplier-notes" / "acme-2026-03.md").read_text()
    (pkg / "data" / "docs" / "supplier-notes" / "acme-copy.md").write_text(first, encoding="utf-8")
    summary = await sc.sync("supplier-note")
    docs = [d for d in await _rows(sc, DocumentRow) if d.status == "active"]
    assert len(docs) == 4
    assert len({d.id for d in docs}) == 4
    # same identity (supplier+date) -> one note, not two
    assert summary["inserted"] == 2
    assert len(await _link_pairs(sc)) == 2


async def test_unresolved_reference_candidate_cannot_be_accepted(doc_context):
    sc, pkg, _ = doc_context
    add_note(pkg, "unknown2.md", "Ghost Supplier", "2026-08-01", "HIGH")
    await sc.sync("supplier-note")
    candidate = next(c for c in await _rows(sc, ExtractCandidateRow) if c.reason == "UNRESOLVED_REFERENCE")
    from ontogeny.errors import OOError

    with pytest.raises(OOError):
        await sc.documents.accept_candidate(candidate.id, principal="reviewer-1")
