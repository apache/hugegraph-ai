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

"""External-agent extraction: command and HTTP transports, end to end."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from doc_fixtures import add_note, make_context
from ontogeny_ext_agent_extract.adapter import AgentError, AgentExtractor

from ontogeny.config import Settings
from ontogeny.documents.protocol import DocInput, ExtractOptions, ExtractRequest

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_AGENT = ROOT / "tools" / "doc_agent_reference.py"


async def _note(sc, supplier: str):
    async with sc.sessionmaker() as s:
        rows = await sc.repo.query(s, "supplier-note", limit=50)
    return next((r for r in rows[0] if r["supplier_name"] == supplier), None)


async def _pairs(sc):
    async with sc.sessionmaker() as s:
        return await sc.repo.link_members(s, "supplier-risk-note")


@pytest.mark.asyncio
async def test_reference_agent_command_runs_the_full_pipeline(tmp_path):
    cmd = f"{sys.executable} {REFERENCE_AGENT}"
    sc, pkg, _ = await make_context(tmp_path, doc_agent_cmd=cmd)
    agent = AgentExtractor(sc)
    sc.document_extractor = agent
    assert (await agent.health())["transport"] == "command"

    summary = await sc.sync("supplier-note")
    assert summary["inserted"] == 2
    assert summary["links"] == 2
    assert summary["candidates"] == 0
    acme = await _note(sc, "Acme Components")
    assert acme is not None and acme["risk_level"] == "HIGH"
    assert ("SUP-001", acme["note_id"]) in await _pairs(sc)

    detail = await sc.documents.run_detail(summary["run_id"])
    acme_doc = next(d for d in detail["documents"] if d["name"] == "acme-2026-03.md")
    # the exact original text is kept beside the graph for the UI comparison
    assert "fire at the Acme" in acme_doc["chunks"][0]["text"]
    assert any(v["label"] == "supplier-note" for v in acme_doc["chunks"][0]["graph"]["vertices"])

    calls = agent.calls
    again = await sc.sync("supplier-note")
    assert again["noop"] == 2
    assert agent.calls == calls  # packet cache: no second agent call

    # a conflicting note goes to review, not into the object table
    add_note(pkg, "acme-update.md", "Acme Components", "2026-03-01", "MEDIUM", "Updated finding")
    conflict = await sc.sync("supplier-note")
    assert conflict["candidates"] >= 1
    assert (await _note(sc, "Acme Components"))["risk_level"] == "HIGH"


async def test_http_transport_sends_schema_and_binary_documents():
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.append(payload)
        return httpx.Response(
            200,
            json={
                "chunks": [
                    {
                        "doc_id": payload["document"]["id"],
                        "index": 0,
                        "text": "OCR text",
                        "graph": {
                            "vertices": [{"id": "n1", "label": "supplier-note", "properties": {"supplier_name": "A"}}],
                            "edges": [],
                        },
                        "issues": [],
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sc = SimpleNamespace(
        settings=Settings(doc_agent_url="http://agent.test/extract", doc_agent_token="secret"),
        package_root=None,
    )
    agent = AgentExtractor(sc, http=client)
    result = await agent.extract(
        ExtractRequest(
            schema={"vertexlabels": [], "edgelabels": [], "propertykeys": []},
            docs=[
                DocInput(
                    doc_id="d1",
                    path="/tmp/scan.pdf",
                    name="scan.pdf",
                    media_type="application/pdf",
                    content_b64="aGVsbG8=",
                )
            ],
            options=ExtractOptions(language="en"),
        )
    )
    await client.aclose()
    assert result[0].status == "final"
    assert result[0].text == "OCR text"
    assert captured[0]["protocol"] == "ontogeny-doc-agent/v1"
    assert captured[0]["schema"]["vertexlabels"] == []
    assert captured[0]["document"]["content_b64"] == "aGVsbG8="
    assert captured[0]["document"]["text"] == ""
    assert "instructions" in captured[0]


async def test_agent_errors_are_actionable():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "model refused"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sc = SimpleNamespace(settings=Settings(doc_agent_url="http://agent.test/extract"), package_root=None)
    with pytest.raises(AgentError, match="model refused"):
        await AgentExtractor(sc, http=client).extract(
            ExtractRequest(schema={}, docs=[DocInput("d", "/x.md", "text")], options=ExtractOptions())
        )
    await client.aclose()

    def broken(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nope": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(broken))
    with pytest.raises(AgentError, match="chunks"):
        await AgentExtractor(sc, http=client).extract(
            ExtractRequest(schema={}, docs=[DocInput("d", "/x.md", "text")], options=ExtractOptions())
        )
    await client.aclose()


async def test_unconfigured_agent_fails_closed():
    sc = SimpleNamespace(settings=Settings(), package_root=None)
    agent = AgentExtractor(sc)
    assert (await agent.health())["status"] == "unconfigured"
    with pytest.raises(AgentError, match="ONTOGENY_DOC_AGENT"):
        await agent.extract(ExtractRequest(schema={}, docs=[DocInput("d", "/x.md", "text")], options=ExtractOptions()))


async def test_command_failure_includes_stderr():
    sc = SimpleNamespace(
        settings=Settings(doc_agent_cmd=f"{sys.executable} -c \"import sys; sys.stderr.write('boom'); sys.exit(3)\""),
        package_root=None,
    )
    with pytest.raises(AgentError, match="boom"):
        await AgentExtractor(sc).extract(
            ExtractRequest(schema={}, docs=[DocInput("d", "/x.md", "text")], options=ExtractOptions())
        )
