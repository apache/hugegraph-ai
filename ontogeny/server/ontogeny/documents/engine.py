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

"""Document ingestion orchestration: corpus -> packets -> objects -> review.

The engine owns the only place where agent output becomes platform data. Two
rules drive the whole module:

* an extraction run is *replayable*: packets are persisted and re-bound without
  another model call, so an ontology change is a rebind, not a re-bill;
* nothing ambiguous is written silently: missing identity, conflicting values
  and unresolved edge endpoints become review candidates.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from ..action.models import OutboxRow, RevisionRow
from ..core.models import DocumentCfg, ExtractCfg, ExtractedJoin
from ..errors import NotFoundError, OOError, StoreError
from ..stores.repo import utcnow
from . import corpus
from .binder import Binder, BoundObject, _jsonable
from .models import (
    DocumentRow,
    ExtractAssertionRow,
    ExtractCandidateRow,
    ExtractOriginRow,
    ExtractPacketRow,
    ExtractRunRow,
)
from .protocol import DocInput, ExtractOptions, ExtractRequest
from .schema import compile_extraction_schema

log = logging.getLogger("ontogeny.documents")

PROMPT_VERSION = "ontogeny-doc-extract/v1"


class DocumentError(OOError):
    code = "DOCUMENT_ERROR"
    http_status = 422


def _valid(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DocumentService:
    def __init__(self, sc) -> None:
        self.sc = sc
        self._locks: dict[str, Any] = {}
        from .tasks import TaskService

        self.tasks = TaskService(self)

    # --------------------------------------------------------------- helpers

    @property
    def compiled(self):
        return self.sc.compiled

    def _extractor(self):
        return getattr(self.sc, "document_extractor", None)

    def document_stores(self) -> list[Any]:
        return sorted(
            (s for s in self.compiled.stores.values() if s.spec.type == "document"),
            key=lambda s: s.metadata.name,
        )

    def store(self, name: str):
        store = self.compiled.stores.get(name)
        if store is None or store.spec.type != "document":
            raise NotFoundError(f"no document store named {name!r}")
        return store

    def object_types(self, store_name: str) -> list[str]:
        out = []
        for name, obj in self.compiled.objects.items():
            b = obj.spec.backing
            if b is not None and b.store == store_name and b.sync is not None and b.sync.strategy == "extract":
                out.append(name)
        return sorted(out)

    def _cfg(self, store) -> DocumentCfg:
        return store.spec.documents or DocumentCfg()

    def _root(self, store) -> Path:
        return corpus.resolve_root(store, self.sc.package_root)

    def _instructions(self, cfg: DocumentCfg) -> str | None:
        if not cfg.prompt_file:
            return None
        root = self.sc.package_root
        if not root:
            raise DocumentError("prompt_file requires ONTOGENY_PACKAGE_ROOT")
        path = (Path(root) / cfg.prompt_file).resolve()
        if not str(path).startswith(str(Path(root).resolve())):
            raise DocumentError("prompt_file must stay inside the package root")
        if not path.is_file():
            raise DocumentError(f"prompt_file not found: {cfg.prompt_file}")
        return path.read_text(encoding="utf-8")

    # ------------------------------------------------------- default source

    async def ensure_default_source(self) -> dict[str, Any]:
        """Create a generic document corpus when the package has none.

        This is an explicit admin action, not a silent page-load write: adding
        an object type changes the ontology, so the caller must ask for it.
        """
        existing = self.document_stores()
        if existing:
            return {"created": False, "store": existing[0].metadata.name}
        root = self.sc.package_root
        if not root:
            raise DocumentError("ONTOGENY_PACKAGE_ROOT is not set; cannot create a default source")
        package = Path(root)
        stores_dir = package / "stores"
        objects_dir = package / "objects"
        stores_dir.mkdir(parents=True, exist_ok=True)
        objects_dir.mkdir(parents=True, exist_ok=True)
        store_name = "documents"
        suffix = 2
        while (stores_dir / f"{store_name}.yaml").exists() or store_name in self.compiled.stores:
            store_name = f"documents-{suffix}"
            suffix += 1
        if (stores_dir / f"{store_name}.yaml").exists():
            raise DocumentError(f"store resource {store_name!r} already exists")
        type_name = "document-note"
        suffix = 2
        while (objects_dir / f"{type_name}.yaml").exists() or type_name in self.compiled.objects:
            type_name = f"document-note-{suffix}"
            suffix += 1
        store_yaml = f"""apiVersion: ontogeny/v1
kind: Store
metadata:
  name: {store_name}
  display: Documents
  description: Default document corpus for document intelligence
spec:
  type: document
  connection: data/docs
  documents:
    include:
      - "**/*.md"
      - "**/*.txt"
      - "**/*.pdf"
      - "**/*.docx"
    split: paragraph
    language: en
"""
        type_yaml = f"""apiVersion: ontogeny/v1
kind: ObjectType
metadata:
  name: {type_name}
  display: Document note
  description: A fact extracted from a document
spec:
  primaryKey: [note_id]
  properties:
    note_id:
      type: string
      display: Note ID
      required: true
      owner: document
    title:
      type: string
      display: Title
      required: true
      owner: document
    summary:
      type: string
      display: Summary
      owner: document
    body:
      type: string
      display: Body
      owner: document
  backing:
    store: {store_name}
    mode: materialized
    source:
      table: document-notes
    sync:
      strategy: extract
    extract:
      key: [title]
      match: [title]
      create: auto
      update: fill-empty
"""
        (stores_dir / f"{store_name}.yaml").write_text(store_yaml, encoding="utf-8")
        (objects_dir / f"{type_name}.yaml").write_text(type_yaml, encoding="utf-8")
        (package / "data" / "docs").mkdir(parents=True, exist_ok=True)
        await self.sc.publish(package)
        return {"created": True, "store": store_name, "object_type": type_name}

    # ---------------------------------------------------------------- corpus

    async def _sync_documents(
        self, session, store, cfg, scanned: list[corpus.ScannedDocument]
    ) -> tuple[list[DocumentRow], list[str]]:
        rows = (
            (await session.execute(select(DocumentRow).where(DocumentRow.store == store.metadata.name))).scalars().all()
        )
        by_path = {str(r.path): r for r in rows if r.status == "active"}
        now = utcnow()
        active: list[DocumentRow] = []
        changed: list[DocumentRow] = []
        seen: set[str] = set()
        for item in scanned:
            key = str(item.path)
            seen.add(key)
            row = by_path.get(key)
            if row is not None and row.id == item.doc_id:
                row.last_seen_at = now
                row.status = "active"
                active.append(row)
                changed.append(row)
                continue
            if row is not None and row.id != item.doc_id:
                # same path, new content: the old document is removed, the new
                # one is a different id (content-addressed)
                row.status = "removed"
                changed.append(row)
            new = DocumentRow(
                id=item.doc_id,
                store=store.metadata.name,
                selector=None,
                path=key,
                media_type=item.media_type,
                size=item.size,
                status="active",
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(new)
            active.append(new)
            changed.append(new)
        removed: list[str] = []
        for row in rows:
            if row.status == "active" and str(row.path) not in seen:
                row.status = "removed"
                removed.append(row.id)
                changed.append(row)
        return active, removed

    # ------------------------------------------------------------- extract

    def _options(self, cfg: DocumentCfg) -> ExtractOptions:
        return ExtractOptions(
            split=cfg.split,
            language=cfg.language,
            instructions=self._instructions(cfg),
            max_chunks_per_doc=cfg.max_chunks_per_doc,
        )

    async def _packets_for(
        self, session, doc_id: str, schema_hash: str, prompt_hash: str, model: str
    ) -> list[ExtractPacketRow]:
        rows = (
            (
                await session.execute(
                    select(ExtractPacketRow)
                    .where(
                        ExtractPacketRow.doc_id == doc_id,
                        ExtractPacketRow.schema_hash == schema_hash,
                        ExtractPacketRow.prompt_hash == prompt_hash,
                        ExtractPacketRow.model == model,
                    )
                    .order_by(ExtractPacketRow.chunk_index)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def _extract_doc(
        self, session, run, doc: DocumentRow, schema, options, *, schema_hash: str, prompt_hash: str, model: str
    ) -> int:
        extractor = self._extractor()
        if extractor is None:
            raise DocumentError(
                "no document extractor is configured; install/enable extensions/doc-extract-agent and set "
                "ONTOGENY_DOC_AGENT_CMD or ONTOGENY_DOC_AGENT_URL"
            )
        path = Path(doc.path)
        text, content_b64 = corpus.read_for_agent(path)
        results = await extractor.extract(
            ExtractRequest(
                schema=schema,
                docs=[
                    DocInput(
                        doc_id=doc.id,
                        path=doc.path,
                        text=text,
                        name=path.name,
                        media_type=doc.media_type,
                        content_b64=content_b64,
                    )
                ],
                options=options,
            )
        )
        # replace this run's packets for the doc (a rerun of the same doc)
        for result in results:
            session.add(
                ExtractPacketRow(
                    run_id=run.id,
                    doc_id=doc.id,
                    doc_hash=doc.id,
                    chunk_index=result.index,
                    chunk_hash=_sha(result.text),
                    schema_hash=schema_hash,
                    prompt_hash=prompt_hash,
                    model=model,
                    text=result.text,
                    graph=_jsonable(result.graph),
                    issues=_jsonable(result.issues),
                    status=result.status,
                )
            )
        doc.chunk_count = len(results)
        doc.extracted_at = utcnow()
        doc.error = None
        return len(results)

    # ---------------------------------------------------------------- bind

    async def _bind(self, session, run, packets: list[tuple[ExtractPacketRow, dict]], schema):
        binder = Binder(self.compiled, schema, self.sc.repo, session, run_id=run.id)
        return await binder.bind(packets)

    # --------------------------------------------------------------- apply

    async def _write_object(
        self,
        session,
        bound: BoundObject,
        *,
        run_id: int,
        force: bool = False,
        principal: str,
        created_by: str | None = None,
        action: str = "ingest.extract",
    ) -> str:
        obj = self.compiled.objects[bound.object_type]
        cfg = obj.spec.backing.extract or ExtractCfg()
        bound.props.setdefault(obj.spec.primaryKey[0], bound.object_id)
        current = await self.sc.repo.get(session, bound.object_type, bound.object_id)
        ts = utcnow()
        evidence = bound.evidence
        doc_id = bound.created_by or (next(iter(bound.docs)) if bound.docs else "")
        chunk = next(iter(evidence.values())).chunk_index if evidence else 0
        # two documents disagreed about one field: the first value is kept and
        # the disagreement is surfaced instead of letting chunk order decide
        for prop, values in bound.alternatives.items():
            if not values:
                continue
            # point the review at the document that supplied the disagreeing
            # value, not at the one that happened to be parsed first
            alt = bound.alternative_evidence.get(prop)
            payload_evidence = (
                {prop: alt.as_dict()} if alt is not None else {k: v.as_dict() for k, v in evidence.items()}
            )
            await self._candidate(
                session,
                run_id,
                alt.doc_id if alt is not None else doc_id,
                alt.chunk_index if alt is not None else chunk,
                "object",
                "CONFLICT",
                {
                    "object_type": bound.object_type,
                    "object_id": bound.object_id,
                    "field": prop,
                    "current": _jsonable(bound.props.get(prop)),
                    "proposed": _jsonable(values[0]),
                    "alternatives": _jsonable(values),
                    "props": _jsonable(bound.props),
                    "evidence": payload_evidence,
                },
                object_type=bound.object_type,
                object_id=bound.object_id,
            )

        if current is None:
            if bound.missing_required:
                await self._candidate(
                    session,
                    run_id,
                    doc_id,
                    chunk,
                    "object",
                    "MISSING_REQUIRED",
                    {
                        "object_type": bound.object_type,
                        "object_id": bound.object_id,
                        "props": _jsonable(bound.props),
                        "missing": bound.missing_required,
                        "evidence": {k: v.as_dict() for k, v in evidence.items()},
                    },
                    object_type=bound.object_type,
                    object_id=bound.object_id,
                )
                return "candidate"
            if not force and cfg.create != "auto":
                await self._candidate(
                    session,
                    run_id,
                    doc_id,
                    chunk,
                    "object",
                    "NEW_OBJECT",
                    {
                        "object_type": bound.object_type,
                        "object_id": bound.object_id,
                        "props": _jsonable(bound.props),
                        "evidence": {k: v.as_dict() for k, v in evidence.items()},
                    },
                    object_type=bound.object_type,
                    object_id=bound.object_id,
                )
                return "candidate"
            outcome = await self.sc.repo.apply_extracted(session, bound.object_type, bound.props, ts)
            created = True
        else:
            values: dict[str, Any] = {}
            for prop, value in bound.props.items():
                if prop in self.compiled.objects[bound.object_type].spec.primaryKey:
                    continue
                if not _valid(value):
                    continue
                owner = self.compiled.owner(bound.object_type, prop)
                # even a human acceptance cannot write a system-of-record
                # field: sync owns it, and the review gate is not a second
                # sync with better intentions
                if owner == "source" and not cfg.include_source:
                    continue
                existing = current.get(self.compiled.col(prop))
                if force:
                    values[prop] = value
                    continue
                if cfg.update == "never":
                    continue
                if cfg.update == "fill-empty" and _valid(existing):
                    if existing != value:
                        await self._candidate(
                            session,
                            run_id,
                            doc_id,
                            chunk,
                            "object",
                            "CONFLICT",
                            {
                                "object_type": bound.object_type,
                                "object_id": bound.object_id,
                                "field": prop,
                                "current": _jsonable(existing),
                                "proposed": _jsonable(value),
                                "props": _jsonable(bound.props),
                                "evidence": {k: v.as_dict() for k, v in evidence.items()},
                            },
                            object_type=bound.object_type,
                            object_id=bound.object_id,
                        )
                    continue
                values[prop] = value
            if not values:
                return "noop"
            values[obj.spec.primaryKey[0]] = bound.object_id
            outcome = await self.sc.repo.apply_extracted(session, bound.object_type, values, ts)
            created = False

        if created and outcome == "inserted":
            # durable origin: assertions may later be deleted with their
            # document, but "the corpus created this row" must survive
            origin = await session.get(ExtractOriginRow, (bound.object_type, bound.object_id))
            if origin is None:
                session.add(
                    ExtractOriginRow(
                        object_type=bound.object_type,
                        object_id=bound.object_id,
                        doc_id=doc_id,
                        run_id=run_id,
                    )
                )
        if outcome in ("inserted", "updated"):
            payload_props = bound.props if created else values
            session.add(
                OutboxRow(
                    object_type=bound.object_type,
                    object_id=bound.object_id,
                    op="upsert",
                    payload={"props": _jsonable(payload_props), "origin": "document", "run_id": run_id},
                )
            )
            session.add(
                RevisionRow(
                    action=action,
                    object_type=bound.object_type,
                    object_id=bound.object_id,
                    principal=principal,
                    params={"run_id": run_id, "doc_id": doc_id},
                    before=_jsonable(current) if current else None,
                    after=_jsonable(bound.props),
                    outcome="executed",
                    message=f"extracted from {doc_id[:12]}" if doc_id else "extracted",
                )
            )
            written = bound.props if created else values
            for prop, value in written.items():
                docs = bound.sources.get(prop) or bound.docs or {doc_id}
                for source_doc in docs:
                    ev = evidence.get(prop)
                    await session.execute(
                        delete(ExtractAssertionRow).where(
                            ExtractAssertionRow.doc_id == source_doc,
                            ExtractAssertionRow.kind == "object",
                            ExtractAssertionRow.object_type == bound.object_type,
                            ExtractAssertionRow.object_id == bound.object_id,
                            ExtractAssertionRow.prop == prop,
                        )
                    )
                    session.add(
                        ExtractAssertionRow(
                            run_id=run_id,
                            doc_id=source_doc,
                            chunk_index=ev.chunk_index if ev else 0,
                            kind="object",
                            object_type=bound.object_type,
                            object_id=bound.object_id,
                            prop=prop,
                            value=_jsonable(value),
                            evidence=ev.as_dict() if ev else {},
                            created_object=bool(created and (created_by in (None, source_doc))),
                        )
                    )
        return outcome

    async def _candidate(
        self,
        session,
        run_id: int,
        doc_id: str,
        chunk: int,
        kind: str,
        reason: str,
        payload: dict[str, Any],
        *,
        object_type: str | None = None,
        link: str | None = None,
        object_id: str | None = None,
    ) -> None:
        material = "|".join(
            str(x)
            for x in (
                kind,
                reason,
                object_type,
                link,
                object_id,
                doc_id,
                payload.get("field"),
                payload.get("proposed"),
                payload.get("src_id"),
                payload.get("dst_id"),
            )
        )
        signature = _sha(material)
        existing = (
            (
                await session.execute(
                    select(ExtractCandidateRow)
                    .where(
                        ExtractCandidateRow.signature == signature,
                        ExtractCandidateRow.status == "pending",
                    )
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            # the same proposal from a newer run: refresh it instead of filling
            # the queue with rows a human must reject one by one
            existing.run_id = run_id
            existing.doc_id = doc_id
            existing.chunk_index = chunk
            existing.payload = _jsonable(payload)
            return
        session.add(
            ExtractCandidateRow(
                run_id=run_id,
                doc_id=doc_id,
                chunk_index=chunk,
                kind=kind,
                object_type=object_type,
                link=link,
                object_id=object_id,
                payload=_jsonable(payload),
                reason=reason,
                signature=signature,
                status="pending",
            )
        )

    async def _apply_links(self, session, run, outcome, *, applied_ids: set[tuple[str, str]], principal: str) -> int:
        ts = utcnow()
        # collect new assertions per document first
        new_by_doc: dict[str, set[tuple[str, str, str]]] = {}
        for bound in outcome.links.values():
            for doc_id in bound.sources:
                new_by_doc.setdefault(doc_id, set()).add((bound.link, bound.src_id, bound.dst_id))
        # retract previous assertions of the same documents that are gone
        docs = list(new_by_doc)
        if docs:
            old = (
                (
                    await session.execute(
                        select(ExtractAssertionRow).where(
                            ExtractAssertionRow.doc_id.in_(docs), ExtractAssertionRow.kind == "link"
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in old:
                keep = new_by_doc.get(row.doc_id, set())
                value = row.value or {}
                key = (row.object_type, str(value.get("src")), str(value.get("dst")))
                if key not in keep:
                    await self.sc.repo.link_retract(session, row.object_type, key[1], key[2], row.doc_id, ts)
                    await session.delete(row)
        count = 0
        for bound in outcome.links.values():
            if (bound.out_label, bound.src_id) not in applied_ids or (bound.in_label, bound.dst_id) not in applied_ids:
                # an endpoint is still pending review / was rejected
                await self._candidate(
                    session,
                    run.id,
                    next(iter(bound.sources)),
                    next(iter(bound.sources.values())).chunk_index,
                    "link",
                    "ENDPOINT_NOT_COMMITTED",
                    bound.payload(),
                    link=bound.link,
                )
                continue
            for doc_id, ev in bound.sources.items():
                await self.sc.repo.link_assert(
                    session,
                    bound.link,
                    bound.src_id,
                    bound.dst_id,
                    {"doc_id": doc_id, "chunk_index": ev.chunk_index, "quote": ev.quote},
                    ts,
                )
                await session.execute(
                    delete(ExtractAssertionRow).where(
                        ExtractAssertionRow.doc_id == doc_id,
                        ExtractAssertionRow.kind == "link",
                        ExtractAssertionRow.object_type == bound.link,
                        ExtractAssertionRow.object_id == f"{bound.src_id}->{bound.dst_id}",
                    )
                )
                session.add(
                    ExtractAssertionRow(
                        run_id=run.id,
                        doc_id=doc_id,
                        chunk_index=ev.chunk_index,
                        kind="link",
                        object_type=bound.link,
                        object_id=f"{bound.src_id}->{bound.dst_id}",
                        prop="",
                        value={"src": bound.src_id, "dst": bound.dst_id},
                        evidence=ev.as_dict(),
                    )
                )
                count += 1
        return count

    async def _cleanup_removed(self, session, run, store, removed: list[str]) -> int:
        if not removed:
            return 0
        ts = utcnow()
        archived = 0
        for doc_id in removed:
            links = (
                (
                    await session.execute(
                        select(ExtractAssertionRow).where(
                            ExtractAssertionRow.doc_id == doc_id, ExtractAssertionRow.kind == "link"
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in links:
                value = row.value or {}
                await self.sc.repo.link_retract(
                    session, row.object_type, str(value.get("src")), str(value.get("dst")), doc_id, ts
                )
                await session.delete(row)
            fields = (
                (
                    await session.execute(
                        select(ExtractAssertionRow).where(
                            ExtractAssertionRow.doc_id == doc_id, ExtractAssertionRow.kind == "object"
                        )
                    )
                )
                .scalars()
                .all()
            )
            touched: set[tuple[str, str]] = set()
            for row in fields:
                touched.add((row.object_type, row.object_id))
                await session.delete(row)
            for object_type, object_id in touched:
                remaining = (
                    (
                        await session.execute(
                            select(ExtractAssertionRow).where(
                                ExtractAssertionRow.object_type == object_type,
                                ExtractAssertionRow.object_id == object_id,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if remaining:
                    continue
                # no action ever touched it, so an extraction-created object
                # with no evidence left is exactly what the corpus created
                acted = (
                    (
                        await session.execute(
                            select(RevisionRow).where(
                                RevisionRow.object_type == object_type,
                                RevisionRow.object_id == object_id,
                                RevisionRow.action.notin_(("ingest.extract", "ingest.confirm")),
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if acted is not None:
                    continue
                origin = await session.get(ExtractOriginRow, (object_type, object_id))
                if origin is None:
                    # created outside the corpus (SQL, an action, a human):
                    # removing a document must never archive it
                    continue
                current = await self.sc.repo.get(session, object_type, object_id)
                if current is None:
                    continue
                await self.sc.repo.archive(session, object_type, object_id, ts)
                session.add(
                    OutboxRow(
                        object_type=object_type, object_id=object_id, op="archive", payload={"origin": "document"}
                    )
                )
                archived += 1
        await session.commit()
        return archived

    # ---------------------------------------------------------------- ingest

    def _lock(self, store_name: str):
        import asyncio

        lock = self._locks.get(store_name)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[store_name] = lock
        return lock

    async def ingest(
        self,
        store_name: str,
        *,
        objects: list[str] | None = None,
        dry_run: bool = False,
        principal: str = "extractor",
    ) -> dict[str, Any]:
        # one extraction at a time per corpus: a double-click must not produce
        # two packets runs racing over the same documents
        async with self._lock(store_name):
            return await self._ingest(store_name, objects=objects, dry_run=dry_run, principal=principal)

    async def _ingest(
        self,
        store_name: str,
        *,
        objects: list[str] | None = None,
        dry_run: bool = False,
        principal: str = "extractor",
    ) -> dict[str, Any]:
        if self.compiled is None:
            raise StoreError("service not initialized")
        store = self.store(store_name)
        if self._extractor() is None:
            raise DocumentError(
                "no document extractor is configured; install/enable extensions/doc-extract-agent and set "
                "ONTOGENY_DOC_AGENT_CMD or ONTOGENY_DOC_AGENT_URL"
            )
        cfg = self._cfg(store)
        root = self._root(store)
        targets = self.object_types(store_name)
        if objects is not None:
            targets = [t for t in targets if t in objects]
        if not targets:
            raise DocumentError(f"store {store_name!r} has no document-backed object types")
        reference_types = self._reference_types(targets)
        schema = compile_extraction_schema(self.compiled, targets, reference_types=reference_types)
        instructions = self._instructions(cfg)
        prompt_hash = _sha(f"{PROMPT_VERSION}\n{instructions or ''}")
        # cache identity is the agent endpoint/command, not an LLM model: a
        # different agent is a different extractor and must not reuse packets
        agent_id = self.sc.settings.doc_agent_url or self.sc.settings.doc_agent_cmd or "unconfigured"
        model = "agent:" + _sha(agent_id)[:16]
        scanned = corpus.scan(root, cfg, self._selector(store, targets))

        summary: dict[str, Any] = {
            "store": store_name,
            "documents": len(scanned),
            "chunks": 0,
            "objects": 0,
            "inserted": 0,
            "updated": 0,
            "noop": 0,
            "links": 0,
            "candidates": 0,
            "quarantined": 0,
            "archived": 0,
            "gaps": [],
            "dry_run": dry_run,
        }

        if dry_run:
            return await self._preview(store, cfg, targets, schema, scanned, summary)

        async with self.sc.sessionmaker() as session:
            run = ExtractRunRow(
                store=store_name,
                status="running",
                schema_hash=schema.hash,
                prompt_hash=prompt_hash,
                model=model,
                n_documents=len(scanned),
            )
            session.add(run)
            await session.flush()
            active, removed = await self._sync_documents(session, store, cfg, scanned)
            await session.commit()
            run_id = run.id

        # ---- extraction (long, no transaction held) ------------------------
        to_extract: list[DocumentRow] = []
        cached: dict[str, list[ExtractPacketRow]] = {}
        async with self.sc.sessionmaker() as session:
            for doc in active:
                if doc.status != "active":
                    continue
                cached_packets = await self._packets_for(session, doc.id, schema.hash, prompt_hash, model)
                if cached_packets and doc.extracted_at is not None and doc.chunk_count == len(cached_packets):
                    cached[doc.id] = cached_packets
                else:
                    to_extract.append(doc)
        options = self._options(cfg)
        errors: list[str] = []
        for doc in to_extract:
            try:
                async with self.sc.sessionmaker() as session:
                    row = await session.get(DocumentRow, doc.id)
                    run = await session.get(ExtractRunRow, run_id)
                    await session.execute(
                        delete(ExtractPacketRow).where(
                            ExtractPacketRow.doc_id == doc.id,
                            ExtractPacketRow.schema_hash == schema.hash,
                            ExtractPacketRow.prompt_hash == prompt_hash,
                            ExtractPacketRow.model == model,
                        )
                    )
                    await self._extract_doc(
                        session,
                        run,
                        row,
                        schema.schema,
                        options,
                        schema_hash=schema.hash,
                        prompt_hash=prompt_hash,
                        model=model,
                    )
                    await session.commit()
            except Exception as exc:  # one bad document must not lose the corpus
                log.warning("document %s extraction failed: %s", doc.path, exc)
                errors.append(f"{Path(doc.path).name}: {type(exc).__name__}: {exc}")
                async with self.sc.sessionmaker() as session:
                    row = await session.get(DocumentRow, doc.id)
                    if row is not None:
                        row.error = f"{type(exc).__name__}: {exc}"[:900]
                        await session.commit()

        # ---- bind + apply ---------------------------------------------------
        try:
            # ---- bind + apply ---------------------------------------------------
            async with self.sc.sessionmaker() as session:
                run = await session.get(ExtractRunRow, run_id)
                packets: list[tuple[ExtractPacketRow, dict]] = []
                for doc in active:
                    if doc.id in cached:
                        rows = cached[doc.id]
                        copied: list[ExtractPacketRow] = []
                        for row in rows:
                            clone = ExtractPacketRow(
                                run_id=run_id,
                                doc_id=row.doc_id,
                                doc_hash=row.doc_hash,
                                chunk_index=row.chunk_index,
                                chunk_hash=row.chunk_hash,
                                schema_hash=row.schema_hash,
                                prompt_hash=row.prompt_hash,
                                model=row.model,
                                text=row.text,
                                graph=row.graph,
                                issues=row.issues,
                                status=row.status,
                            )
                            session.add(clone)
                            copied.append(clone)
                        rows = copied
                    else:
                        rows = await self._packets_for(session, doc.id, schema.hash, prompt_hash, model)
                    for row in rows:
                        packets.append((row, row.graph or {}))
                outcome = await self._bind(session, run, packets, schema)
                summary["objects"] = len(outcome.objects)
                summary["gaps"] = list(dict.fromkeys(outcome.gaps))[:50]

                for reject in outcome.rejected:
                    from ..stores.sync import QuarantineRow

                    session.add(
                        QuarantineRow(
                            object_type=reject.object_type,
                            source_pk=reject.source_pk,
                            row=reject.row,
                            code=reject.code,
                            reason=reject.reason,
                        )
                    )
                    summary["quarantined"] += 1
                for cand in outcome.candidates:
                    await self._candidate(
                        session,
                        run_id,
                        cand.doc_id,
                        cand.chunk_index,
                        cand.kind,
                        cand.reason,
                        cand.payload,
                        object_type=cand.object_type,
                        link=cand.link,
                        object_id=cand.object_id,
                    )

                applied_ids: set[tuple[str, str]] = set()
                for bound in outcome.objects.values():
                    current = await self.sc.repo.get(session, bound.object_type, bound.object_id)
                    if current is not None:
                        applied_ids.add((bound.object_type, bound.object_id))
                    outcome_kind = await self._write_object(
                        session, bound, run_id=run_id, principal=f"extractor:{run_id}", created_by=bound.created_by
                    )
                    if outcome_kind == "inserted":
                        applied_ids.add((bound.object_type, bound.object_id))
                        summary["inserted"] += 1
                    elif outcome_kind == "updated":
                        applied_ids.add((bound.object_type, bound.object_id))
                        summary["updated"] += 1
                    elif outcome_kind == "noop":
                        summary["noop"] += 1

                applied_ids |= outcome.references
                summary["links"] = await self._apply_links(
                    session, run, outcome, applied_ids=applied_ids, principal=f"extractor:{run_id}"
                )
                await session.flush()
                pending = (
                    (await session.execute(select(ExtractCandidateRow).where(ExtractCandidateRow.run_id == run_id)))
                    .scalars()
                    .all()
                )
                summary["candidates"] = len(pending)
                packet_rows = (
                    (await session.execute(select(ExtractPacketRow).where(ExtractPacketRow.run_id == run_id)))
                    .scalars()
                    .all()
                )
                summary["chunks"] = len(packet_rows)
                run.n_chunks = summary["chunks"]
                run.n_objects = summary["objects"]
                run.n_inserted = summary["inserted"]
                run.n_updated = summary["updated"]
                run.n_noop = summary["noop"]
                run.n_links = summary["links"]
                run.n_candidates = summary["candidates"]
                run.n_quarantined = summary["quarantined"]
                run.status = "ok"
                run.finished_at = utcnow()
                if errors:
                    run.error = "\n".join(errors)[:4000]
                await session.commit()

        except Exception as exc:
            await self._mark_run_failed(run_id, exc)
            raise

        # a corpus file removed earlier (e.g. by listing the corpus, which
        # marks it removed without extracting) must still be retracted now
        already_removed = await self._removed_ids(store_name)
        summary["archived"] = await self._cleanup_removed_run(
            store_name, list(dict.fromkeys([*removed, *already_removed])), run_id
        )
        summary["run_id"] = run_id
        return summary

    def _reference_types(self, targets: list[str]) -> list[str]:
        """DB-backed endpoints an extracted link points at.

        Opt-in: the type must declare ``backing.extract`` with a match/key, so
        the corpus can resolve it (by name) without ever creating one.
        """
        out: list[str] = []
        for lnk in self.compiled.links.values():
            if not isinstance(lnk.spec.join, ExtractedJoin):
                continue
            for endpoint in (lnk.spec.source, lnk.spec.target):
                if endpoint in targets or endpoint in out:
                    continue
                obj = self.compiled.objects.get(endpoint)
                b = obj.spec.backing if obj is not None else None
                if b is not None and b.extract is not None and (b.extract.match or b.extract.key):
                    out.append(endpoint)
        return out

    def _selector(self, store, targets: list[str]) -> str | None:
        values = {self.compiled.objects[t].spec.backing.source.table for t in targets}
        return values.pop() if len(values) == 1 else None

    async def _mark_run_failed(self, run_id: int, exc: Exception) -> None:
        """A failed apply must not leave a run 'running' forever."""
        async with self.sc.sessionmaker() as session:
            run = await session.get(ExtractRunRow, run_id)
            if run is not None:
                run.status = "error"
                run.error = f"{type(exc).__name__}: {exc}"[:4000]
                run.finished_at = utcnow()
                await session.commit()

    async def _removed_ids(self, store_name: str) -> list[str]:
        async with self.sc.sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(DocumentRow.id).where(DocumentRow.store == store_name, DocumentRow.status == "removed")
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    async def _cleanup_removed_run(self, store_name: str, removed: list[str], run_id: int | None = None) -> int:
        if not removed:
            return 0
        async with self.sc.sessionmaker() as session:
            run = await session.get(ExtractRunRow, run_id) if run_id else None
            if run is None:
                run = ExtractRunRow(store=store_name, status="cleanup")
                session.add(run)
                await session.flush()
            archived = await self._cleanup_removed(session, run, self.store(store_name), removed)
            await session.commit()
            return archived

    async def _preview(self, store, cfg, targets, schema, scanned, summary) -> dict[str, Any]:
        """Dry run: bind against a throwaway in-memory session without writes."""
        extractor = self._extractor()
        if extractor is None:
            raise DocumentError(
                "no document extractor is configured; enable extensions/doc-extract-agent and set "
                "ONTOGENY_DOC_AGENT_CMD or ONTOGENY_DOC_AGENT_URL"
            )
        options = self._options(cfg)
        packets = []
        for item in scanned:
            text, content_b64 = corpus.read_for_agent(item.path)
            results = await extractor.extract(
                ExtractRequest(
                    schema=schema.schema,
                    docs=[
                        DocInput(
                            doc_id=item.doc_id,
                            path=str(item.path),
                            text=text,
                            name=item.path.name,
                            media_type=item.media_type,
                            content_b64=content_b64,
                        )
                    ],
                    options=options,
                )
            )
            for r in results:
                packets.append(
                    type(
                        "P",
                        (),
                        {
                            "doc_id": item.doc_id,
                            "chunk_index": r.index,
                            "text": r.text,
                            "graph": r.graph,
                        },
                    )()
                )
        async with self.sc.sessionmaker() as session:
            run = type("R", (), {"id": 0})()
            outcome = await self._bind(session, run, [(p, p.graph) for p in packets], schema)
        summary.update(
            {
                "objects": len(outcome.objects),
                "links": len(outcome.links),
                "candidates": len(outcome.candidates),
                "quarantined": len(outcome.rejected),
                "gaps": list(dict.fromkeys(outcome.gaps))[:50],
                "preview": {
                    "objects": [b.payload() for b in list(outcome.objects.values())[:200]],
                    "links": [b.payload() for b in list(outcome.links.values())[:200]],
                    "candidates": [
                        {"kind": c.kind, "reason": c.reason, "payload": c.payload} for c in outcome.candidates[:200]
                    ],
                },
            }
        )
        return summary

    async def sync(self, object_type: str) -> dict[str, Any]:
        obj = self.compiled.objects.get(object_type)
        if obj is None or obj.spec.backing is None:
            raise StoreError(f"{object_type!r} has no materialized backing")
        if obj.spec.backing.sync is None or obj.spec.backing.sync.strategy != "extract":
            raise StoreError(f"{object_type!r} is not document-backed")
        return await self.ingest(obj.spec.backing.store, objects=[object_type])

    # ------------------------------------------------------------------ read

    async def store_summaries(self) -> dict[str, Any]:
        stores = self.document_stores()
        async with self.sc.sessionmaker() as session:
            docs = (await session.execute(select(DocumentRow))).scalars().all()
            runs = (
                (await session.execute(select(ExtractRunRow).order_by(ExtractRunRow.id.desc()).limit(200)))
                .scalars()
                .all()
            )
            pending = (
                (await session.execute(select(ExtractCandidateRow).where(ExtractCandidateRow.status == "pending")))
                .scalars()
                .all()
            )
        run_ids = {r.id: r.store for r in runs}
        out = []
        for s in stores:
            mine = [d for d in docs if d.store == s.metadata.name]
            last = next((r for r in runs if r.store == s.metadata.name), None)
            out.append(
                {
                    "name": s.metadata.name,
                    "display": s.metadata.display or s.metadata.name,
                    "description": s.metadata.description,
                    "connection": str(s.spec.connection),
                    "documents": len([d for d in mine if d.status == "active"]),
                    "removed": len([d for d in mine if d.status != "active"]),
                    "object_types": self.object_types(s.metadata.name),
                    "pending": len([c for c in pending if run_ids.get(c.run_id) == s.metadata.name]),
                    "last_run": _run_dict(last) if last is not None else None,
                }
            )
        return {
            "stores": out,
            "extractor": "loaded" if self._extractor() is not None else "missing",
        }

    async def scan_corpus(self, store_name: str) -> int:
        """Register files that exist on disk, without extracting anything.

        The corpus must be visible before the first run -- otherwise the UI
        shows an empty source until someone guesses to press "extract".
        """
        store = self.store(store_name)
        cfg = self._cfg(store)
        root = self._root(store)
        targets = self.object_types(store_name)
        scanned = corpus.scan(root, cfg, self._selector(store, targets))
        async with self.sc.sessionmaker() as session:
            await self._sync_documents(session, store, cfg, scanned)
            await session.commit()
        return len(scanned)

    async def list_documents(self, store_name: str) -> dict[str, Any]:
        self.store(store_name)
        await self.scan_corpus(store_name)
        async with self.sc.sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(DocumentRow)
                        .where(DocumentRow.store == store_name)
                        .order_by(DocumentRow.last_seen_at.desc())
                    )
                )
                .scalars()
                .all()
            )
        return {
            "store": store_name,
            "documents": [
                {
                    "id": r.id,
                    "path": r.path,
                    "name": Path(r.path).name,
                    "media_type": r.media_type,
                    "size": r.size,
                    "status": r.status,
                    "chunk_count": r.chunk_count,
                    "error": r.error,
                    "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
                    "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
                    "extracted_at": r.extracted_at.isoformat() if r.extracted_at else None,
                }
                for r in rows
            ],
        }

    async def list_runs(self, store_name: str | None = None, limit: int = 30) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            stmt = select(ExtractRunRow).order_by(ExtractRunRow.id.desc()).limit(max(1, min(limit, 200)))
            if store_name:
                stmt = stmt.where(ExtractRunRow.store == store_name)
            rows = (await session.execute(stmt)).scalars().all()
        return {"runs": [_run_dict(r) for r in rows]}

    async def run_detail(self, run_id: int) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            run = await session.get(ExtractRunRow, run_id)
            if run is None:
                raise NotFoundError(f"no extraction run {run_id}")
            packets = (
                (
                    await session.execute(
                        select(ExtractPacketRow)
                        .where(ExtractPacketRow.run_id == run_id)
                        .order_by(ExtractPacketRow.doc_id, ExtractPacketRow.chunk_index)
                    )
                )
                .scalars()
                .all()
            )
            docs = {
                r.id: r
                for r in (await session.execute(select(DocumentRow).where(DocumentRow.store == run.store)))
                .scalars()
                .all()
            }
            candidates = (
                (
                    await session.execute(
                        select(ExtractCandidateRow)
                        .where(ExtractCandidateRow.run_id == run_id)
                        .order_by(ExtractCandidateRow.id)
                    )
                )
                .scalars()
                .all()
            )
        grouped: dict[str, dict[str, Any]] = {}
        for p in packets:
            d = docs.get(p.doc_id)
            entry = grouped.setdefault(
                p.doc_id,
                {
                    "doc_id": p.doc_id,
                    "path": d.path if d else None,
                    "name": Path(d.path).name if d else p.doc_id[:12],
                    "chunks": [],
                },
            )
            entry["chunks"].append(
                {
                    "index": p.chunk_index,
                    "text": p.text,
                    "graph": p.graph,
                    "issues": p.issues,
                    "status": p.status,
                }
            )
        return {
            "run": _run_dict(run),
            "documents": list(grouped.values()),
            "candidates": [_candidate_dict(c) for c in candidates],
        }

    async def list_candidates(
        self, status: str = "pending", store_name: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            stmt = select(ExtractCandidateRow).order_by(ExtractCandidateRow.id.desc()).limit(max(1, min(limit, 500)))
            if status and status != "all":
                stmt = stmt.where(ExtractCandidateRow.status == status)
            if store_name:
                run_ids = select(ExtractRunRow.id).where(ExtractRunRow.store == store_name)
                stmt = stmt.where(ExtractCandidateRow.run_id.in_(run_ids))
            rows = (await session.execute(stmt)).scalars().all()
            docs = {r.id: r for r in (await session.execute(select(DocumentRow))).scalars().all()}
        out = []
        for c in rows:
            item = _candidate_dict(c)
            d = docs.get(c.doc_id)
            item["document"] = {
                "id": c.doc_id,
                "name": Path(d.path).name if d else c.doc_id[:12],
                "path": d.path if d else None,
            }
            out.append(item)
        return {"candidates": out}

    async def candidate_detail(self, candidate_id: int) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            c = await session.get(ExtractCandidateRow, candidate_id)
            if c is None:
                raise NotFoundError(f"no candidate {candidate_id}")
            doc = await session.get(DocumentRow, c.doc_id)
            packet = (
                (
                    await session.execute(
                        select(ExtractPacketRow)
                        .where(ExtractPacketRow.doc_id == c.doc_id, ExtractPacketRow.chunk_index == c.chunk_index)
                        .order_by(ExtractPacketRow.id.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            current = None
            if c.kind == "object" and c.object_type and c.object_id:
                current = await self.sc.repo.get(session, c.object_type, c.object_id)
                if current is not None:
                    current = {k: _jsonable(v) for k, v in current.items() if not k.startswith("_")}
            return {
                "candidate": _candidate_dict(c),
                "document": {
                    "id": c.doc_id,
                    "name": Path(doc.path).name if doc else c.doc_id[:12],
                    "path": doc.path if doc else None,
                },
                "chunk": {
                    "index": c.chunk_index,
                    "text": packet.text if packet else "",
                    "issues": packet.issues if packet else [],
                    "graph": packet.graph if packet else {},
                },
                "current": current,
            }

    async def accept_candidate(
        self, candidate_id: int, overrides: dict[str, Any] | None = None, *, principal: str, note: str | None = None
    ) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            c = await session.get(ExtractCandidateRow, candidate_id)
            if c is None:
                raise NotFoundError(f"no candidate {candidate_id}")
            if c.status != "pending":
                raise DocumentError(f"candidate {candidate_id} is {c.status}")
            payload = dict(c.payload or {})
            if c.kind == "object" and c.reason in (
                "NO_IDENTITY",
                "AMBIGUOUS_MATCH",
                "UNRESOLVED_REFERENCE",
                "AMBIGUOUS_REFERENCE",
            ):
                raise DocumentError(
                    f"candidate {candidate_id} ({c.reason}) cannot be accepted: resolve or complete the "
                    "entity first, then run extraction again"
                )
            if overrides:
                payload.setdefault("props", {}).update(overrides)
            if c.kind == "link":
                link = payload.get("link")
                src, dst = payload.get("src_id"), payload.get("dst_id")
                if not link or not src or not dst:
                    raise DocumentError("link candidate is missing endpoints")
                ev = payload.get("evidence") or {}
                link_obj = self.compiled.links.get(link)
                if link_obj is not None:
                    src_row = await self.sc.repo.get(session, link_obj.spec.source, str(src))
                    dst_row = await self.sc.repo.get(session, link_obj.spec.target, str(dst))
                    if src_row is None or dst_row is None:
                        raise DocumentError("link endpoints no longer exist")
                await self.sc.repo.link_assert(
                    session,
                    link,
                    str(src),
                    str(dst),
                    {"doc_id": c.doc_id, "chunk_index": c.chunk_index, "quote": ev.get("quote", "")},
                    utcnow(),
                )
                session.add(
                    OutboxRow(
                        object_type=str(link), object_id=f"{src}->{dst}", op="link", payload={"origin": "document"}
                    )
                )
            else:
                object_type = payload.get("object_type") or c.object_type
                object_id = str(payload.get("object_id") or c.object_id or "")
                if not object_type or not object_id:
                    raise DocumentError("object candidate is missing its type/id")
                from .binder import BoundObject, Evidence, coerce_value

                obj = self.compiled.objects.get(object_type)
                if obj is None:
                    raise DocumentError(f"unknown object type {object_type!r}")
                # a conflict candidate is about ONE field: accepting it must
                # not replay every other extracted value over newer data
                if c.reason == "CONFLICT" and payload.get("field"):
                    chosen: dict[str, Any] = {str(payload["field"]): payload.get("proposed")}
                    chosen.update(overrides or {})
                    raw_props = chosen
                else:
                    raw_props = dict(payload.get("props") or {})
                    raw_props.update(overrides or {})
                props = {}
                for prop, value in raw_props.items():
                    ptype = obj.spec.properties.get(prop)
                    if ptype is None:
                        continue
                    try:
                        props[prop] = coerce_value(ptype.ptype(), value, prop=prop)
                    except Exception:
                        props[prop] = value
                if c.reason == "MISSING_REQUIRED":
                    still = [p for p in (payload.get("missing") or []) if not _valid(props.get(p))]
                    if still:
                        raise DocumentError(
                            f"candidate {candidate_id} is still missing required properties: {', '.join(still)}"
                        )
                evidence = payload.get("evidence") or {}
                bound = BoundObject(object_type, object_id, props, {}, True)
                for prop in props:
                    ev = evidence.get(prop) or {}
                    bound.evidence[prop] = Evidence(
                        ev.get("doc_id") or c.doc_id, ev.get("chunk_index") or c.chunk_index, ev.get("quote") or ""
                    )
                    bound.sources.setdefault(prop, {c.doc_id})
                bound.docs = {c.doc_id}
                bound.created_by = c.doc_id
                result = await self._write_object(
                    session,
                    bound,
                    run_id=c.run_id,
                    force=True,
                    principal=principal,
                    created_by=c.doc_id,
                    action="ingest.accept",
                )
                if result == "candidate":
                    raise DocumentError("candidate could not be applied")
            c.status = "accepted"
            c.decided_by = principal
            c.decided_at = utcnow()
            c.note = note
            await session.commit()
            return {"ok": True, "candidate": _candidate_dict(c)}

    async def reject_candidate(self, candidate_id: int, *, principal: str, reason: str = "") -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            c = await session.get(ExtractCandidateRow, candidate_id)
            if c is None:
                raise NotFoundError(f"no candidate {candidate_id}")
            c.status = "rejected"
            c.decided_by = principal
            c.decided_at = utcnow()
            c.note = reason
            await session.commit()
            return {"ok": True, "candidate": _candidate_dict(c)}

    async def upload(self, store_name: str, files: list[dict[str, str]]) -> dict[str, Any]:
        async with self._lock(store_name):
            return await self._upload(store_name, files)

    async def _upload(self, store_name: str, files: list[dict[str, str]]) -> dict[str, Any]:
        # uploading is corpus management, not extraction: it must work before
        # an agent is configured
        store = self.store(store_name)
        root = self._root(store)
        base = root
        selector = self._selector(store, self.object_types(store_name))
        if selector:
            candidate = root / selector
            if candidate.is_dir():
                base = candidate
        written = []
        for item in files:
            name = Path(str(item.get("name") or "")).name
            if not name or name in {".", ".."}:
                raise DocumentError("invalid file name")
            import base64
            import binascii

            try:
                data = base64.b64decode(str(item.get("content_b64") or ""), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise DocumentError(f"file {name}: invalid base64 content") from exc
            if len(data) > 20 * 1024 * 1024:
                raise DocumentError(f"file {name}: larger than 20MB")
            target = (base / name).resolve()
            if not str(target).startswith(str(root)):
                raise DocumentError("upload escapes the corpus root")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written.append(str(target.relative_to(root)))
        return {"written": written}

    async def remove_document(self, doc_id: str) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            doc = await session.get(DocumentRow, doc_id)
            if doc is None:
                raise NotFoundError(f"no document {doc_id}")
            store_name = doc.store
        async with self._lock(store_name):
            return await self._remove_document(doc_id)

    async def _remove_document(self, doc_id: str) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            doc = await session.get(DocumentRow, doc_id)
            if doc is None:
                raise NotFoundError(f"no document {doc_id}")
            store_name = doc.store
            path = Path(doc.path)
            doc.status = "removed"
            await session.commit()
        # the corpus is the source of truth: leaving the file in place would
        # make the next scan resurrect the document. Move it out of the glob
        # (recoverable) instead of deleting the user's file.
        store = self.store(store_name)
        root = self._root(store)
        if path.is_file() and str(path.resolve()).startswith(str(root.resolve())):
            trash = root.parent / ".trash" / store_name
            trash.mkdir(parents=True, exist_ok=True)
            target = trash / f"{doc_id[:8]}-{path.name}"
            path.rename(target)
        archived = await self._cleanup_removed_run(store_name, [doc_id], None)
        return {"ok": True, "archived": archived}

    def status(self) -> dict[str, Any]:
        records = []
        host = getattr(self.sc, "ext", None)
        for rec in getattr(host, "records", []) if host is not None else []:
            if rec.kind == "document-extractor":
                records.append(rec.to_meta())
        return {
            "extractor": "loaded" if self._extractor() is not None else "missing",
            "extensions": records,
            "stores": [s.metadata.name for s in self.document_stores()],
        }


def _run_dict(r) -> dict[str, Any]:
    return {
        "id": r.id,
        "store": r.store,
        "status": r.status,
        "schema_hash": r.schema_hash,
        "prompt_hash": r.prompt_hash,
        "model": r.model,
        "documents": r.n_documents,
        "chunks": r.n_chunks,
        "objects": r.n_objects,
        "inserted": r.n_inserted,
        "updated": r.n_updated,
        "noop": r.n_noop,
        "links": r.n_links,
        "candidates": r.n_candidates,
        "quarantined": r.n_quarantined,
        "error": r.error,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


def _candidate_dict(c) -> dict[str, Any]:
    return {
        "id": c.id,
        "run_id": c.run_id,
        "doc_id": c.doc_id,
        "chunk_index": c.chunk_index,
        "kind": c.kind,
        "object_type": c.object_type,
        "link": c.link,
        "object_id": c.object_id,
        "reason": c.reason,
        "signature": c.signature,
        "payload": c.payload,
        "status": c.status,
        "note": c.note,
        "decided_by": c.decided_by,
        "decided_at": c.decided_at.isoformat() if c.decided_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }
