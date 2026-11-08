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

"""Task staging: run/review/confirm, local scope, blockers, rerun."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest
from doc_fixtures import make_context
from sqlalchemy import select

from ontogeny.action.models import OutboxRow
from ontogeny.documents.models import DocumentRow, ExtractCandidateRow, ExtractRunRow
from ontogeny.documents.tasks import TaskError

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_AGENT = ROOT / "tools" / "doc_agent_reference.py"


def _file(name: str, text: str) -> list[dict[str, str]]:
    return [{"name": name, "content_b64": base64.b64encode(text.encode()).decode()}]


NOTE = """Supplier: Acme Components
Effective date: 2026-07-01
Risk level: HIGH
Summary: staged task note
"""


async def _notes(sc):
    async with sc.sessionmaker() as s:
        rows, total = await sc.repo.query(s, "supplier-note", limit=20)
    return rows, total


async def test_task_is_staged_until_confirm_and_edits_apply(doc_context):
    sc, _, _ = doc_context
    await sc.sync("supplier")
    created = await sc.documents.tasks.create_tasks(
        "supplier-docs",
        _file("task-note.md", NOTE),
        scope={
            "objects": {"supplier-note": ["supplier_name", "effective_date", "risk_level"]},
            "links": ["supplier-risk-note"],
        },
        skill={"id": "graph-extract", "addendum": "Only the risk memo fields."},
        principal="tester",
    )
    task_id = created["tasks"][0]["id"]
    detail = await sc.documents.tasks.run(task_id, "tester")
    assert detail["status"] == "review"
    assert detail["attempt"]["graph"]["vertices"]
    assert detail["attempt"]["validation"]["blockers"] == []

    # the local schema excludes summary even though the extractor returned it
    _rows, total = await _notes(sc)
    assert total == 0  # staging wrote nothing

    graph = detail["attempt"]["graph"]
    for vertex in graph["vertices"]:
        if vertex["label"] == "supplier-note":
            vertex["properties"]["risk_level"] = "MEDIUM"
    saved = await sc.documents.tasks.save_graph(task_id, graph, "tester")
    assert saved["status"] == "review"
    confirmed = await sc.documents.tasks.confirm(task_id, "tester")
    assert confirmed["task"]["status"] == "confirmed"
    assert confirmed["summary"]["inserted"] == 1

    rows, total = await _notes(sc)
    assert total == 1
    assert rows[0]["risk_level"] == "MEDIUM"
    assert "summary" not in rows[0] or rows[0]["summary"] in (None, "")
    async with sc.sessionmaker() as session:
        outbox = (
            (await session.execute(select(OutboxRow).where(OutboxRow.object_id == rows[0]["note_id"]))).scalars().all()
        )
    assert outbox  # confirming is what emits the projection event
    # the corpus row must reflect the confirmed import: 0 chunks after a
    # confirmed task reads as "nothing was imported" in the console
    async with sc.sessionmaker() as session:
        doc = await session.get(DocumentRow, created["tasks"][0]["doc_id"])
    assert doc is not None
    assert doc.chunk_count >= 1
    assert doc.extracted_at is not None
    assert (await sc.documents.tasks.confirm(task_id, "tester"))["already"] is True


async def test_unresolved_reference_blocks_confirm(doc_context):
    sc, _, _ = doc_context
    await sc.sync("supplier")
    ghost = NOTE.replace("Acme Components", "Ghost Supplier")
    created = await sc.documents.tasks.create_tasks(
        "supplier-docs",
        _file("ghost.md", ghost),
        scope=None,
        skill=None,
        principal="tester",
    )
    task_id = created["tasks"][0]["id"]
    detail = await sc.documents.tasks.run(task_id, "tester")
    reasons = {b["reason"] for b in detail["attempt"]["validation"]["blockers"]}
    assert "UNRESOLVED_REFERENCE" in reasons
    with pytest.raises(TaskError):
        await sc.documents.tasks.confirm(task_id, "tester")
    _rows, total = await _notes(sc)
    assert total == 0


async def test_task_confirmation_does_not_share_an_ingest_run_id(doc_context):
    sc, _, _ = doc_context
    await sc.sync("supplier")
    async with sc.sessionmaker() as session:
        unrelated_run = ExtractRunRow(store="other-store", status="ok")
        session.add(unrelated_run)
        await session.flush()
        session.add(ExtractCandidateRow(run_id=unrelated_run.id, doc_id="other", kind="object", status="pending"))
        await session.commit()
        unrelated_id = unrelated_run.id

    created = await sc.documents.tasks.create_tasks(
        "supplier-docs", _file("task-note.md", NOTE), scope=None, skill=None, principal="tester"
    )
    task_id = created["tasks"][0]["id"]
    detail = await sc.documents.tasks.run(task_id, "tester")
    assert detail["attempt"]["id"] == unrelated_id
    confirmed = await sc.documents.tasks.confirm(task_id, "tester")
    assert confirmed["summary"]["candidates"] == 0
    async with sc.sessionmaker() as session:
        runs = (
            (await session.execute(select(ExtractRunRow).where(ExtractRunRow.store == "supplier-docs"))).scalars().all()
        )
    assert len(runs) == 1
    assert runs[0].id != unrelated_id
    assert runs[0].status == "ok"
    assert runs[0].n_inserted == 1
    run_detail = await sc.documents.run_detail(runs[0].id)
    assert len(run_detail["documents"]) == 1
    assert run_detail["documents"][0]["doc_id"] == created["tasks"][0]["doc_id"]
    assert len(run_detail["documents"][0]["chunks"]) == runs[0].n_chunks
    assert all(chunk["status"] == "task-raw" for chunk in run_detail["documents"][0]["chunks"])


async def test_rerun_after_confirm_creates_a_revision(doc_context):
    sc, _, _ = doc_context
    await sc.sync("supplier")
    created = await sc.documents.tasks.create_tasks(
        "supplier-docs", _file("rev.md", NOTE), scope=None, skill=None, principal="tester"
    )
    task_id = created["tasks"][0]["id"]
    await sc.documents.tasks.run(task_id, "tester")
    await sc.documents.tasks.confirm(task_id, "tester")
    rerun = await sc.documents.tasks.rerun(task_id, "tester")
    assert rerun["task"]["revision"] == 2
    assert rerun["task"]["supersedes_task_id"] == task_id
    old = await sc.documents.tasks.detail(task_id)
    assert old["status"] == "confirmed"  # only flips when the revision confirms


async def test_task_runs_the_configured_agent_command_directly(tmp_path):
    """After the mainline broker refactor (sessions + call_tool only), the
    extractor runs the doc-agent protocol out-of-process — no agent session is
    created for an extraction payload, and the attempt records the direct run."""
    cmd = f"{sys.executable} {REFERENCE_AGENT}"
    sc, _, _ = await make_context(tmp_path, doc_agent_cmd=cmd)
    await sc.sync("supplier")
    created = await sc.documents.tasks.create_tasks(
        "supplier-docs", _file("agent-task.md", NOTE), scope=None, skill=None, principal="tester"
    )
    task_id = created["tasks"][0]["id"]
    detail = await sc.documents.tasks.run(task_id, "tester")
    assert detail["attempt"]["agent_run_id"] is None
    assert detail["attempt"]["provider"] == "direct"
    sessions = await sc.agents.list_sessions()
    assert not any(s.get("plugin") == "doc-extract" for s in sessions)
    assert any(c["label"] == "supplier-note" for c in detail["attempt"]["graph"]["vertices"])


async def test_empty_graph_cannot_be_confirmed(doc_context):
    sc, _, _ = doc_context
    await sc.sync("supplier")
    created = await sc.documents.tasks.create_tasks(
        "supplier-docs",
        _file("blank.md", "# an API page with no supplier facts\n"),
        scope=None,
        skill=None,
        principal="tester",
    )
    task_id = created["tasks"][0]["id"]
    detail = await sc.documents.tasks.run(task_id, "tester")
    assert detail["attempt"]["graph"] == {"vertices": [], "edges": []}
    with pytest.raises(TaskError, match="empty"):
        await sc.documents.tasks.confirm(task_id, "tester")


async def test_default_document_source_is_created_once(tmp_path):
    import shutil

    from ontogeny.config import Settings
    from ontogeny.service import ServiceContext

    pkg = tmp_path / "pkg"
    shutil.copytree(ROOT / "domains" / "chip-lifecycle", pkg)
    # the demo now ships a default source; this test exercises the scaffold path
    # by removing chip-lifecycle's own document resources first
    (pkg / "stores" / "chip-docs.yaml").unlink(missing_ok=True)
    (pkg / "objects" / "fmea-note.yaml").unlink(missing_ok=True)
    (pkg / "links" / "design-fmea-notes.yaml").unlink(missing_ok=True)
    for agent_name in ("product-copilot.yaml", "fab-copilot.yaml", "cqe-copilot.yaml"):
        agent = pkg / "agents" / agent_name
        agent.write_text(agent.read_text().replace("    - search_fmea_note\n", ""))
    shutil.rmtree(pkg / "data" / "docs", ignore_errors=True)
    (pkg / "projections" / "lifecycle-graph.yaml").unlink(missing_ok=True)
    settings = Settings(
        db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}",
        dev_auth=True,
        extensions_dir=str(tmp_path / "ext"),
        env={"ERP_DSN": f"sqlite+aiosqlite:///{tmp_path / 'erp.db'}"},
    )
    (tmp_path / "ext").mkdir()
    sc = ServiceContext(settings, str(pkg))
    await sc.initialize()
    first = await sc.documents.ensure_default_source()
    assert first["created"] is True
    assert (pkg / "stores" / "documents.yaml").is_file()
    assert (pkg / "objects" / "document-note.yaml").is_file()
    assert "document-note" in sc.compiled.objects
    second = await sc.documents.ensure_default_source()
    assert second["created"] is False


async def test_reconfigure_confirmed_task_opens_a_new_revision(doc_context):
    sc, _, _ = doc_context
    await sc.sync("supplier")
    created = await sc.documents.tasks.create_tasks(
        "supplier-docs", _file("reconfigure.md", NOTE), scope=None, skill=None, principal="tester"
    )
    task_id = created["tasks"][0]["id"]
    await sc.documents.tasks.run(task_id, "tester")
    await sc.documents.tasks.confirm(task_id, "tester")
    next_task = await sc.documents.tasks.reconfigure(
        task_id,
        scope={
            "objects": {"supplier-note": ["supplier_name", "risk_level"]},
            "links": ["supplier-risk-note"],
        },
        skill={"id": "graph-extract", "addendum": "Re-extract with the narrowed scope."},
        principal="tester",
    )
    assert next_task["id"] != task_id
    assert next_task["revision"] == 2
    assert next_task["supersedes_task_id"] == task_id
    assert next_task["status"] == "draft"
    assert next_task["scope"]["objects"]["supplier-note"] == ["supplier_name", "risk_level"]
    assert next_task["skill"]["addendum"] == "Re-extract with the narrowed scope."
    old = await sc.documents.tasks.detail(task_id)
    assert old["status"] == "confirmed"

    detail = await sc.documents.tasks.run(next_task["id"], "tester")
    assert detail["status"] == "review"
    assert detail["attempt"]["validation"]["blockers"] == []
