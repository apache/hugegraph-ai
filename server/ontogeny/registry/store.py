# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Registry persistence: resource rows, lineage edges, publish/load flows."""
from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, Text, select, update
from sqlalchemy.orm import Mapped, mapped_column

from ..core.loader import OntologyPackage
from ..core.models import RESOURCE_BY_KIND, AnyResource
from ..core.validator import validate
from ..db import Base
from ..errors import DSLValidationError
from .compiled import CompiledOntology, compile_package


class ResourceRow(Base):
    __tablename__ = "ontogeny_meta_resource"

    id: Mapped[int] = mapped_column(primary_key=True)
    pkg: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)
    api_name: Mapped[str] = mapped_column(String(200), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    # sidecar file bodies (policy .cedar text today): kept so a snapshot rebuilt
    # from the database keeps enforcing the same rules
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: _dt.datetime.now(_dt.timezone.utc)
    )
    deleted_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_meta_res_pk", "pkg", "kind", "api_name", unique=True),)


class LineageRow(Base):
    __tablename__ = "ontogeny_meta_lineage"

    id: Mapped[int] = mapped_column(primary_key=True)
    src: Mapped[str] = mapped_column(String(500), index=True)  # "kind/name"
    dst: Mapped[str] = mapped_column(String(500), index=True)
    edge_type: Mapped[str] = mapped_column(String(50))


def _read_sidecar(pkg: OntologyPackage, res: AnyResource) -> str | None:
    """Inline body of a resource's sidecar file, when it has one."""
    if res.kind == "PolicySet":
        rel = getattr(res.spec, "source", None)
        if rel:
            return pkg.sidecar_text("PolicySet", res.metadata.name, rel) or None
    return None


def _lineage_edges(pkg: OntologyPackage) -> list[tuple[str, str, str]]:
    edges: list[tuple[str, str, str]] = []
    stores = {s.metadata.name for s in pkg.stores()}
    for obj in pkg.objects():
        obj_id = f"ObjectType/{obj.metadata.name}"
        b = obj.spec.backing
        if b is not None and b.store in stores:
            edges.append((f"Store/{b.store}", obj_id, "backs"))
        for act in pkg.actions():
            if act.spec.target == obj.metadata.name:
                edges.append((obj_id, f"Action/{act.metadata.name}", "target-of"))
        for lnk in pkg.links():
            if obj.metadata.name in (lnk.spec.source, lnk.spec.target):
                edges.append((obj_id, f"LinkType/{lnk.metadata.name}", "endpoint-of"))
        for prj in pkg.projections():
            if obj.metadata.name in prj.spec.include.objects:
                edges.append((obj_id, f"Projection/{prj.metadata.name}", "projected-to"))
    return edges


def _prune_unknown(cls, definition: dict) -> dict:
    """Drop fields the current DSL no longer knows about.

    A snapshot in the registry was validated when it was written, under the
    model of that day. When the DSL later *removes* a field, that snapshot would
    fail to load — and the deployment would refuse to start because of a key
    nobody uses any more. Removing a field is a normal evolution, so stored
    definitions are read tolerantly here.

    Strictness stays where it belongs: a package on disk is validated with
    `extra="forbid"` at publish time, so a typo in a YAML file is still an
    error. Only already-accepted history is read leniently.
    """
    def _accepted_keys(model) -> set[str]:
        # a stored definition uses the serialized (alias) spelling: accept both
        # the field name and its alias, so an aliased field added later is not
        # silently pruned (and silently reset to its default) on restart
        out = set(model.model_fields)
        for name, fi in model.model_fields.items():
            if fi.alias:
                out.add(fi.alias)
        return out

    fields = _accepted_keys(cls)
    known = {k: v for k, v in definition.items() if k in fields}
    # nested specs are the usual home of a removed field (spec.publish)
    for key, value in list(known.items()):
        if key == "spec" and isinstance(value, dict):
            spec_cls = cls.model_fields[key].annotation
            if hasattr(spec_cls, "model_fields"):
                known[key] = {k: v for k, v in value.items() if k in _accepted_keys(spec_cls)}
    return known


class RegistryService:
    """Publish (validate + persist + compile) and load snapshots from the DB."""

    def __init__(self) -> None:
        self._cache: dict[str, CompiledOntology] = {}

    async def publish(
        self,
        session,
        pkg: OntologyPackage,
        *,
        created_by: str | None = None,
        force: bool = False,
    ) -> CompiledOntology:
        report = validate(pkg)
        if not report.ok and not force:
            errs = "; ".join(f"{i.code}@{i.resource}: {i.message}" for i in report.issues if i.severity == "error")
            raise DSLValidationError(f"package rejected by validator: {errs}", details={"issues": [
                {"code": i.code, "resource": i.resource, "message": i.message} for i in report.issues
            ]})

        compiled = compile_package(pkg)
        pkg_name = pkg.manifest.metadata.name
        now = _dt.datetime.now(_dt.timezone.utc)

        # soft-deleted rows are matched too: the unique index covers
        # (pkg, kind, api_name) regardless of deleted_at, so re-publishing a
        # resource whose earlier row was soft-deleted must REVIVE that row —
        # inserting a fresh one would collide with the index. (This is exactly
        # what the guided demo's second run does: reset soft-deletes the
        # mounted stores, then mounting them again hits this path.)
        existing = {
            (r.kind, r.api_name): r
            for r in (await session.execute(
                select(ResourceRow).where(ResourceRow.pkg == pkg_name)
            )).scalars()
        }

        seen_keys: set[tuple[str, str]] = set()
        for res in [pkg.manifest, *pkg.resources]:
            key = (res.kind, res.metadata.name)
            seen_keys.add(key)
            payload = res.model_dump(mode="json", by_alias=True)
            sidecar = _read_sidecar(pkg, res)
            row = existing.get(key)
            if row is None:
                session.add(ResourceRow(
                    pkg=pkg_name, kind=res.kind, api_name=res.metadata.name,
                    content_hash=compiled.content_hash, definition=payload,
                    source_text=sidecar, created_by=created_by, created_at=now,
                ))
            else:
                row.deleted_at = None  # revive a soft-deleted resource
                row.definition = payload
                row.content_hash = compiled.content_hash
                row.source_text = sidecar
                row.version += 1

        for key, row in existing.items():
            if key not in seen_keys:  # resource removed from the package
                row.deleted_at = now

        await session.execute(LineageRow.__table__.delete())  # lineage is fully derived per publish
        for src, dst, etype in _lineage_edges(pkg):
            session.add(LineageRow(src=src, dst=dst, edge_type=etype))

        self._cache[compiled.content_hash] = compiled
        return compiled

    def cached(self, content_hash: str) -> CompiledOntology | None:
        return self._cache.get(content_hash)

    async def activate(
        self,
        session,
        pkg: OntologyPackage,
        *,
        created_by: str | None = None,
    ) -> CompiledOntology:
        """Domain switch: the snapshot holds exactly ONE ontology.

        ``publish`` only reconciles rows of the *same* package name, so
        activating a second package would otherwise UNION its resources into
        the snapshot (``load_latest`` reads every non-deleted row). Retiring
        every other package's rows first is what makes this a switch, and the
        soft delete is what lets the retired domains come back untouched when
        they are activated again.
        """
        now = _dt.datetime.now(_dt.timezone.utc)
        await session.execute(
            update(ResourceRow)
            .where(ResourceRow.pkg != pkg.manifest.metadata.name, ResourceRow.deleted_at.is_(None))
            .values(deleted_at=now)
        )
        return await self.publish(session, pkg, created_by=created_by)

    async def load_latest(self, session) -> CompiledOntology | None:
        """Rebuild the snapshot from persisted rows (restart without git)."""
        rows = (await session.execute(
            select(ResourceRow).where(ResourceRow.deleted_at.is_(None)).order_by(ResourceRow.id)
        )).scalars().all()
        if not rows:
            return None
        resources: list[AnyResource] = []
        manifest: AnyResource | None = None
        source_texts: dict[tuple[str, str], str] = {}
        for row in rows:
            cls = RESOURCE_BY_KIND.get(row.kind)
            if cls is None:
                continue
            res = cls.model_validate(_prune_unknown(cls, row.definition))
            if row.source_text is not None:
                source_texts[(row.kind, row.api_name)] = row.source_text
            if res.kind == "Ontology":
                manifest = res
                continue
            resources.append(res)
        if manifest is None:
            return None
        pkg = OntologyPackage(
            root=_FakeRoot(), manifest=manifest, resources=resources, source_texts=source_texts,
        )
        compiled = compile_package(pkg)
        self._cache[compiled.content_hash] = compiled
        return compiled

    async def lineage(self, session) -> list[dict[str, str]]:
        rows = (await session.execute(select(LineageRow))).scalars()
        return [{"src": r.src, "dst": r.dst, "edge_type": r.edge_type} for r in rows]


class _FakeRoot:
    """Path stand-in for compile-from-DB (no filesystem behind persisted rows).

    Cedar texts are not reconstructible from rows alone; the registry stores
    them in the definition payload's source file reference. Callers that need
    live cedar text publish from a real package directory.
    """

    def __fspath__(self) -> str:
        return "."

    def __str__(self) -> str:
        return "."

    def __truediv__(self, other: str):
        return _FakePath()


class _FakePath:
    def __truediv__(self, other: str):
        return _FakePath()

    def read_text(self, *a, **k) -> str:  # pragma: no cover - only for DB-only loads
        return ""
