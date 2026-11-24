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

"""Versioned object repository: the ONLY component that reads/writes object
tables. Sync path respects property ownership; action path is used exclusively
by ActionRuntime (ownership already validated at publish time).
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from itertools import batched
from typing import Any

from sqlalchemy import and_, case, func, or_, select, tuple_, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from ..errors import ConflictError, NotFoundError, PolicyDeniedError, RuleRejectedError, StoreError, TypeMismatchError
from .ddl import ensure_tables, live_index_name, object_table

SYNC_UPSERT_BATCH_SIZE = 100
_LINK_MEMBER_BATCH_SIZE = 500


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _next_version_time(current: _dt.datetime, proposed: _dt.datetime) -> _dt.datetime:
    """Keep version intervals strictly increasing, including SQLite's naive UTC timestamps."""
    old = current if current.tzinfo is not None else current.replace(tzinfo=_dt.UTC)
    new = proposed if proposed.tzinfo is not None else proposed.replace(tzinfo=_dt.UTC)
    return proposed if new > old else old + _dt.timedelta(microseconds=1)


def _and(*conds):
    """and_() that drops None conditions (build_filter returns None for no filter)."""
    real = [c for c in conds if c is not None]
    return and_(*real) if real else None


class ObjectRepository:
    def __init__(self, compiled) -> None:
        self.compiled = compiled

    # ------------------------------------------------------------------ util

    def _table(self, object_type: str):
        if object_type not in self.compiled.objects:
            raise NotFoundError(f"unknown object type {object_type!r}")
        return object_table(self.compiled, object_type)

    def _prop_cols(self, object_type: str) -> list[str]:
        """Columns written by sync/actions: everything except derived properties
        (expression deriveds are computed at read; function deriveds are
        materialized by the derivation worker)."""
        obj = self.compiled.objects[object_type]
        return [self.compiled.col(p) for p, d in obj.spec.properties.items() if d.derived is None]

    def _pk_cols(self, object_type: str) -> list[str]:
        return [self.compiled.col(p) for p in self.compiled.objects[object_type].spec.primaryKey]

    def _pk(self, object_type: str, t) -> list:
        """Primary-key Column objects for the object's table."""
        return [t.c[c] for c in self._pk_cols(object_type)]

    def _key_values(self, object_type: str, obj_id: Any) -> tuple[Any, ...]:
        """Coerce API and internal key values using the declared property types."""
        obj = self.compiled.objects[object_type]
        values = list(obj_id) if isinstance(obj_id, (list, tuple)) else [obj_id]
        if len(values) != len(obj.spec.primaryKey):
            raise StoreError(f"expected {len(obj.spec.primaryKey)} key value(s), got {len(values)}")
        if any(value is None for value in values):
            raise StoreError("primary key values must not be null")
        normalized = []
        for prop, value in zip(obj.spec.primaryKey, values, strict=True):
            value = obj.spec.properties[prop].ptype().coerce(value, prop=prop)
            if isinstance(value, _dt.datetime):
                # Timestamp keys must match UTCDateTime's database round trip.
                if value.tzinfo is None:
                    value = value.replace(tzinfo=_dt.UTC)
                value = value.astimezone(_dt.UTC)
            normalized.append(value)
        return tuple(normalized)

    def _key_where(self, object_type: str, table, obj_id: Any):
        return _and(
            *[
                col == value
                for col, value in zip(self._pk(object_type, table), self._key_values(object_type, obj_id), strict=True)
            ]
        )

    def row_to_props(self, object_type: str, row: RowMapping) -> dict[str, Any]:
        """Column dict -> property dict (adds _rev/_valid_from/_valid_to/_synced_at)."""
        out = {
            prop: row[self.compiled.col(prop)]
            for prop in self.compiled.objects[object_type].spec.properties
            if self.compiled.col(prop) in row
        }
        out.update({k: row.get(k) for k in ("_rev", "_valid_from", "_valid_to", "_synced_at")})
        return out

    def _to_columns(self, object_type: str, props: dict[str, Any]) -> dict[str, Any]:
        """Translate declared property names only at the SQL write boundary."""
        declared = self.compiled.objects[object_type].spec.properties
        return {self.compiled.col(p): value for p, value in props.items() if p in declared}

    async def _insert_current(self, session, table, object_type: str, values: dict[str, Any]) -> None:
        """Keep the transaction usable after a concurrent unique conflict."""
        keys = self._pk_cols(object_type)
        try:
            if session.get_bind().dialect.name == "sqlite":
                # SQLite aborts only the failed statement. A SAVEPOINT opened
                # before its first write can otherwise become the outermost
                # transaction and RELEASE would commit the insertion early.
                await session.execute(table.insert().values(**values))
            else:
                # PostgreSQL requires rolling back a failed statement to a
                # savepoint before the surrounding transaction can continue.
                async with session.begin_nested():
                    await session.execute(table.insert().values(**values))
        except IntegrityError as exc:
            orig = exc.orig
            state = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
            message = str(orig)
            pg_conflict = state == "23505" and (
                live_index_name(table.name) in message or f"{table.name}_pkey" in message
            )
            sqlite_columns = ", ".join(f"{table.name}.{key}" for key in keys)
            sqlite_pk_columns = ", ".join(f"{table.name}.{column.name}" for column in table.primary_key.columns)
            sqlite_conflict = getattr(orig, "sqlite_errorname", "") in (
                "SQLITE_CONSTRAINT_UNIQUE",
                "SQLITE_CONSTRAINT_PRIMARYKEY",
            ) and message in (
                f"UNIQUE constraint failed: {sqlite_columns}",
                f"UNIQUE constraint failed: {sqlite_pk_columns}",
            )
            if not (pg_conflict or sqlite_conflict):
                raise
            ids = [values.get(key) for key in keys]
            raise ConflictError(
                f"{object_type}/{ids} already exists", details={"object_type": object_type, "id": ids}
            ) from exc

    async def ensure(self, session) -> None:
        await session.connection()
        conn = await session.connection()
        await conn.run_sync(lambda c: ensure_tables(c, self.compiled))

    # ------------------------------------------------------------------ reads

    def _current_where(self, object_type: str, at: _dt.datetime | None):
        t = self._table(object_type)
        if at is None:
            return t.c._valid_to.is_(None)
        return and_(t.c._valid_from <= at, (t.c._valid_to.is_(None)) | (t.c._valid_to > at))

    async def get(
        self,
        session,
        object_type: str,
        obj_id: Any,
        *,
        at: _dt.datetime | None = None,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        t = self._table(object_type)
        where = _and(self._current_where(object_type, at), self._key_where(object_type, t, obj_id))
        stmt = select(t).where(where).limit(1)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await session.execute(stmt)).mappings().first()
        return self.row_to_props(object_type, row) if row else None

    async def get_many(
        self,
        session,
        object_type: str,
        ids: Iterable[Any],
        *,
        at: _dt.datetime | None = None,
    ) -> list[dict[str, Any]]:
        t = self._table(object_type)
        pk = self._pk(object_type, t)
        values = [self._key_values(object_type, obj_id) for obj_id in ids]
        predicate = pk[0].in_([value[0] for value in values]) if len(pk) == 1 else tuple_(*pk).in_(values)
        stmt = select(t).where(_and(self._current_where(object_type, at), predicate))
        rows = (await session.execute(stmt)).mappings().all()
        return [self.row_to_props(object_type, r) for r in rows]

    async def history(self, session, object_type: str, obj_id: Any) -> list[dict[str, Any]]:
        t = self._table(object_type)
        stmt = select(t).where(self._key_where(object_type, t, obj_id)).order_by(t.c._valid_from)
        return [self.row_to_props(object_type, r) for r in (await session.execute(stmt)).mappings().all()]

    def _marked_props(self, object_type: str, principal: dict | None) -> set[str]:
        """Marked properties the principal does NOT hold -- filters and sorts
        on these would let a caller binary-search a masked value."""
        obj = self.compiled.objects.get(object_type)
        if obj is None:
            return set()
        claims = set((principal or {}).get("markings") or [])
        return {p for p, d in obj.spec.properties.items() if d.marking and d.marking not in claims}

    def build_filter(self, object_type: str, filt: Any, principal: dict | None = None) -> ColumnElement | None:
        """Compile the JSON filter AST to a SQLAlchemy expression.

        Forms: {"field","op","value"} | {"and":[...]} | {"or":[...]} | {"not":F}
        Shorthand {"prop": value} -> eq.  Ops: eq ne lt le gt ge in contains isnull.

        A principal enforces marking claims. None is reserved for trusted
        repository callers such as projection and function execution.
        """
        t = self._table(object_type)
        if filt is None:
            return None

        marked = (
            {self.compiled.col(p) for p in self._marked_props(object_type, principal)}
            if principal is not None
            else set()
        )
        properties = {
            self.compiled.col(prop): definition
            for prop, definition in self.compiled.objects[object_type].spec.properties.items()
        }

        def one(f: dict) -> ColumnElement:
            if "and" in f:
                return and_(*[one(x) for x in f["and"]])
            if "or" in f:
                from sqlalchemy import or_

                return or_(*[one(x) for x in f["or"]])
            if "not" in f:
                return ~one(f["not"])
            if "field" in f:
                name, op, value = f["field"], f.get("op", "eq"), f.get("value")
            else:
                # shorthand: {"a": 1, "b": 2} == a==1 AND b==2
                return _and(*[one({"field": k, "op": "eq", "value": v}) for k, v in f.items()])
            if name.startswith("_"):
                raise StoreError(f"filter on system column {name!r} is not allowed")
            if self.compiled.col(name) in marked:
                raise PolicyDeniedError(
                    f"cannot filter {object_type}.{name}: marked property",
                    details={"object_type": object_type, "field": name},
                )
            col = t.c.get(self.compiled.col(name))
            if col is None:
                raise NotFoundError(f"unknown filter field {name!r} on {object_type}")
            if op in {"eq", "ne", "lt", "le", "gt", "ge", "in"}:
                ptype = properties[col.name].ptype()
                if op == "in":
                    value = [ptype.coerce(item, prop=name) for item in (value if isinstance(value, list) else [value])]
                else:
                    value = ptype.coerce(value, prop=name)
            if op == "eq":
                return col.is_(None) if value is None else col == value
            if op == "ne":
                return col != value
            if op == "lt":
                return col < value
            if op == "le":
                return col <= value
            if op == "gt":
                return col > value
            if op == "ge":
                return col >= value
            if op == "in":
                return col.in_(value if isinstance(value, list) else [value])
            if op == "contains":
                return col.like(f"%{value}%")
            if op == "isnull":
                return col.is_(None)
            raise StoreError(f"unknown filter op {op!r}")

        return one(filt)

    async def query(
        self,
        session,
        object_type: str,
        *,
        filt: Any = None,
        sort: list | None = None,
        limit: int | None = 100,
        offset: int = 0,
        at: _dt.datetime | None = None,
        principal: dict | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        t = self._table(object_type)
        where = _and(self._current_where(object_type, at), self.build_filter(object_type, filt, principal))
        total = (await session.execute(select(func.count()).select_from(t).where(where))).scalar_one()
        stmt = select(t).where(where)
        if isinstance(sort, str):
            parts = sort.rsplit("-", 1)
            declared = self.compiled.objects[object_type].spec.properties
            sort = [
                parts
                if sort not in declared and len(parts) == 2 and parts[1].lower() in ("asc", "desc")
                else [sort, "asc"]
            ]
        for s in sort or []:
            if isinstance(s, str):
                name, direction = s, "asc"
            else:
                name, direction = s[0], s[1]
            col = t.c.get(self.compiled.col(name))
            if col is None:
                raise NotFoundError(f"unknown sort field {name!r}")
            # sorting by a marked property the principal lacks is an oracle
            # (binary-search the masked value through ORDER BY)
            marked = self._marked_props(object_type, principal)
            if self.compiled.col(name) in {self.compiled.col(p) for p in marked}:
                raise PolicyDeniedError(
                    f"cannot sort {object_type}.{name}: marked property",
                    details={"object_type": object_type, "field": name},
                )
            stmt = stmt.order_by(col.desc() if str(direction).lower() == "desc" else col.asc())
        stmt = stmt.limit(limit).offset(offset)
        rows = (await session.execute(stmt)).mappings().all()
        return [self.row_to_props(object_type, r) for r in rows], int(total)

    async def aggregate(
        self,
        session,
        object_type: str,
        fn: str,
        field: str | None,
        *,
        principal: dict | None = None,
        filt: Any = None,
    ) -> float:
        t = self._table(object_type)
        where = _and(self._current_where(object_type, None), self.build_filter(object_type, filt, principal))
        # NOTE: `col if col else ...` truth-tests a Column and raises
        # "Boolean value of this clause is not defined" -- compare with None.
        col = t.c[self.compiled.col(field)] if field else None
        marked = self._marked_props(object_type, principal)
        if field and self.compiled.col(field) in {self.compiled.col(p) for p in marked}:
            raise PolicyDeniedError(
                f"cannot aggregate {object_type}.{field}: marked property",
                details={"object_type": object_type, "field": field},
            )
        target = col if col is not None else t.c._rev
        f = {"count": func.count, "sum": func.sum, "avg": func.avg, "min": func.min, "max": func.max}[fn]
        return (await session.execute(select(f(target)).select_from(t).where(where))).scalar_one()

    # ------------------------------------------------------------- sync writes

    async def sync_upsert(
        self,
        session,
        object_type: str,
        props: dict[str, Any],
        ts: _dt.datetime,
    ) -> str:
        return (await self.sync_upsert_many(session, object_type, [(props, ts)]))[0]

    async def sync_upsert_many(
        self,
        session,
        object_type: str,
        rows: list[tuple[dict[str, Any], _dt.datetime]],
    ) -> list[str]:
        """Ownership-aware upsert used by the sync engine.

        - insert: seeds every provided property (ontology-owned included)
        - update: overwrites ONLY source-owned properties; carries the rest forward

        Current rows are fetched and locked in bounded key batches. Version
        closures and new versions are then written in batches, preserving the
        source-row order and the per-row outcome contract.
        """
        if not rows:
            return []
        if len(rows) > SYNC_UPSERT_BATCH_SIZE:
            outcomes = []
            for offset in range(0, len(rows), SYNC_UPSERT_BATCH_SIZE):
                outcomes.extend(
                    await self.sync_upsert_many(session, object_type, rows[offset : offset + SYNC_UPSERT_BATCH_SIZE])
                )
            return outcomes

        t = self._table(object_type)
        pk_cols = self._pk_cols(object_type)
        property_cols = self._prop_cols(object_type)
        materialized_cols = self._materialized_cols(object_type)
        stored_cols = list(dict.fromkeys([*property_cols, *materialized_cols]))
        normalized: list[tuple[tuple[Any, ...], dict[str, Any], _dt.datetime]] = []
        for source_props, row_ts in rows:
            props = self._to_columns(object_type, source_props)
            missing = [c for c in pk_cols if props.get(c) is None]
            if missing:
                raise StoreError(f"sync row missing primary key {missing}")
            key = self._key_values(object_type, [props[c] for c in pk_cols])
            props.update(dict(zip(pk_cols, key, strict=True)))
            normalized.append((key, props, row_ts))

        keys = list(dict.fromkeys(key for key, _, _ in normalized))
        pk_expr = tuple_(*[t.c[c] for c in pk_cols])
        stmt = select(t).where(t.c._valid_to.is_(None), pk_expr.in_(keys)).with_for_update()
        current_rows = (await session.execute(stmt)).mappings().all()
        states: dict[tuple[Any, ...], dict[str, Any]] = {
            tuple(row[c] for c in pk_cols): {"row": dict(row), "persisted": True} for row in current_rows
        }

        # A persisted version may receive a sync timestamp and later be closed
        # again in the same source batch. Keep both changes keyed to that exact
        # version, while newly-created versions can be updated in memory.
        db_updates: dict[tuple[Any, ...], dict[str, Any]] = {}
        inserted: list[dict[str, Any]] = []
        outcomes: list[str] = []
        for key, props, row_ts in normalized:
            state = states.get(key)
            if state is None:
                version = {col: props.get(col) for col in stored_cols}
                version.update({"_rev": 1, "_valid_from": row_ts, "_valid_to": None, "_synced_at": row_ts})
                inserted.append(version)
                states[key] = {"row": version, "persisted": False}
                outcomes.append("inserted")
                continue

            current = state["row"]
            changes = {
                col: props[col]
                for col in property_cols
                if col in props
                and props[col] != current.get(col)
                and self.compiled.owner(object_type, self._un_col(object_type, col)) == "source"
            }
            if not changes:
                current["_synced_at"] = row_ts
                if state["persisted"]:
                    identity = (*key, current["_valid_from"])
                    db_updates.setdefault(identity, {})["_synced_at"] = row_ts
                outcomes.append("noop")
                continue

            version_ts = _next_version_time(current["_valid_from"], row_ts)
            if state["persisted"]:
                identity = (*key, current["_valid_from"])
                db_updates.setdefault(identity, {})["_valid_to"] = version_ts
            else:
                current["_valid_to"] = version_ts

            version = {col: current.get(col) for col in stored_cols}
            version.update(changes)
            version.update(
                {"_rev": current["_rev"] + 1, "_valid_from": version_ts, "_valid_to": None, "_synced_at": version_ts}
            )
            inserted.append(version)
            states[key] = {"row": version, "persisted": False}
            outcomes.append("updated")

        if db_updates:
            conditions = []
            valid_to_cases = []
            synced_at_cases = []
            for identity, changes in db_updates.items():
                key, valid_from = identity[:-1], identity[-1]
                condition = _and(
                    *[t.c[col] == value for col, value in zip(pk_cols, key, strict=True)],
                    t.c._valid_from == valid_from,
                )
                conditions.append(condition)
                if "_valid_to" in changes:
                    valid_to_cases.append((condition, changes["_valid_to"]))
                if "_synced_at" in changes:
                    synced_at_cases.append((condition, changes["_synced_at"]))
            values = {}
            if valid_to_cases:
                values["_valid_to"] = case(*valid_to_cases, else_=t.c._valid_to)
            if synced_at_cases:
                values["_synced_at"] = case(*synced_at_cases, else_=t.c._synced_at)
            await session.execute(update(t).where(or_(*conditions)).values(**values))

        # Inserts go through _insert_current rather than a single bulk INSERT:
        # a new business key has no live row to lock, so a concurrent create can
        # still collide on the partial unique index. _insert_current wraps each
        # write in a dialect-appropriate savepoint and converts the unique
        # violation into ConflictError, keeping the surrounding transaction
        # usable (the concurrent-create test relies on this contract).
        for version in inserted:
            await self._insert_current(session, t, object_type, version)
        return outcomes

    async def apply_extracted(
        self,
        session,
        object_type: str,
        values: dict[str, Any],
        ts: _dt.datetime,
    ) -> str:
        """Write document-bound values with explicit authority.

        The binder has already decided *which* fields may change (ownership,
        fill-only, review); this method only makes the write versioned and
        idempotent. ``None`` never overwrites an existing value: an absent
        extraction is not evidence of absence.
        """
        t = self._table(object_type)
        values = self._to_columns(object_type, values)
        pk_cols = self._pk_cols(object_type)
        missing = [c for c in pk_cols if values.get(c) is None]
        if missing:
            raise StoreError(f"extracted row missing primary key {missing}")
        values.update(dict(zip(pk_cols, self._key_values(object_type, [values[c] for c in pk_cols]), strict=True)))
        where = _and(t.c._valid_to.is_(None), *[getattr(t.c, c) == values[c] for c in pk_cols])
        current = (await session.execute(select(t).where(where).limit(1).with_for_update())).mappings().first()

        if current is None:
            seed = {c: values.get(c) for c in self._prop_cols(object_type) if c in values}
            seed.update({"_rev": 1, "_valid_from": ts, "_valid_to": None, "_synced_at": ts})
            await session.execute(t.insert().values(**seed))
            return "inserted"

        changes = {
            c: v
            for c, v in values.items()
            if c in self._prop_cols(object_type) and v is not None and (c not in pk_cols) and current.get(c) != v
        }
        if not changes:
            return "noop"
        await session.execute(update(t).where(where).values(_valid_to=ts))
        merged = {c: current.get(c) for c in self._prop_cols(object_type)}
        merged.update({c: current.get(c) for c in self._materialized_cols(object_type)})
        merged.update(changes)
        merged.update({"_rev": current["_rev"] + 1, "_valid_from": ts, "_valid_to": None, "_synced_at": ts})
        await session.execute(t.insert().values(**merged))
        return "updated"

    async def find_by_keys(
        self,
        session,
        object_type: str,
        keys: dict[str, Any],
        *,
        limit: int = 3,
    ) -> list[str]:
        """Resolve extracted natural keys to live ids (normalized comparison).

        Case/whitespace normalization is deliberate: "ACME Corp" and "acme corp"
        are the same supplier in practice, and a false negative creates a
        duplicate that no later run can merge (we never auto-merge objects).
        """
        t = self._table(object_type)
        pk_cols = self._pk_cols(object_type)
        where = [t.c._valid_to.is_(None)]
        for prop, value in keys.items():
            if value is None or value == "":
                continue
            col = getattr(t.c, self.compiled.col(prop))
            kind = self.compiled.ptype(object_type, prop).kind
            if kind in ("string", "enum", "media", "document"):
                where.append(func.lower(func.trim(col)) == str(value).strip().lower())
            else:
                where.append(col == value)
        if len(where) == 1:
            return []
        rows = (
            await session.execute(select(*[getattr(t.c, c) for c in pk_cols]).where(_and(*where)).limit(limit))
        ).all()
        return [str(r[0]) for r in rows]

    def _materialized_cols(self, object_type: str) -> list[str]:
        """Function-derived columns: materialized values that must survive a
        version transition (they are recomputed by the derivation worker, but a
        new version starting as NULL would blank them until the next drain)."""
        obj = self.compiled.objects[object_type]
        return [self.compiled.col(p) for p, d in obj.spec.properties.items() if d.derived_kind() == "function"]

    def _un_col(self, object_type: str, col_name: str) -> str:
        for prop in self.compiled.objects[object_type].spec.properties:
            if self.compiled.col(prop) == col_name:
                return prop
        return col_name

    async def alive_ids(self, session, object_type: str) -> set[Any]:
        t = self._table(object_type)
        pk = self._pk(object_type, t)[0]
        rows = (await session.execute(select(pk).where(t.c._valid_to.is_(None)))).scalars()
        return set(rows)

    async def alive_keys(self, session, object_type: str) -> set[tuple[Any, ...]]:
        t = self._table(object_type)
        rows = (await session.execute(select(*self._pk(object_type, t)).where(t.c._valid_to.is_(None)))).all()
        return {tuple(row) for row in rows}

    # ----------------------------------------------------------- action writes

    async def action_insert(self, session, object_type: str, props: dict[str, Any], ts: _dt.datetime) -> dict[str, Any]:
        t = self._table(object_type)
        props = self._to_columns(object_type, props)
        pk_cols = self._pk_cols(object_type)
        pk_vals = self._key_values(object_type, [props.get(c) for c in pk_cols])
        props.update(dict(zip(pk_cols, pk_vals, strict=True)))
        # The versioned schema keys rows by (business key, _valid_from), so a
        # duplicate business key does NOT violate any table constraint: without
        # this guard it produced two alive rows and `get` silently picked one
        # (newId() used to collide across executions exactly this way).
        key_where = _and(*[t.c[c] == v for c, v in zip(pk_cols, pk_vals, strict=False)])
        where = _and(t.c._valid_to.is_(None), key_where)
        if (await session.execute(select(func.count()).select_from(t).where(where))).scalar_one():
            raise ConflictError(
                f"{object_type}/{pk_vals} already exists",
                details={"object_type": object_type, "id": pk_vals},
            )
        # Reusing an archived key must start after all prior version bounds.
        # A multi-effect action can archive and recreate with the same `ts`.
        latest_start, latest_end = (
            await session.execute(select(func.max(t.c._valid_from), func.max(t.c._valid_to)).where(key_where))
        ).one()
        for bound in (latest_start, latest_end):
            if bound is not None:
                ts = _next_version_time(bound, ts)
        values = {c: props.get(c) for c in self._prop_cols(object_type)}
        values.update({"_rev": 1, "_valid_from": ts, "_valid_to": None})
        await self._insert_current(session, t, object_type, values)
        return await self.get(session, object_type, pk_vals)

    async def action_update(
        self,
        session,
        object_type: str,
        obj_id: Any,
        changes: dict[str, Any],
        ts: _dt.datetime,
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        t = self._table(object_type)
        where = _and(t.c._valid_to.is_(None), self._key_where(object_type, t, obj_id))
        current = (await session.execute(select(t).where(where).limit(1).with_for_update())).mappings().first()
        if current is None:
            raise NotFoundError(f"{object_type}/{obj_id} not found (or archived)")
        if expected_revision is not None and current["_rev"] != expected_revision:
            raise ConflictError(
                f"revision conflict: expected {expected_revision}, current {current['_rev']}",
                details={"expected": expected_revision, "current": current["_rev"]},
            )
        columns = self._to_columns(object_type, changes)
        pk_cols = self._pk_cols(object_type)
        if any(key in columns for key in pk_cols):
            new_keys = self._key_values(object_type, [columns.get(key, current[key]) for key in pk_cols])
            if any(new != current[key] for key, new in zip(pk_cols, new_keys, strict=True)):
                raise RuleRejectedError(f"cannot change the primary key of {object_type}/{obj_id}")
            columns.update(dict(zip(pk_cols, new_keys, strict=True)))
        ts = _next_version_time(current["_valid_from"], ts)
        await session.execute(update(t).where(where).values(_valid_to=ts))
        merged = {c: current.get(c) for c in self._prop_cols(object_type)}
        # materialized function-derived values survive the version transition
        merged.update({c: current.get(c) for c in self._materialized_cols(object_type)})
        merged.update(columns)
        merged.update({"_rev": current["_rev"] + 1, "_valid_from": ts, "_valid_to": None, "_synced_at": None})
        await session.execute(t.insert().values(**merged))
        return self.row_to_props(object_type, dict(current) | merged)

    async def archive(self, session, object_type: str, obj_id: Any, ts: _dt.datetime) -> None:
        t = self._table(object_type)
        where = _and(t.c._valid_to.is_(None), self._key_where(object_type, t, obj_id))
        current = (
            await session.execute(select(t.c._valid_from).where(where).limit(1).with_for_update())
        ).scalar_one_or_none()
        if current is not None:
            await session.execute(update(t).where(where).values(_valid_to=_next_version_time(current, ts)))

    async def archive_many(self, session, object_type: str, obj_ids: Iterable[Any], ts: _dt.datetime) -> list[Any]:
        """Archive live objects and return the supplied IDs of archived rows."""
        t = self._table(object_type)
        pk_cols = self._pk_cols(object_type)
        requested = {}
        for obj_id in obj_ids:
            requested.setdefault(self._key_values(object_type, obj_id), obj_id)
        keys = list(requested)
        archived = []
        for offset in range(0, len(keys), SYNC_UPSERT_BATCH_SIZE):
            batch = keys[offset : offset + SYNC_UPSERT_BATCH_SIZE]
            key_predicate = (
                t.c[pk_cols[0]].in_([key[0] for key in batch])
                if len(pk_cols) == 1
                else tuple_(*[t.c[col] for col in pk_cols]).in_(batch)
            )
            current_rows = (
                await session.execute(
                    select(*[t.c[col] for col in pk_cols], t.c._valid_from)
                    .where(t.c._valid_to.is_(None), key_predicate)
                    .with_for_update()
                )
            ).all()
            if not current_rows:
                continue
            cases = []
            conditions = []
            for row in current_rows:
                key = tuple(row[: len(pk_cols)])
                valid_from = row[len(pk_cols)]
                condition = _and(
                    *[t.c[col] == value for col, value in zip(pk_cols, key, strict=True)],
                    t.c._valid_from == valid_from,
                )
                conditions.append(condition)
                cases.append((condition, _next_version_time(valid_from, ts)))
                archived.append(requested[key])
            await session.execute(
                update(t)
                .where(or_(*conditions), t.c._valid_to.is_(None))
                .values(_valid_to=case(*cases, else_=t.c._valid_to))
            )
        return archived

    # ------------------------------------------------------------------ links

    async def link_add(self, session, link_name: str, src_id: str, dst_id: str, ts: _dt.datetime) -> None:
        from .ddl import link_table

        t = link_table(self.compiled, link_name)
        existing = (
            (
                await session.execute(
                    select(t).where(and_(t.c.src_id == src_id, t.c.dst_id == dst_id, t.c._valid_to.is_(None)))
                )
            )
            .mappings()
            .first()
        )
        if existing:
            # an explicit (action) assertion shares the edge with the corpus:
            # mark it external so a later document removal cannot close it
            provenance = dict(existing.get("_provenance") or {})
            if not provenance.get("external"):
                provenance["external"] = True
                await session.execute(
                    update(t)
                    .where(t.c.src_id == src_id, t.c.dst_id == dst_id, t.c._valid_to.is_(None))
                    .values(_provenance=provenance)
                )
            return
        await session.execute(t.insert().values(src_id=src_id, dst_id=dst_id, _valid_from=ts, _valid_to=None))

    async def link_remove(self, session, link_name: str, src_id: str, dst_id: str, ts: _dt.datetime) -> None:
        from sqlalchemy import update as sa_update

        from .ddl import link_table

        t = link_table(self.compiled, link_name)
        await session.execute(
            sa_update(t)
            .where(and_(t.c.src_id == src_id, t.c.dst_id == dst_id, t.c._valid_to.is_(None)))
            .values(_valid_to=ts)
        )

    async def link_assert(
        self,
        session,
        link_name: str,
        src_id: str,
        dst_id: str,
        provenance: dict[str, Any],
        ts: _dt.datetime,
    ) -> str:
        """Assert an extracted edge; merge provenance when the pair is alive."""
        from .ddl import link_table

        t = link_table(self.compiled, link_name)
        existing = (
            (
                await session.execute(
                    select(t).where(and_(t.c.src_id == src_id, t.c.dst_id == dst_id, t.c._valid_to.is_(None)))
                )
            )
            .mappings()
            .first()
        )
        if existing:
            merged = dict(existing.get("_provenance") or {})
            if existing.get("_provenance") is None:
                # the edge predates the corpus (an action created it): never
                # let a document's retraction close it
                merged["external"] = True
            docs = list(merged.get("docs") or [])
            doc_id = provenance.get("doc_id")
            if doc_id and doc_id not in docs:
                docs.append(doc_id)
            merged["docs"] = docs
            evidence = list(merged.get("evidence") or [])
            evidence.append(provenance)
            merged["evidence"] = evidence[-20:]
            await session.execute(
                update(t)
                .where(t.c.src_id == src_id, t.c.dst_id == dst_id, t.c._valid_to.is_(None))
                .values(_provenance=merged)
            )
            return "noop"
        await session.execute(
            t.insert().values(
                src_id=src_id,
                dst_id=dst_id,
                _valid_from=ts,
                _valid_to=None,
                _provenance={"docs": [provenance["doc_id"]], "evidence": [provenance]},
            )
        )
        return "asserted"

    async def link_retract(
        self,
        session,
        link_name: str,
        src_id: str,
        dst_id: str,
        doc_id: str,
        ts: _dt.datetime,
    ) -> bool:
        """Drop one document's assertion; close the edge only when none remain."""
        from .ddl import link_table

        t = link_table(self.compiled, link_name)
        row = (
            (
                await session.execute(
                    select(t).where(and_(t.c.src_id == src_id, t.c.dst_id == dst_id, t.c._valid_to.is_(None)))
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return False
        provenance = dict(row.get("_provenance") or {})
        docs = [d for d in (provenance.get("docs") or []) if d != doc_id]
        if provenance.get("external") or docs:
            provenance["docs"] = docs
            provenance["evidence"] = [e for e in (provenance.get("evidence") or []) if e.get("doc_id") != doc_id]
            await session.execute(
                update(t)
                .where(t.c.src_id == src_id, t.c.dst_id == dst_id, t.c._valid_to.is_(None))
                .values(_provenance=provenance)
            )
            return False
        await session.execute(
            update(t).where(t.c.src_id == src_id, t.c.dst_id == dst_id, t.c._valid_to.is_(None)).values(_valid_to=ts)
        )
        return True

    async def link_members(
        self,
        session,
        link_name: str,
        *,
        src_id: str | None = None,
        dst_id: str | None = None,
        at: _dt.datetime | None = None,
    ) -> list[tuple[str, str]]:
        from .ddl import link_table

        t = link_table(self.compiled, link_name)
        where = (
            t.c._valid_to.is_(None)
            if at is None
            else and_(t.c._valid_from <= at, (t.c._valid_to.is_(None)) | (t.c._valid_to > at))
        )
        if src_id is not None:
            where = _and(where, t.c.src_id == src_id)
        if dst_id is not None:
            where = _and(where, t.c.dst_id == dst_id)
        rows = (await session.execute(select(t.c.src_id, t.c.dst_id).where(where))).all()
        return [(r[0], r[1]) for r in rows]

    # -------------------------------------------------- derived materialization
    async def set_derived_value(
        self, session, object_type: str, obj_id: str, prop: str, value: Any, ts: _dt.datetime
    ) -> None:
        """Engine-internal materialization of a function-derived property.

        Deliberately NOT a version bump or an audit revision: the value is
        recomputable, and treating recomputation as an "action" would flood the
        audit trail the first time a sync touches a thousand rows.
        """
        t = self._table(object_type)
        col = t.c[self.compiled.col(prop)]
        await session.execute(
            update(t)
            .where(_and(t.c._valid_to.is_(None), self._key_where(object_type, t, obj_id)))
            .values({col.name: value})
        )

    # FK links are read from the object tables themselves
    async def fk_linked_ids(
        self,
        session,
        link_name: str,
        obj_id: str,
        *,
        from_source: bool,
        at: _dt.datetime | None = None,
    ) -> list[str]:
        from ..core.models import ForeignKeyJoin

        lnk = self.compiled.links[link_name]
        join = lnk.spec.join
        if not isinstance(join, ForeignKeyJoin):
            raise StoreError(f"link {link_name} is not foreign-key backed")
        # keys format: {"<target-side obj>.<prop>": "<source-side obj>.<prop>"}
        ((tgt_side, src_side),) = join.keys.items()
        tgt_obj, tgt_prop = tgt_side.split(".", 1)
        _src_obj, _src_prop = src_side.split(".", 1)

        if from_source:
            # obj is a source-side object id; return target-side PKs where fk == obj_id
            t = self._table(tgt_obj)
            fk_col = t.c[self.compiled.col(tgt_prop)]
            pk_col = t.c[self._pk_cols(tgt_obj)[0]]
            fk_value = self.compiled.objects[tgt_obj].spec.properties[tgt_prop].ptype().coerce(obj_id, prop=tgt_prop)
            stmt = select(pk_col).where(_and(self._current_where(tgt_obj, at), fk_col == fk_value))
            return [str(v) for v in (await session.execute(stmt)).scalars()]
        # obj is a target-side object id; read its fk value as the source id
        row = await self.get(session, tgt_obj, obj_id, at=at)
        if row is None:
            return []
        value = row.get(tgt_prop)
        return [str(value)] if value is not None else []

    async def fk_link_pairs(self, session, link_name: str, *, at: _dt.datetime | None = None) -> list[tuple[str, str]]:
        """Every ``(source_id, target_id)`` pair of a foreign-key link.

        The FK column lives on the *target-side* table and holds the source-side
        key, so one scan of that table yields the whole edge set -- this is what
        lets the projection materialize FK links as graph edges instead of
        leaving them implicit in vertex properties.
        """
        from ..core.models import ForeignKeyJoin

        lnk = self.compiled.links[link_name]
        join = lnk.spec.join
        if not isinstance(join, ForeignKeyJoin):
            raise StoreError(f"link {link_name} is not foreign-key backed")
        ((tgt_side, _src_side),) = join.keys.items()
        tgt_obj, tgt_prop = tgt_side.split(".", 1)

        t = self._table(tgt_obj)
        fk_col = t.c[self.compiled.col(tgt_prop)]
        pk_col = t.c[self._pk_cols(tgt_obj)[0]]
        where = _and(self._current_where(tgt_obj, at), fk_col.is_not(None))
        rows = (await session.execute(select(fk_col, pk_col).where(where))).all()
        return [(str(r[0]), str(r[1])) for r in rows]

    def _link_id_candidates(self, endpoint: str, oid: str) -> tuple[str, ...]:
        # Join and extracted edges store endpoint IDs as text. Keep matching
        # exact legacy spellings as well as the type's canonical ID.
        if len(self.compiled.objects[endpoint].spec.primaryKey) != 1:
            return (oid,)
        try:
            (key,) = self._key_values(endpoint, oid)
        except TypeMismatchError:
            return (oid,)
        candidates = (oid, str(key))
        if isinstance(key, _dt.datetime):
            candidates += (key.isoformat(),)
        return tuple(dict.fromkeys(candidates))

    async def link_members_by_ids(
        self,
        session,
        link_name: str,
        ids: Iterable[str],
        *,
        from_source: bool,
        at: _dt.datetime | None = None,
    ) -> dict[str, list[str]]:
        """Read edges only for the requested anchors, in bounded SQL batches."""
        grouped: dict[str, list[str]] = {oid: [] for oid in ids}
        if not grouped:
            return grouped

        from ..core.models import ForeignKeyJoin
        from .ddl import link_table

        spec = self.compiled.links[link_name].spec
        join = spec.join
        if isinstance(join, ForeignKeyJoin):
            ((target_key, _source_key),) = join.keys.items()
            target, fk_prop = target_key.split(".", 1)
            table = self._table(target)
            pk_prop = self.compiled.objects[target].spec.primaryKey[0]
            fk_col = table.c[self.compiled.col(fk_prop)]
            pk_col = table.c[self.compiled.col(pk_prop)]
            anchor_col, other_col = (fk_col, pk_col) if from_source else (pk_col, fk_col)
            anchor_prop = fk_prop if from_source else pk_prop
            ptype = self.compiled.objects[target].spec.properties[anchor_prop].ptype()
            valid = self._current_where(target, at)

            def normalize(value):
                key = ptype.coerce(value, prop=anchor_prop)
                if isinstance(key, _dt.datetime) and key.tzinfo is None:
                    return key.replace(tzinfo=_dt.UTC)
                return key

            aliases: dict[Any, list[str]] = {}
            for oid in grouped:
                key = oid if from_source else self._key_values(target, oid)[0]
                aliases.setdefault(normalize(key), []).append(oid)
        else:
            table = link_table(self.compiled, link_name)
            anchor_col, other_col = (
                (table.c.src_id, table.c.dst_id) if from_source else (table.c.dst_id, table.c.src_id)
            )
            valid = (
                table.c._valid_to.is_(None)
                if at is None
                else and_(table.c._valid_from <= at, (table.c._valid_to.is_(None)) | (table.c._valid_to > at))
            )
            endpoint = spec.source if from_source else spec.target
            aliases = {}
            for oid in grouped:
                for key in self._link_id_candidates(endpoint, oid):
                    aliases.setdefault(key, []).append(oid)
            normalize = str

        for batch in batched(aliases, _LINK_MEMBER_BATCH_SIZE):
            stmt = select(anchor_col, other_col).where(_and(valid, anchor_col.in_(batch)))
            for anchor, other in (await session.execute(stmt)).all():
                if other is not None:
                    for oid in aliases.get(normalize(anchor), ()):
                        grouped[oid].append(str(other))
        if isinstance(join, ForeignKeyJoin):
            return grouped
        # An edge can exist under both of an anchor's stored spellings.
        return {oid: list(dict.fromkeys(members)) for oid, members in grouped.items()}
