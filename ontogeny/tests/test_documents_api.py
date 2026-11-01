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

"""The HTTP shell of document ingestion: same doors, same governance."""

from __future__ import annotations

import json

import httpx
from doc_fixtures import add_note

from ontogeny.api import build_app

ADMIN = {"X-Ontogeny-Principal": json.dumps({"id": "doc-admin", "is_admin": True})}


async def _client(sc):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=build_app(sc)), base_url="http://test", headers=ADMIN)


async def test_api_corpus_ingest_runs_and_review(doc_context):
    sc, pkg, _ = doc_context
    async with await _client(sc) as c:
        status = (await c.get("/api/v1/admin/documents/status")).json()
        assert status["extractor"] == "loaded"

        stores = (await c.get("/api/v1/admin/documents/stores")).json()["stores"]
        assert [s["name"] for s in stores] == ["supplier-docs"]
        assert stores[0]["object_types"] == ["supplier-note"]

        docs = (await c.get("/api/v1/admin/documents?store=supplier-docs")).json()["documents"]
        assert len(docs) == 3
        assert {d["name"] for d in docs} == {"acme-2026-03.md", "globex-2026-02.md", "note-format.md"}

        # upload the plain-text convenience form (base64 also works)
        up = await c.post(
            "/api/v1/admin/documents/upload",
            json={
                "store": "supplier-docs",
                "files": [
                    {
                        "name": "uploaded.md",
                        "content": (
                            "Supplier: Acme Components\nEffective date: 2026-06-01\n"
                            "Risk level: LOW\nSummary: Re-audit passed.\n"
                        ),
                    }
                ],
            },
        )
        assert up.status_code == 200, up.text
        assert up.json()["written"] == ["supplier-notes/uploaded.md"]

        run = await c.post("/api/v1/admin/documents/ingest", json={"store": "supplier-docs"})
        assert run.status_code == 200, run.text
        summary = run.json()
        assert summary["inserted"] == 3
        assert summary["links"] == 3

        runs = (await c.get("/api/v1/admin/documents/runs?store=supplier-docs")).json()["runs"]
        assert runs[0]["id"] == summary["run_id"]
        detail = (await c.get(f"/api/v1/admin/documents/runs/{summary['run_id']}")).json()
        assert len(detail["documents"]) == 4
        assert any("fire at the Acme" in chunk["text"] for doc in detail["documents"] for chunk in doc["chunks"])

        # a conflicting document parks a candidate; the detail returns BOTH the
        # original chunk and the proposed/current values
        add_note(pkg, "acme-conflict.md", "Acme Components", "2026-03-01", "MEDIUM", "Revised finding")
        second = (await c.post("/api/v1/admin/documents/ingest", json={"store": "supplier-docs"})).json()
        assert second["candidates"] >= 1
        pending = (await c.get("/api/v1/admin/documents/candidates?status=pending&store=supplier-docs")).json()[
            "candidates"
        ]
        assert pending
        conflict = next(x for x in pending if x["reason"] == "CONFLICT" and x["payload"].get("field") == "risk_level")
        detail = (await c.get(f"/api/v1/admin/documents/candidates/{conflict['id']}")).json()
        assert "Acme Components" in detail["chunk"]["text"]
        assert detail["chunk"]["graph"]["vertices"]
        assert detail["current"]["risk_level"] == "HIGH"

        accepted = await c.post(
            f"/api/v1/admin/documents/candidates/{conflict['id']}/accept",
            json={"overrides": {"risk_level": "MEDIUM"}, "note": "confirmed"},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["candidate"]["status"] == "accepted"

        # accepted data is ordinary ontology data: the query surface sees it
        q = await c.post("/api/v1/objects/supplier-note/query", json={"limit": 10})
        assert q.status_code == 200, q.text
        rows = q.json()["objects"]
        assert any(r["risk_level"] == "MEDIUM" and r["supplier_name"] == "Acme Components" for r in rows)


async def test_api_reject_candidate(doc_context):
    sc, pkg, _ = doc_context
    async with await _client(sc) as c:
        await c.post("/api/v1/admin/documents/ingest", json={"store": "supplier-docs"})
        add_note(pkg, "globex-conflict.md", "Globex Materials", "2026-02-14", "HIGH", "Conflicting")
        await c.post("/api/v1/admin/documents/ingest", json={"store": "supplier-docs"})
        pending = (await c.get("/api/v1/admin/documents/candidates?status=pending")).json()["candidates"]
        candidate = next(x for x in pending if x["reason"] == "CONFLICT")
        out = await c.post(
            f"/api/v1/admin/documents/candidates/{candidate['id']}/reject", json={"reason": "not credible"}
        )
        assert out.status_code == 200
        assert out.json()["candidate"]["status"] == "rejected"
        rejected = (await c.get("/api/v1/admin/documents/candidates?status=rejected")).json()["candidates"]
        assert any(x["id"] == candidate["id"] for x in rejected)


async def test_api_dry_run_and_removal(doc_context):
    sc, _, _ = doc_context
    async with await _client(sc) as c:
        preview = (
            await c.post("/api/v1/admin/documents/ingest", json={"store": "supplier-docs", "dry_run": True})
        ).json()
        assert preview["objects"] == 2
        assert preview["preview"]["objects"]
        docs = (await c.get("/api/v1/admin/documents?store=supplier-docs")).json()["documents"]
        assert all(d["extracted_at"] is None for d in docs)

        await c.post("/api/v1/admin/documents/ingest", json={"store": "supplier-docs"})
        target = next(
            d
            for d in (await c.get("/api/v1/admin/documents?store=supplier-docs")).json()["documents"]
            if d["name"] == "acme-2026-03.md"
        )
        removed = await c.delete(f"/api/v1/admin/documents/{target['id']}")
        assert removed.status_code == 200
        assert removed.json()["archived"] == 1


async def test_api_documents_require_admin(doc_context):
    sc, _, _ = doc_context
    headers = {"X-Ontogeny-Principal": json.dumps({"id": "visitor", "Role": ["visitor"]})}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(sc)), base_url="http://test", headers=headers
    ) as c:
        for method, path in (
            ("get", "/api/v1/admin/documents/stores"),
            ("get", "/api/v1/admin/documents?store=supplier-docs"),
            ("post", "/api/v1/admin/documents/ingest"),
        ):
            response = (
                await getattr(c, method)(path, json={"store": "supplier-docs"})
                if method == "post"
                else await getattr(c, method)(path)
            )
            assert response.status_code in (401, 403), (path, response.status_code, response.text)


async def test_api_upload_sanitizes_names_and_rejects_bad_base64(doc_context):
    sc, _, _ = doc_context
    async with await _client(sc) as c:
        out = await c.post(
            "/api/v1/admin/documents/upload",
            json={
                "store": "supplier-docs",
                "files": [
                    {"name": "../../evil.md", "content": "Supplier: Acme Components\nEffective date: 2026-07-01\n"}
                ],
            },
        )
        assert out.status_code == 200, out.text
        assert out.json()["written"] == ["supplier-notes/evil.md"]
        bad = await c.post(
            "/api/v1/admin/documents/upload",
            json={"store": "supplier-docs", "files": [{"name": "bad.md", "content_b64": "not-base64!!"}]},
        )
        assert bad.status_code == 422
        assert bad.json()["code"] == "DOCUMENT_ERROR"


async def test_api_task_create_run_edit_confirm(doc_context):
    sc, _, _ = doc_context
    async with await _client(sc) as c:
        schema = (await c.get("/api/v1/admin/documents/schema?store=supplier-docs")).json()
        assert {o["name"] for o in schema["objects"]} == {"supplier-note"}
        assert any(link["name"] == "supplier-risk-note" for link in schema["links"])
        skills = (await c.get("/api/v1/admin/documents/skills")).json()["skills"]
        assert skills[0]["id"] == "graph-extract"

        created = await c.post(
            "/api/v1/admin/documents/tasks",
            json={
                "store": "supplier-docs",
                "files": [
                    {
                        "name": "api-task.md",
                        "content": (
                            "Supplier: Acme Components\nEffective date: 2026-08-01\n"
                            "Risk level: HIGH\nSummary: staged API task\n"
                        ),
                    }
                ],
                "scope": {
                    "objects": {"supplier-note": ["supplier_name", "effective_date", "risk_level"]},
                    "links": ["supplier-risk-note"],
                },
                "skill": {"id": "graph-extract", "addendum": "API test"},
            },
        )
        assert created.status_code == 200, created.text
        task = created.json()["tasks"][0]
        assert task["status"] == "draft"

        run = await c.post(f"/api/v1/admin/documents/tasks/{task['id']}/run")
        assert run.status_code == 200, run.text
        detail = run.json()
        assert detail["status"] == "review"
        assert detail["attempt"]["graph"]["vertices"]

        async with sc.sessionmaker() as session:
            rows, total = await sc.repo.query(session, "supplier-note", limit=10)
        assert total == 0  # staged, not written

        graph = detail["attempt"]["graph"]
        for vertex in graph["vertices"]:
            if vertex["label"] == "supplier-note":
                vertex["properties"]["risk_level"] = "MEDIUM"
        saved = await c.patch(f"/api/v1/admin/documents/tasks/{task['id']}", json={"graph": graph})
        assert saved.status_code == 200, saved.text
        confirmed = await c.post(f"/api/v1/admin/documents/tasks/{task['id']}/confirm")
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["summary"]["inserted"] == 1

        async with sc.sessionmaker() as session:
            rows, total = await sc.repo.query(session, "supplier-note", limit=10)
        assert total == 1
        assert rows[0]["risk_level"] == "MEDIUM"


async def test_api_task_from_existing_document(doc_context):
    sc, _, _ = doc_context
    async with await _client(sc) as c:
        docs = (await c.get("/api/v1/admin/documents?store=supplier-docs")).json()["documents"]
        acme = next(d for d in docs if d["name"] == "acme-2026-03.md")
        created = await c.post(
            "/api/v1/admin/documents/tasks",
            json={
                "store": "supplier-docs",
                "doc_ids": [acme["id"]],
                "scope": {
                    "objects": {"supplier-note": ["supplier_name", "effective_date", "risk_level"]},
                    "links": ["supplier-risk-note"],
                },
                "skill": {"id": "graph-extract", "addendum": "existing doc"},
            },
        )
        assert created.status_code == 200, created.text
        task = created.json()["tasks"][0]
        assert task["doc_id"] == acme["id"]
        assert task["status"] == "draft"
        # no upload happened: the corpus still has exactly the three shipped docs
        docs2 = (await c.get("/api/v1/admin/documents?store=supplier-docs")).json()["documents"]
        assert len(docs2) == 3
