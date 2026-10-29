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

"""Derivation worker: materializes function-backed properties.

Contract (docs/implementation.md §5.9):
- A property declares ``derived: {kind: function, entry: file.py:fn, object_param: obj}``.
  Its value is STORED on the object table (unlike expression deriveds, which are
  computed at read time) because the function may call ``ontogeny.query`` on other
  object types or the platform LLM — read-time evaluation would be too slow and
  non-deterministic to put on the query path.
- Triggers: every object upsert/archive lands in the outbox; the worker consumes
  those events for object types that carry function-derived properties, batches
  the ids, and evaluates the function ONCE PER SUBPROCESS over the whole batch
  (the loop runs inside the child; one spawn per batch).
- Writes: the engine applies the values via ``repo.set_derived_value`` — no
  revision bump, no audit row. The value is recomputable; treating
  recomputation as an "action" would flood the audit trail the first time a
  sync touches a thousand rows. Eventually consistent, like the graph
  projection; action decisions never read derived properties for correctness.
"""

from __future__ import annotations

import logging
import secrets

from sqlalchemy import String, delete, select
from sqlalchemy.orm import Mapped, mapped_column

from ..action.models import OutboxRow
from ..db import Base
from ..stores.repo import ObjectRepository, utcnow

log = logging.getLogger("ontogeny.derive")


class DerivationPendingRow(Base):
    """Durable invalidation, written in the outbox consumer's transaction."""

    __tablename__ = "ontogeny_derivation_pending"

    object_type: Mapped[str] = mapped_column(String(255), primary_key=True)
    object_id: Mapped[str] = mapped_column(String(500), primary_key=True)
    generation: Mapped[str] = mapped_column(String(32), nullable=False)


class DerivationWorker:
    def __init__(self, compiled, repo: ObjectRepository, sandbox, session_factory) -> None:
        self.compiled = compiled
        self.repo = repo
        self.sandbox = sandbox
        self.session_factory = session_factory

    # ------------------------------------------------------------------ plan

    def targets(self) -> dict[str, list[tuple[str, str]]]:
        """object_type -> [(prop, entry)] with function-derived properties."""
        out: dict[str, list[tuple[str, str]]] = {}
        for name, obj in self.compiled.objects.items():
            for prop, pdef in obj.spec.properties.items():
                if pdef.derived_kind() == "function":
                    out.setdefault(name, []).append((prop, pdef.derived_entry() or ""))
        return out

    def _fn_for(self, object_type: str, entry: str):
        for fn in self.compiled.functions.values():
            if fn.spec.entry == entry:
                return fn
        return None

    # -------------------------------------------------------------- consumer

    def _trigger_map(self) -> dict[str, set[str]]:
        """changed object type -> owning object types that must recompute."""
        out: dict[str, set[str]] = {}
        for owner in self.targets():
            out.setdefault(owner, set()).add(owner)
        for name, obj in self.compiled.objects.items():
            for pdef in obj.spec.properties.values():
                for trigger in pdef.derived_triggers():
                    out.setdefault(trigger, set()).add(name)
        return out

    async def handle_event(self, event: OutboxRow, session=None) -> bool:
        """Outbox consumer: queue recompute for the owning object types.

        A cross-object derivation (a count over another type's rows) must
        refresh when the OTHER type changes -- a new maintenance order bumps
        equipment.open_mo_count even though equipment itself did not move.
        Cross-type triggers recompute the owner's whole table: targeted
        invalidation would need a dependency graph we deliberately do not
        parse out of sandboxed code; owner tables in an operational ontology
        are small enough that wholesale recompute is the correct trade.
        """
        if session is None:
            async with self.session_factory() as s:
                result = await self.handle_event(event, s)
                await s.commit()
                return result
        if not event.object_type:
            return True
        owners = self._trigger_map().get(event.object_type) or set()
        for owner in owners:
            if owner == event.object_type:
                ids = {str(event.object_id)}
            else:
                ids = {str(oid) for oid in await self.repo.alive_ids(session, owner)}
            # SQLite and PostgreSQL support atomic upsert; a fresh token also
            # prevents an old worker from deleting a later invalidation (ABA).
            if session.bind.dialect.name == "sqlite":
                from sqlalchemy.dialects.sqlite import insert
            elif session.bind.dialect.name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            else:
                raise RuntimeError("durable derivation queue requires SQLite or PostgreSQL")
            values = [{"object_type": owner, "object_id": str(oid), "generation": secrets.token_hex(16)} for oid in ids]
            for start in range(0, len(values), 300):
                stmt = insert(DerivationPendingRow).values(values[start : start + 300])
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["object_type", "object_id"], set_={"generation": stmt.excluded.generation}
                    )
                )
        return True

    async def drain(self) -> dict[str, int]:
        """Compute pending values. Called after each outbox dispatch and by
        `POST /admin/derive`. Returns per-type processed counts."""
        counts: dict[str, int] = {}
        for object_type, props in self.targets().items():
            async with self.session_factory() as s:
                pending = (
                    (
                        await s.execute(
                            select(DerivationPendingRow).where(DerivationPendingRow.object_type == object_type)
                        )
                    )
                    .scalars()
                    .all()
                )
                generations = {row.object_id: row.generation for row in pending}
            if not generations:
                continue
            complete = set(generations)
            for prop, entry in props:
                done, succeeded = await self._compute(object_type, prop, entry, generations)
                complete &= succeeded
                counts[f"{object_type}.{prop}"] = done
            async with self.session_factory() as s:
                for oid in complete:
                    await s.execute(
                        delete(DerivationPendingRow).where(
                            DerivationPendingRow.object_type == object_type,
                            DerivationPendingRow.object_id == oid,
                            DerivationPendingRow.generation == generations[oid],
                        )
                    )
                await s.commit()
        return counts

    # ------------------------------------------------------------- computing

    async def _compute(
        self, object_type: str, prop: str, entry: str, generations: dict[str, str]
    ) -> tuple[int, set[str]]:
        fn = self._fn_for(object_type, entry)
        if fn is None:
            log.warning("function-derived %s.%s: entry %r not found", object_type, prop, entry)
            return 0, set()
        obj = self.compiled.objects[object_type]
        pdef = obj.spec.properties[prop]
        object_param = pdef.derived_object_param()
        pk = obj.spec.primaryKey[0]

        async with self.session_factory() as s:
            rows = await self.repo.get_many(s, object_type, list(generations))
        if not rows:
            return 0, set(generations)

        from ..engine.service import assemble_row

        assembled = [assemble_row(self.compiled, object_type, row) for row in rows]
        succeeded = set(generations) - {str(row[pk]) for row in assembled}

        done = 0
        ts = utcnow()
        # one session AND one subprocess for the whole batch: the fn loop runs
        # inside the child; ontogeny.query RPCs from the child are answered on this
        # session, and the materialized values land in a single transaction
        async with self.session_factory() as s:
            try:
                values = await self.sandbox.map_rows(s, fn, assembled, {}, object_param=object_param)
            except Exception as exc:
                log.warning("derivation %s.%s failed for %d rows: %s", object_type, prop, len(rows), exc)
                return 0, set()
            if len(values) != len(assembled):
                log.warning(
                    "derivation %s.%s returned %d values for %d rows", object_type, prop, len(values), len(rows)
                )
                return 0, set()
            for row_id, value in zip([r[pk] for r in assembled], values, strict=False):
                if value is None and pdef.required:
                    continue
                try:
                    coerced = None if value is None else pdef.ptype().coerce(value, prop=f"{object_type}.{prop}")
                except Exception as exc:
                    log.warning("derivation %s.%s: bad value %r (%s)", object_type, prop, value, exc)
                    continue
                oid = str(row_id)
                current = await s.scalar(
                    select(DerivationPendingRow.generation)
                    .where(
                        DerivationPendingRow.object_type == object_type,
                        DerivationPendingRow.object_id == oid,
                    )
                    .with_for_update()
                )
                if current != generations[oid]:
                    continue
                await self.repo.set_derived_value(s, object_type, str(row_id), prop, coerced, ts)
                done += 1
                succeeded.add(oid)
            await s.commit()
        return done, succeeded
