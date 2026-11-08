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

"""Task-oriented document intelligence.

The legacy ingest path writes as soon as extraction succeeds. This module is
the gated path: a task (one document + one scope + one skill snapshot) runs an
agent attempt into staging, a human can edit the reviewed graph, and only an
explicit confirm binds and writes object/link rows + outbox events.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select

from ..errors import NotFoundError, OOError
from . import corpus, skills
from .binder import Binder
from .models import (
    DocumentAttemptRow,
    DocumentEditRow,
    DocumentRow,
    DocumentTaskRow,
    ExtractCandidateRow,
    ExtractionSkillRow,
    ExtractPacketRow,
    ExtractRunRow,
)
from .protocol import DocInput, ExtractOptions, ExtractRequest
from .schema import compile_extraction_schema

BLOCKING = {
    "NO_IDENTITY",
    "AMBIGUOUS_MATCH",
    "UNRESOLVED_REFERENCE",
    "AMBIGUOUS_REFERENCE",
    "UNRESOLVED_ENDPOINT",
    "WRONG_DIRECTION",
    "MISSING_REQUIRED",
    "TYPE_MISMATCH",
}


class TaskError(OOError):
    code = "DOCUMENT_TASK_ERROR"
    http_status = 422


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _json(value: Any) -> Any:
    if isinstance(value, _dt.datetime | _dt.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json(v) for v in value]
    return value


class TaskService:
    def __init__(self, docs) -> None:
        self.docs = docs
        self.sc = docs.sc

    # ------------------------------------------------------------- helpers

    async def _stored_skills_async(self) -> list[dict[str, Any]]:
        async with self.sc.sessionmaker() as session:
            rows = (
                (await session.execute(select(ExtractionSkillRow).where(ExtractionSkillRow.status == "active")))
                .scalars()
                .all()
            )
        return [
            {
                "id": r.name,
                "name": r.name,
                "display": r.display or r.name,
                "version": r.version,
                "description": r.description,
                "body": r.body,
                "examples": r.examples or [],
            }
            for r in rows
        ]

    def _targets(
        self, store_name: str, scope: dict[str, Any] | None
    ) -> tuple[list[str], dict[str, list[str]] | None, list[str] | None]:
        defaults = self.docs.object_types(store_name)
        if not scope:
            return defaults, None, None
        selected = scope.get("objects")
        if not isinstance(selected, dict) or not selected:
            raise TaskError("scope.objects must be a non-empty object map")
        targets = sorted(selected)
        unknown = [t for t in targets if t not in defaults]
        if unknown:
            raise TaskError(f"scope selects types not backed by store {store_name!r}: {unknown}")
        properties = {name: list(vals) for name, vals in selected.items()}
        links = scope.get("links")
        if links is not None and not isinstance(links, list):
            raise TaskError("scope.links must be an array")
        return targets, properties, links

    def _reference_types(self, targets: list[str], links: list[str] | None) -> list[str]:
        selected = set(links) if links is not None else None
        out: list[str] = []
        for name, lnk in self.docs.compiled.links.items():
            if selected is not None and name not in selected:
                continue
            from ..core.models import ExtractedJoin

            if not isinstance(lnk.spec.join, ExtractedJoin):
                continue
            for endpoint in (lnk.spec.source, lnk.spec.target):
                if endpoint in targets or endpoint in out:
                    continue
                obj = self.docs.compiled.objects.get(endpoint)
                b = obj.spec.backing if obj is not None else None
                if b is not None and b.extract is not None and (b.extract.match or b.extract.key):
                    out.append(endpoint)
        return out

    def _bundle(self, store_name: str, scope: dict[str, Any] | None):
        targets, properties, links = self._targets(store_name, scope)
        refs = self._reference_types(targets, links)
        try:
            return compile_extraction_schema(
                self.docs.compiled,
                targets,
                reference_types=refs,
                properties=properties,
                links=links,
            )
        except ValueError as exc:
            raise TaskError(str(exc)) from exc

    def _doc(self, session, task: DocumentTaskRow) -> DocumentRow:
        doc = session.get(DocumentRow, task.doc_id)
        if doc is None:
            raise NotFoundError(f"document {task.doc_id} not found")
        return doc

    # -------------------------------------------------------------- skills

    async def list_skills(self) -> dict[str, Any]:
        stored = await self._stored_skills_async()
        return {"skills": [skills.GENERIC, *stored]}

    async def create_skill(self, body: dict[str, Any], principal: str) -> dict[str, Any]:
        name = str(body.get("name") or "").strip()
        if not name:
            raise TaskError("skill name is required")
        payload = skills.snapshot(
            {"id": name, "addendum": body.get("body") or "", "examples": body.get("examples") or []}
        )
        async with self.sc.sessionmaker() as session:
            existing = (
                await session.execute(select(ExtractionSkillRow).where(ExtractionSkillRow.name == name))
            ).scalar_one_or_none()
            if existing is not None:
                raise OOError(f"skill {name!r} already exists", code="CONFLICT", http_status=409)
            row = ExtractionSkillRow(
                name=name,
                version=1,
                display=str(body.get("display") or name),
                description=str(body.get("description") or ""),
                body=str(body.get("body") or ""),
                examples=body.get("examples") or [],
                created_by=principal,
            )
            session.add(row)
            await session.commit()
        return {"id": name, "name": name, "version": 1, "snapshot": payload}

    async def _snapshot(self, skill: dict[str, Any] | None) -> dict[str, Any]:
        stored = await self._stored_skills_async()
        try:
            return skills.snapshot(skill, stored)
        except skills.SkillError as exc:
            raise TaskError(str(exc)) from exc

    # --------------------------------------------------------------- scope

    async def schema_options(self, store_name: str) -> dict[str, Any]:
        self.docs.store(store_name)
        targets = self.docs.object_types(store_name)
        objects = []
        for name in targets:
            obj = self.docs.compiled.objects[name]
            cfg = obj.spec.backing.extract if obj.spec.backing is not None else None
            identity = list(cfg.key or []) if cfg else []
            props = []
            for prop, d in obj.spec.properties.items():
                if d.derived is not None:
                    continue
                if d.ptype().kind in ("struct", "vector"):
                    continue
                props.append(
                    {
                        "name": prop,
                        "display": d.display,
                        "type": d.ptype().kind,
                        "required": bool(d.required),
                        "identity": prop in identity or prop == obj.spec.primaryKey[0],
                        "owner": d.owner,
                    }
                )
            objects.append(
                {
                    "name": name,
                    "display": obj.metadata.display or name,
                    "description": obj.metadata.description,
                    "identity": identity,
                    "properties": props,
                }
            )
        links = []
        from ..core.models import ExtractedJoin

        for name, lnk in sorted(self.docs.compiled.links.items()):
            if not isinstance(lnk.spec.join, ExtractedJoin):
                continue
            if lnk.spec.target not in targets:
                continue
            source_ref = lnk.spec.source not in targets
            links.append(
                {
                    "name": name,
                    "display": lnk.metadata.display or name,
                    "source": lnk.spec.source,
                    "target": lnk.spec.target,
                    "source_is_reference": source_ref,
                }
            )
        return {"store": store_name, "objects": objects, "links": links}

    async def preview(self, store_name: str, scope: dict[str, Any] | None) -> dict[str, Any]:
        bundle = self._bundle(store_name, scope)
        return {"schema": bundle.schema, "schema_hash": bundle.hash}

    # --------------------------------------------------------------- tasks

    async def create_tasks(
        self,
        store_name: str,
        files: list[dict[str, str]],
        *,
        doc_ids: list[str] | None = None,
        scope: dict[str, Any] | None,
        skill: dict[str, Any] | None,
        principal: str,
    ) -> dict[str, Any]:
        self.docs.store(store_name)
        if not files and not doc_ids:
            raise TaskError("choose at least one file or existing document")
        bundle = self._bundle(store_name, scope)
        snapshot = await self._snapshot(skill)
        written: list[str] = []
        if files:
            uploaded = await self.docs._upload(store_name, files)
            written = list(uploaded.get("written") or [])
        await self.docs.scan_corpus(store_name)
        root = self.docs._root(self.docs.store(store_name)).resolve()
        paths = {(root / p).resolve() for p in written}
        wanted_ids = set(doc_ids or [])
        async with self.sc.sessionmaker() as session:
            docs = (await session.execute(select(DocumentRow).where(DocumentRow.store == store_name))).scalars().all()
            selected = [d for d in docs if d.id in wanted_ids or Path(d.path).resolve() in paths]
            if not selected:
                raise TaskError("no uploaded or existing document was found")
            if wanted_ids:
                missing = wanted_ids - {d.id for d in selected}
                if missing:
                    raise TaskError(f"unknown document ids: {sorted(missing)}")
            tasks = []
            for doc in selected:
                existing = (
                    (
                        await session.execute(
                            select(DocumentTaskRow)
                            .where(
                                DocumentTaskRow.doc_id == doc.id,
                                DocumentTaskRow.status.in_(("draft", "review", "failed")),
                            )
                            .order_by(DocumentTaskRow.id.desc())
                        )
                    )
                    .scalars()
                    .first()
                )
                if existing is None:
                    latest = (
                        (
                            await session.execute(
                                select(DocumentTaskRow)
                                .where(DocumentTaskRow.doc_id == doc.id)
                                .order_by(DocumentTaskRow.revision.desc(), DocumentTaskRow.id.desc())
                            )
                        )
                        .scalars()
                        .first()
                    )
                    existing = DocumentTaskRow(
                        store=store_name,
                        doc_id=doc.id,
                        status="draft",
                        revision=(latest.revision + 1) if latest is not None else 1,
                        supersedes_task_id=latest.id if latest is not None and latest.status == "confirmed" else None,
                        created_by=principal,
                    )
                    session.add(existing)
                existing.scope = scope
                existing.schema_hash = bundle.hash
                existing.skill = snapshot
                existing.skill_hash = snapshot["hash"]
                existing.error = None
                existing.status = "draft"
                await session.flush()
                tasks.append(self._task_dict(existing, doc))
            await session.commit()
        return {"tasks": tasks, "written": written, "schema_hash": bundle.hash}

    async def list_tasks(self, store_name: str | None = None, status: str | None = None) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            stmt = select(DocumentTaskRow).order_by(DocumentTaskRow.id.desc()).limit(500)
            if store_name:
                stmt = stmt.where(DocumentTaskRow.store == store_name)
            if status:
                stmt = stmt.where(DocumentTaskRow.status == status)
            tasks = (await session.execute(stmt)).scalars().all()
            docs = (
                {
                    d.id: d
                    for d in (
                        await session.execute(select(DocumentRow).where(DocumentRow.id.in_([t.doc_id for t in tasks])))
                    ).scalars()
                }
                if tasks
                else {}
            )
            return {"tasks": [self._task_dict(t, docs.get(t.doc_id)) for t in tasks]}

    def _task_dict(self, task: DocumentTaskRow, doc: DocumentRow | None = None) -> dict[str, Any]:
        return {
            "id": task.id,
            "store": task.store,
            "doc_id": task.doc_id,
            "name": Path(doc.path).name if doc is not None else task.doc_id,
            "path": doc.path if doc is not None else None,
            "status": task.status,
            "revision": task.revision,
            "supersedes_task_id": task.supersedes_task_id,
            "scope": task.scope,
            "schema_hash": task.schema_hash,
            "skill": task.skill,
            "skill_hash": task.skill_hash,
            "current_attempt_id": task.current_attempt_id,
            "confirmed_attempt_id": task.confirmed_attempt_id,
            "created_by": task.created_by,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "confirmed_by": task.confirmed_by,
            "confirmed_at": task.confirmed_at.isoformat() if task.confirmed_at else None,
            "graph_sync_status": task.graph_sync_status,
            "confirm_summary": task.confirm_summary,
            "error": task.error,
        }

    def _attempt_dict(self, attempt: DocumentAttemptRow, *, include_graph: bool = True) -> dict[str, Any]:
        data = {
            "id": attempt.id,
            "task_id": attempt.task_id,
            "attempt_no": attempt.attempt_no,
            "status": attempt.status,
            "agent_run_id": attempt.agent_run_id,
            "provider": attempt.provider,
            "model": attempt.model,
            "schema_hash": attempt.schema_hash,
            "prompt_hash": attempt.prompt_hash,
            "chunks": attempt.chunks or [],
            "issues": attempt.issues or [],
            "validation": attempt.validation or {},
            "error": attempt.error,
            "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
            "finished_at": attempt.finished_at.isoformat() if attempt.finished_at else None,
        }
        if include_graph:
            data["graph"] = attempt.reviewed_graph or attempt.raw_graph or {"vertices": [], "edges": []}
            data["raw_graph"] = attempt.raw_graph or {"vertices": [], "edges": []}
        return data

    async def detail(self, task_id: int) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            task = await session.get(DocumentTaskRow, task_id)
            if task is None:
                raise NotFoundError(f"no task {task_id}")
            doc = await session.get(DocumentRow, task.doc_id)
            attempts = (
                (
                    await session.execute(
                        select(DocumentAttemptRow)
                        .where(DocumentAttemptRow.task_id == task_id)
                        .order_by(DocumentAttemptRow.attempt_no)
                    )
                )
                .scalars()
                .all()
            )
            current = next((a for a in attempts if a.id == task.current_attempt_id), attempts[-1] if attempts else None)
            data = self._task_dict(task, doc)
            data["chunks"] = current.chunks if current is not None else []
            data["attempt"] = self._attempt_dict(current) if current is not None else None
            data["attempts"] = [self._attempt_dict(a, include_graph=False) for a in attempts]
            return data

    # ---------------------------------------------------------------- agent

    async def _agent_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        extractor = self.docs._extractor()
        if extractor is None:
            raise TaskError("no document extractor is configured")
        doc = payload["document"]
        request = ExtractRequest(
            schema=payload["schema"],
            docs=[
                DocInput(
                    doc_id=doc["doc_id"],
                    path=doc["path"],
                    text=doc.get("text") or "",
                    name=doc.get("name") or "",
                    media_type=doc.get("media_type"),
                    content_b64=doc.get("content_b64"),
                )
            ],
            options=ExtractOptions(
                split=payload.get("split", "paragraph"),
                language=payload.get("language", "en"),
                max_chunks_per_doc=int(payload.get("max_chunks_per_doc", 200)),
                instructions=payload.get("instructions"),
            ),
        )
        results = await extractor.extract(request)
        return {
            "chunks": [
                {
                    "doc_id": r.doc_id,
                    "index": r.index,
                    "text": r.text,
                    "graph": r.graph,
                    "issues": r.issues,
                    "status": r.status,
                    "reason": r.reason,
                }
                for r in results
            ]
        }

    async def _run_agent(self, payload: dict[str, Any], *, principal: str, task: str) -> dict[str, Any]:
        # The extractor runs out-of-process over the doc-agent protocol; the
        # agent broker's governed surface (sessions + call_tool) is for
        # ontology tools, not extraction payloads.
        return {"output": await self._agent_task(payload), "agent_run_id": None, "provider": "direct"}

    # ---------------------------------------------------------------- run

    async def run(self, task_id: int, principal: str) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            task = await session.get(DocumentTaskRow, task_id)
            if task is None:
                raise NotFoundError(f"no task {task_id}")
            if task.status == "confirmed":
                raise TaskError("confirmed task is immutable; rerun creates a new revision")
            doc = await session.get(DocumentRow, task.doc_id)
            if doc is None:
                raise NotFoundError(f"document {task.doc_id} not found")
            bundle = self._bundle(task.store, task.scope)
            last = (
                await session.execute(
                    select(func.max(DocumentAttemptRow.attempt_no)).where(DocumentAttemptRow.task_id == task_id)
                )
            ).scalar_one()
            attempt = DocumentAttemptRow(
                task_id=task_id,
                attempt_no=int(last or 0) + 1,
                status="running",
                schema_hash=bundle.hash,
                prompt_hash=task.skill_hash,
            )
            session.add(attempt)
            await session.flush()
            task.current_attempt_id = attempt.id
            task.status = "running"
            task.schema_hash = bundle.hash
            task.error = None
            await session.commit()
            task_id, attempt_id = task.id, attempt.id
            doc_payload = {
                "doc_id": doc.id,
                "path": doc.path,
                "name": Path(doc.path).name,
                "media_type": doc.media_type,
                "text": "",
                "content_b64": None,
            }
            path = Path(doc.path)
            text, content_b64 = corpus.read_for_agent(path)
            doc_payload["text"] = text
            doc_payload["content_b64"] = content_b64
            skill = task.skill or {}
            cfg = self.docs._cfg(self.docs.store(task.store))
            payload = {
                "schema": bundle.schema,
                "document": doc_payload,
                "split": cfg.split,
                "language": skill.get("language") or cfg.language,
                "max_chunks_per_doc": cfg.max_chunks_per_doc,
                "instructions": skills.instructions(skill) if skill else self.docs._instructions(cfg),
            }
        try:
            result = await self._run_agent(payload, principal=principal, task=f"task:{task_id}")
            chunks = list((result.get("output") or {}).get("chunks") or [])
            vertices: list[Any] = []
            edges: list[Any] = []
            seen_edges: set[tuple[str, str, str]] = set()
            for chunk in chunks:
                graph = chunk.get("graph") if isinstance(chunk, dict) else None
                if isinstance(graph, dict):
                    chunk_vertices = graph.get("vertices") or []
                    chunk_edges = graph.get("edges") or []
                elif isinstance(chunk, dict) and isinstance(chunk.get("vertices"), list):
                    chunk_vertices = chunk.get("vertices") or []
                    chunk_edges = chunk.get("edges") or []
                else:
                    continue
                # Every occurrence carries evidence: later chunks can add
                # properties or disagree. The binder reconciles identities;
                # the graph preview separately deduplicates display node IDs.
                vertices.extend(chunk_vertices)
                for edge in chunk_edges:
                    if isinstance(edge, dict):
                        key = (
                            str(edge.get("label")),
                            str(edge.get("outV")),
                            str(edge.get("inV")),
                        )
                        if key in seen_edges:
                            continue
                        seen_edges.add(key)
                    edges.append(edge)
            graph = {"vertices": vertices, "edges": edges}
            validation = await self._validate(task_id, graph, bundle)
            async with self.sc.sessionmaker() as session:
                attempt = await session.get(DocumentAttemptRow, attempt_id)
                task = await session.get(DocumentTaskRow, task_id)
                attempt.status = "review"
                attempt.agent_run_id = result.get("agent_run_id")
                attempt.provider = result.get("provider")
                attempt.raw_graph = graph
                attempt.reviewed_graph = graph
                attempt.chunks = chunks
                attempt.validation = validation
                attempt.finished_at = _dt.datetime.now(_dt.UTC)
                task.status = "review"
                await session.commit()
            return await self.detail(task_id)
        except Exception as exc:
            async with self.sc.sessionmaker() as session:
                attempt = await session.get(DocumentAttemptRow, attempt_id)
                task = await session.get(DocumentTaskRow, task_id)
                if attempt is not None:
                    attempt.status = "failed"
                    attempt.error = f"{type(exc).__name__}: {exc}"[:4000]
                    attempt.finished_at = _dt.datetime.now(_dt.UTC)
                if task is not None:
                    task.status = "failed"
                    task.error = f"{type(exc).__name__}: {exc}"[:4000]
                await session.commit()
            raise

    # ----------------------------------------------------------- validation

    async def _validate(self, task_id: int, graph: dict[str, Any], bundle) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            task = await session.get(DocumentTaskRow, task_id)
            if task is None:
                raise NotFoundError(f"no task {task_id}")
            doc = await session.get(DocumentRow, task.doc_id)
            text = ""
            async with self.sc.sessionmaker() as s:
                attempt = await s.get(DocumentAttemptRow, task.current_attempt_id) if task.current_attempt_id else None
                if attempt is not None:
                    text = "\n\n".join(str(c.get("text") or "") for c in (attempt.chunks or []) if isinstance(c, dict))
            if not text and doc is not None:
                text, _ = corpus.read_for_agent(Path(doc.path))
            packet = SimpleNamespace(doc_id=task.doc_id, chunk_index=0, text=text)
            binder = Binder(self.docs.compiled, bundle, self.docs.sc.repo, session, run_id=0)
            outcome = await binder.bind([(packet, graph)])
        blockers = []
        warnings = []
        for cand in outcome.candidates:
            item = {
                "reason": cand.reason,
                "kind": cand.kind,
                "object_type": cand.object_type,
                "link": cand.link,
                "payload": _json(cand.payload),
            }
            (blockers if cand.reason in BLOCKING else warnings).append(item)
        for reject in outcome.rejected:
            blockers.append(
                {"reason": reject.code, "kind": "object", "message": reject.reason, "payload": _json(reject.row)}
            )
        for gap in outcome.gaps:
            warnings.append({"reason": "SCHEMA_GAP", "message": gap})
        return {
            "blockers": blockers,
            "warnings": warnings,
            "objects": len(outcome.objects),
            "links": len(outcome.links),
            "references": [list(x) for x in outcome.references],
            "gaps": outcome.gaps[:50],
        }

    # --------------------------------------------------------------- edit

    async def save_graph(self, task_id: int, graph: dict[str, Any], principal: str) -> dict[str, Any]:
        if (
            not isinstance(graph, dict)
            or not isinstance(graph.get("vertices"), list)
            or not isinstance(graph.get("edges"), list)
        ):
            raise TaskError("graph must contain vertices[] and edges[]")
        async with self.sc.sessionmaker() as session:
            task = await session.get(DocumentTaskRow, task_id)
            if task is None:
                raise NotFoundError(f"no task {task_id}")
            if task.status == "confirmed":
                raise TaskError("confirmed task is immutable")
            attempt = (
                await session.get(DocumentAttemptRow, task.current_attempt_id) if task.current_attempt_id else None
            )
            if attempt is None:
                raise TaskError("run the task before editing its graph")
            before = attempt.reviewed_graph
            attempt.reviewed_graph = graph
            attempt.validation = await self._validate(task_id, graph, self._bundle(task.store, task.scope))
            session.add(
                DocumentEditRow(
                    attempt_id=attempt.id,
                    actor=principal,
                    op="replace_graph",
                    path="graph",
                    before=before,
                    after=graph,
                )
            )
            task.status = "review"
            await session.commit()
        return await self.detail(task_id)

    # ------------------------------------------------------------- confirm

    async def confirm(self, task_id: int, principal: str) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            task = await session.get(DocumentTaskRow, task_id)
            if task is None:
                raise NotFoundError(f"no task {task_id}")
            if task.status == "confirmed":
                return {"task": await self.detail(task_id), "already": True}
            if task.current_attempt_id is None:
                raise TaskError("task has no attempt to confirm")
            attempt = await session.get(DocumentAttemptRow, task.current_attempt_id)
            if attempt is None:
                raise TaskError("current attempt is missing")
            graph = attempt.reviewed_graph or attempt.raw_graph or {"vertices": [], "edges": []}
            if not (graph.get("vertices") or graph.get("edges")):
                raise TaskError("graph is empty; nothing to confirm")
            bundle = self._bundle(task.store, task.scope)
            validation = await self._validate(task_id, graph, bundle)
            if validation["blockers"]:
                raise TaskError(
                    "task has unresolved blockers; fix the graph before confirming",
                    details={"blockers": validation["blockers"]},
                )
            doc = await session.get(DocumentRow, task.doc_id)
            text = "\n\n".join(str(c.get("text") or "") for c in (attempt.chunks or []) if isinstance(c, dict))
            if not text and doc is not None:
                text, _ = corpus.read_for_agent(Path(doc.path))
            packet = SimpleNamespace(doc_id=task.doc_id, chunk_index=0, text=text)
            # Attempt ids and extraction run ids are independent sequences.
            # Create a real run so candidates and provenance cannot collide
            # with an unrelated ingest run that happens to have the same id.
            run = ExtractRunRow(
                store=task.store,
                status="running",
                schema_hash=attempt.schema_hash,
                prompt_hash=attempt.prompt_hash,
                model=attempt.model,
                n_documents=1,
                n_chunks=max(1, len(attempt.chunks or [])),
            )
            session.add(run)
            await session.flush()
            # Preserve the agent's raw chunks in the run detail. The reviewed
            # graph stays on the attempt and may differ after a human edit.
            chunks = attempt.chunks or [{"text": text, "graph": attempt.raw_graph}]
            for index, chunk in enumerate(chunks):
                chunk = chunk if isinstance(chunk, dict) else {}
                chunk_text = str(chunk.get("text") or "")
                chunk_graph = chunk.get("graph") or {
                    "vertices": chunk.get("vertices") or [],
                    "edges": chunk.get("edges") or [],
                }
                session.add(
                    ExtractPacketRow(
                        run_id=run.id,
                        doc_id=task.doc_id,
                        doc_hash=task.doc_id,
                        chunk_index=index,
                        chunk_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
                        schema_hash=attempt.schema_hash or "",
                        prompt_hash=attempt.prompt_hash or "",
                        model=attempt.model,
                        text=chunk_text,
                        graph=_json(chunk_graph),
                        issues=_json(chunk.get("issues") or []),
                        status="task-raw",
                    )
                )
            binder = Binder(self.docs.compiled, bundle, self.docs.sc.repo, session, run_id=run.id)
            outcome = await binder.bind([(packet, graph)])
            applied: set[tuple[str, str]] = set()
            summary = {"inserted": 0, "updated": 0, "noop": 0, "links": 0, "candidates": 0}
            for bound in outcome.objects.values():
                current = await self.docs.sc.repo.get(session, bound.object_type, bound.object_id)
                if current is not None:
                    applied.add((bound.object_type, bound.object_id))
                result = await self.docs._write_object(
                    session,
                    bound,
                    run_id=run.id,
                    principal=principal,
                    created_by=bound.created_by,
                    action="ingest.confirm",
                )
                if result == "inserted":
                    applied.add((bound.object_type, bound.object_id))
                    summary["inserted"] += 1
                elif result == "updated":
                    applied.add((bound.object_type, bound.object_id))
                    summary["updated"] += 1
                elif result == "noop":
                    summary["noop"] += 1
            applied |= outcome.references
            summary["links"] = await self.docs._apply_links(
                session,
                run,
                outcome,
                applied_ids=applied,
                doc_ids={task.doc_id},
                link_names=set(bundle.link_labels.values()),
                principal=principal,
            )
            for cand in outcome.candidates:
                await self.docs._candidate(
                    session,
                    run.id,
                    cand.doc_id,
                    cand.chunk_index,
                    cand.kind,
                    cand.reason,
                    cand.payload,
                    object_type=cand.object_type,
                    link=cand.link,
                    object_id=cand.object_id,
                )
            pending = (
                (await session.execute(select(ExtractCandidateRow).where(ExtractCandidateRow.run_id == run.id)))
                .scalars()
                .all()
            )
            summary["candidates"] = len(pending)
            summary["graph_hash"] = _sha(graph)
            run.status = "ok"
            run.n_objects = len(outcome.objects)
            run.n_inserted = summary["inserted"]
            run.n_updated = summary["updated"]
            run.n_noop = summary["noop"]
            run.n_links = summary["links"]
            run.n_candidates = summary["candidates"]
            run.finished_at = _dt.datetime.now(_dt.UTC)
            attempt.status = "confirmed"
            attempt.finished_at = _dt.datetime.now(_dt.UTC)
            task.status = "confirmed"
            task.confirmed_attempt_id = attempt.id
            task.confirmed_by = principal
            task.confirmed_at = _dt.datetime.now(_dt.UTC)
            task.graph_sync_status = "confirmed"
            task.confirm_summary = summary
            # The task path is the only writer for staged imports, so the
            # document row is the one place the console reads "how much of this
            # file is in the graph" from -- leaving it at 0 chunks after a
            # confirmed task reads as "nothing was imported".
            if doc is not None:
                doc.extracted_at = _dt.datetime.now(_dt.UTC)
                doc.chunk_count = max(1, len(attempt.chunks or []))
            if task.supersedes_task_id:
                old = await session.get(DocumentTaskRow, task.supersedes_task_id)
                if old is not None:
                    old.status = "superseded"
            await session.commit()
            result = {"summary": summary, "task": await self.detail(task_id), "already": False}
        return result

    async def reconfigure(
        self,
        task_id: int,
        *,
        scope: dict[str, Any],
        skill: dict[str, Any] | None,
        principal: str,
    ) -> dict[str, Any]:
        """Update a task's extraction scope/skill, preserving confirmed history.

        A confirmed task is immutable, so reconfiguration opens the next
        revision instead of rewriting the audited attempt. A draft/review task
        is updated in place and its stale attempt is detached; the UI can then
        run the new configuration.
        """
        async with self.sc.sessionmaker() as session:
            task = await session.get(DocumentTaskRow, task_id)
            if task is None:
                raise NotFoundError(f"no task {task_id}")
            if task.status == "superseded":
                raise TaskError("superseded task cannot be reconfigured")
            bundle = self._bundle(task.store, scope)
            snapshot = await self._snapshot(skill)
            if task.status == "confirmed":
                latest = (
                    (
                        await session.execute(
                            select(DocumentTaskRow)
                            .where(DocumentTaskRow.doc_id == task.doc_id)
                            .order_by(DocumentTaskRow.revision.desc(), DocumentTaskRow.id.desc())
                        )
                    )
                    .scalars()
                    .first()
                )
                new = DocumentTaskRow(
                    store=task.store,
                    doc_id=task.doc_id,
                    status="draft",
                    revision=(latest.revision + 1) if latest is not None else task.revision + 1,
                    supersedes_task_id=task.id,
                    scope=scope,
                    schema_hash=bundle.hash,
                    skill=snapshot,
                    skill_hash=snapshot["hash"],
                    created_by=principal,
                )
                session.add(new)
                await session.flush()
                new_id = new.id
                await session.commit()
                return await self.detail(new_id)
            task.scope = scope
            task.schema_hash = bundle.hash
            task.skill = snapshot
            task.skill_hash = snapshot["hash"]
            task.status = "draft"
            task.current_attempt_id = None
            task.error = None
            await session.commit()
            return await self.detail(task_id)

    async def rerun(self, task_id: int, principal: str) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            task = await session.get(DocumentTaskRow, task_id)
            if task is None:
                raise NotFoundError(f"no task {task_id}")
            if task.status != "confirmed":
                return {"task": await self.run(task_id, principal), "revision": task.revision}
            new = DocumentTaskRow(
                store=task.store,
                doc_id=task.doc_id,
                status="draft",
                revision=task.revision + 1,
                supersedes_task_id=task.id,
                scope=task.scope,
                schema_hash=task.schema_hash,
                skill=task.skill,
                skill_hash=task.skill_hash,
                created_by=principal,
            )
            session.add(new)
            await session.flush()
            new_id = new.id
            await session.commit()
        return {"task": await self.detail(new_id), "revision": task.revision + 1}
