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
# specific language governing permissions and
# limitations under the License.

"""Sync engine: source -> object tables, with quarantine and ownership.

Execution semantics (data-layer §3.2):
1. idempotent batches (upsert by PK; watermark advances only on commit)
2. at-least-once (failure replays converge via idempotency)
3. deletes are explicit: snapshot defaults to absent-means-archive; watermark
   never invents deletes
4. bad rows quarantine (never block the batch); quarantine rate doubles as an
   evolve fitness signal
"""

from __future__ import annotations

import datetime as _dt
import math
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from ..action.models import OutboxRow
from ..core.types import PropertyType
from ..db import Base
from ..errors import StoreError, TypeMismatchError
from .repo import ObjectRepository, utcnow


class SyncStateRow(Base):
    __tablename__ = "ontogeny_sync_state"

    store: Mapped[str] = mapped_column(String(200), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(200), primary_key=True)
    watermark: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SyncRunRow(Base):
    __tablename__ = "ontogeny_sync_run"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    object_type: Mapped[str] = mapped_column(String(200), index=True)
    strategy: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))  # ok | error
    n_inserted: Mapped[int] = mapped_column(Integer, default=0)
    n_updated: Mapped[int] = mapped_column(Integer, default=0)
    n_noop: Mapped[int] = mapped_column(Integer, default=0)
    n_archived: Mapped[int] = mapped_column(Integer, default=0)
    n_quarantined: Mapped[int] = mapped_column(Integer, default=0)
    watermark_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuarantineRow(Base):
    """Generic quarantine: bad rows wait here for schema fixes (their arrival
    rate is a first-class signal for the evolution loop)."""

    __tablename__ = "ontogeny_quarantine"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    object_type: Mapped[str] = mapped_column(String(200), index=True)
    source_pk: Mapped[str | None] = mapped_column(String(500), nullable=True)
    row: Mapped[dict[str, Any]] = mapped_column(JSON)
    code: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def _coerce_row(
    object_type: str,
    props: dict[str, PropertyType],
    mapped: dict[str, str],
    raw: dict[str, Any],
    *,
    required: set[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """raw source row -> typed property dict; on failure return quarantine info."""
    out: dict[str, Any] = {}
    for prop, colname in mapped.items():
        if colname not in raw:
            continue
        value = raw[colname]
        if value is None:
            out[prop] = None
            continue
        try:
            out[prop] = props[prop].coerce(value, prop=prop)
        except TypeMismatchError as exc:
            return None, "TYPE_MISMATCH", exc.message
    for prop in (k for k in mapped if k not in out):
        out[prop] = None
    missing = sorted(prop for prop in required or () if out.get(prop) is None)
    if missing:
        return None, "REQUIRED_PROPERTY", f"required source properties missing/None: {', '.join(missing)}"
    return out, None, None


class SyncEngine:
    def __init__(self, compiled, settings, repo: ObjectRepository, source_factory) -> None:
        self.compiled = compiled
        self.settings = settings
        self.repo = repo
        self.source_factory = source_factory  # (store_resource) -> source

    def strategy_for(self, object_type: str) -> str:
        obj = self.compiled.objects.get(object_type)
        backing = obj.spec.backing if obj is not None else None
        return backing.sync.strategy if (backing is not None and backing.sync) else "snapshot"

    async def sync(self, session, object_type: str) -> dict[str, Any]:
        obj = self.compiled.objects.get(object_type)
        if obj is None or obj.spec.backing is None:
            raise StoreError(f"{object_type!r} has no materialized backing")
        backing = obj.spec.backing
        if backing.mode == "virtual":
            raise StoreError(f"{object_type!r} is virtual; nothing to sync")
        store = self.compiled.stores.get(backing.store)
        if store is None:
            raise StoreError(f"unknown store {backing.store!r}")

        run = SyncRunRow(
            object_type=object_type,
            strategy=self.strategy_for(object_type),
            status="running",
        )
        session.add(run)
        await session.flush()
        started = utcnow()
        summary = {"inserted": 0, "updated": 0, "noop": 0, "archived": 0, "quarantined": 0}
        # A failed sync's audit is persisted by the caller AFTER the rollback
        # (see ServiceContext.sync): everything in this session is discarded,
        # and only this watermark survives to describe how far the run got.
        max_wm: Any = None
        try:
            source = self.source_factory(store)
            columns = await source.columns(backing.source)

            # prop -> column mapping: explicit overrides + same-name direct
            mapped: dict[str, str] = dict(backing.mapping)
            for prop in obj.spec.properties:
                if prop in mapped or obj.spec.properties[prop].derived:
                    continue
                if prop in columns:
                    mapped[prop] = prop

            state = (
                await session.execute(
                    select(SyncStateRow).where(
                        SyncStateRow.store == backing.store, SyncStateRow.object_type == object_type
                    )
                )
            ).scalar_one_or_none()
            strategy = backing.sync.strategy if backing.sync else "snapshot"
            watermark_col = backing.sync.watermark.column if (backing.sync and backing.sync.watermark) else None

            after: Any = None
            if strategy == "watermark":
                if watermark_col is None:
                    raise StoreError("watermark strategy requires watermark.column")
                after = state.watermark if state and state.watermark else None

            seen_pks: set[str] = set()
            max_wm: Any = after
            pk_props = obj.spec.primaryKey
            ptypes = {p: d.ptype() for p, d in obj.spec.properties.items()}
            required_props = {
                p
                for p, definition in obj.spec.properties.items()
                if definition.required and not definition.derived and p not in pk_props
            }

            rows = source.fetch(
                backing.source,
                watermark_col=watermark_col if strategy == "watermark" else None,
                after=after,
            )
            async for raw in rows:
                if strategy == "watermark" and watermark_col is not None:
                    wm_val = raw.get(watermark_col)
                    if wm_val is not None and (max_wm is None or str(wm_val) > str(max_wm)):
                        max_wm = wm_val
                # Presence is independent of whether the other properties can
                # be coerced. Quarantining an update must preserve the previous
                # good object, not treat that source row as a snapshot deletion.
                # Coerce the key alone so mapped/numeric keys use the same
                # canonical ID as the materialized repository.
                pk_prop = pk_props[0]
                raw_pk = raw.get(mapped.get(pk_prop, pk_prop))
                if raw_pk is not None:
                    try:
                        source_pk = ptypes[pk_prop].coerce(raw_pk, prop=pk_prop)
                    except TypeMismatchError:
                        pass  # an invalid key cannot identify an existing object
                    else:
                        seen_pks.add(str(source_pk))
                props, code, reason = _coerce_row(
                    object_type,
                    ptypes,
                    mapped,
                    raw,
                    required=required_props,
                )
                pk = None
                if props is not None:
                    pk = str(props.get(pk_props[0]))
                    if pk is None or pk == "None":
                        props, code, reason = None, "MISSING_PK", "primary key missing/None"
                if props is None:
                    session.add(
                        QuarantineRow(
                            object_type=object_type,
                            source_pk=str(raw.get(mapped.get(pk_props[0], pk_props[0]))),
                            row=_jsonable(raw),
                            code=code or "?",
                            reason=reason or "",
                        )
                    )
                    summary["quarantined"] += 1
                    continue
                seen_pks.add(pk)
                outcome = await self.repo.sync_upsert(session, object_type, props, started)
                summary[outcome if outcome in summary else "noop"] += 1
                session.add(
                    OutboxRow(
                        object_type=object_type,
                        object_id=pk,
                        op="upsert",
                        payload={"props": _jsonable(props), "origin": "sync"},
                    )
                )

            # absent-means-archive (snapshot only, unless explicitly disabled)
            deletes = backing.sync.deletes if backing.sync else None
            if strategy == "snapshot" and deletes != "none":
                alive = await self.repo.alive_ids(session, object_type)
                for gone in alive:
                    if str(gone) in seen_pks:
                        continue
                    await self.repo.archive(session, object_type, gone, started)
                    session.add(OutboxRow(object_type=object_type, object_id=gone, op="archive", payload={}))
                    summary["archived"] += 1

            if state is None:
                session.add(
                    SyncStateRow(
                        store=backing.store,
                        object_type=object_type,
                        watermark=str(max_wm) if max_wm is not None else None,
                    )
                )
            elif max_wm is not None:
                state.watermark = str(max_wm)

            run.status = "ok"
        except Exception as exc:
            run.status = "error"
            run.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            for k, v in summary.items():
                setattr(run, f"n_{k}", v)
            run.watermark_to = str(max_wm) if max_wm is not None else None
            run.finished_at = utcnow()
        return summary


def _jsonable(value: Any) -> Any:
    """Keep source diagnostics JSON-safe without losing decimal precision.

    Drivers return native Decimal, UUID, datetime and binary values even for
    rows rejected by schema coercion. Conversion must recurse through native
    arrays/JSON too, otherwise one quarantined row can abort the whole sync.
    """
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(item) for item in value]
    if isinstance(value, _dt.datetime | _dt.date | _dt.time):
        return value.isoformat()
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    # Preserve a useful diagnostic for other driver-specific scalar types
    # (for example intervals/ranges), rather than failing to quarantine them.
    return str(value)
