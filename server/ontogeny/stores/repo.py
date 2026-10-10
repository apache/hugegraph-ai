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
"""Versioned object repository: the ONLY component that reads/writes object
tables. Sync path respects property ownership; action path is used exclusively
by ActionRuntime (ownership already validated at publish time).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Iterable, Sequence

from sqlalchemy import and_, func, select, update
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.engine import RowMapping

from ..errors import ConflictError, NotFoundError, StoreError
from .ddl import ensure_tables, object_table


def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


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
        return [
            self.compiled.col(p) for p, d in obj.spec.properties.items() if d.derived is None
        ]

    def _pk_cols(self, object_type: str) -> list[str]:
        return [self.compiled.col(p) for p in self.compiled.objects[object_type].spec.primaryKey]

    def _pk(self, object_type: str, t) -> list:
        """Primary-key Column objects for the object's table."""
        return [getattr(t.c, c) for c in self._pk_cols(object_type)]

    def row_to_props(self, object_type: str, row: RowMapping) -> dict[str, Any]:
        """Column dict -> property dict (adds _rev/_valid_from/_valid_to/_synced_at)."""
        out: dict[str, Any] = {k: v for k, v in row.items() if not k.startswith("_")}
        out.update({k: row.get(k) for k in ("_rev", "_valid_from", "_valid_to", "_synced_at")})
        return out

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
        self, session, object_type: str, obj_id: str | Sequence[str],
        *, at: _dt.datetime | None = None, for_update: bool = False,
    ) -> dict[str, Any] | None:
        t = self._table(object_type)
        pk_cols = self._pk_cols(object_type)
        ids = [obj_id] if isinstance(obj_id, str) else list(obj_id)
        if len(ids) != len(pk_cols):
            raise StoreError(f"expected {len(pk_cols)} key value(s), got {len(ids)}")
        pk_columns = self._pk(object_type, t)
        where = _and(self._current_where(object_type, at), *[c == v for c, v in zip(pk_columns, ids)])
        stmt = select(t).where(where).limit(1)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await session.execute(stmt)).mappings().first()
        return self.row_to_props(object_type, row) if row else None

    async def get_many(
        self, session, object_type: str, ids: Iterable[str], *, at: _dt.datetime | None = None,
    ) -> list[dict[str, Any]]:
        t = self._table(object_type)
        pk = self._pk(object_type, t)[0]
        stmt = select(t).where(_and(self._current_where(object_type, at), pk.in_(list(ids))))
        rows = (await session.execute(stmt)).mappings().all()
        return [self.row_to_props(object_type, r) for r in rows]

    async def history(self, session, object_type: str, obj_id: str) -> list[dict[str, Any]]:
        t = self._table(object_type)
        pk = self._pk(object_type, t)[0]
        stmt = select(t).where(pk == obj_id).order_by(t.c._valid_from)
        return [self.row_to_props(object_type, r) for r in (await session.execute(stmt)).mappings().all()]

    def build_filter(self, object_type: str, filt: Any) -> ColumnElement | None:
        """Compile the JSON filter AST to a SQLAlchemy expression.

        Forms: {"field","op","value"} | {"and":[...]} | {"or":[...]} | {"not":F}
        Shorthand {"prop": value} -> eq.  Ops: eq ne lt le gt ge in contains isnull.
        """
        t = self._table(object_type)
        if filt is None:
            return None

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
            col = getattr(t.c, self.compiled.col(name), None)
            if col is None:
                raise NotFoundError(f"unknown filter field {name!r} on {object_type}")
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
        self, session, object_type: str,
        *, filt: Any = None, sort: list | None = None, limit: int | None = 100,
        offset: int = 0, at: _dt.datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        t = self._table(object_type)
        where = _and(self._current_where(object_type, at), self.build_filter(object_type, filt))
        total = (await session.execute(select(func.count()).select_from(t).where(where))).scalar_one()
        stmt = select(t).where(where)
        if isinstance(sort, str):
            sort = [sort.rsplit("-", 1) if "-" in sort else [sort, "asc"]]
        for s in sort or []:
            if isinstance(s, str):
                name, direction = s, "asc"
            else:
                name, direction = s[0], s[1]
            col = getattr(t.c, self.compiled.col(name), None)
            if col is None:
                raise NotFoundError(f"unknown sort field {name!r}")
            stmt = stmt.order_by(col.desc() if str(direction).lower() == "desc" else col.asc())
        stmt = stmt.limit(limit).offset(offset)
        rows = (await session.execute(stmt)).mappings().all()
        return [self.row_to_props(object_type, r) for r in rows], int(total)

    async def aggregate(
        self, session, object_type: str, fn: str, field: str | None, *, filt: Any = None,
    ) -> float:
        t = self._table(object_type)
        where = _and(self._current_where(object_type, None), self.build_filter(object_type, filt))
        # NOTE: `col if col else ...` truth-tests a Column and raises
        # "Boolean value of this clause is not defined" -- compare with None.
        col = getattr(t.c, self.compiled.col(field)) if field else None
        target = col if col is not None else t.c._rev
        f = {"count": func.count, "sum": func.sum, "avg": func.avg, "min": func.min, "max": func.max}[fn]
        return (await session.execute(select(f(target)).select_from(t).where(where))).scalar_one()

    # ------------------------------------------------------------- sync writes

    async def sync_upsert(
        self, session, object_type: str, props: dict[str, Any], ts: _dt.datetime,
    ) -> str:
        """Ownership-aware upsert used by the sync engine.

        - insert: seeds every provided property (ontology-owned included)
        - update: overwrites ONLY source-owned properties; carries the rest forward
        """
        t = self._table(object_type)
        pk_cols = self._pk_cols(object_type)
        missing = [c for c in pk_cols if props.get(c) is None]
        if missing:
            raise StoreError(f"sync row missing primary key {missing}")
        where = _and(t.c._valid_to.is_(None), *[getattr(t.c, c) == props[c] for c in pk_cols])
        current = (await session.execute(select(t).where(where).limit(1).with_for_update())).mappings().first()

        if current is None:
            values = {c: props.get(c) for c in self._prop_cols(object_type) if c in props}
            values.update({"_rev": 1, "_valid_from": ts, "_valid_to": None, "_synced_at": ts})
            await session.execute(t.insert().values(**values))
            return "inserted"

        changes = {
            c: props[c]
            for c in self._prop_cols(object_type)
            if c in props and props[c] != current.get(c)
            and self.compiled.owner(object_type, self._un_col(object_type, c)) == "source"
        }
        if not changes:
            # touch _synced_at only (no new version)
            await session.execute(
                update(t).where(where).values(_synced_at=ts)
            )
            return "noop"

        await session.execute(update(t).where(where).values(_valid_to=ts))
        merged = {c: current.get(c) for c in self._prop_cols(object_type)}
        merged.update({c: current.get(c) for c in self._materialized_cols(object_type)})
        merged.update(changes)
        merged.update({"_rev": current["_rev"] + 1, "_valid_from": ts, "_valid_to": None, "_synced_at": ts})
        await session.execute(t.insert().values(**merged))
        return "updated"

    def _materialized_cols(self, object_type: str) -> list[str]:
        """Function-derived columns: materialized values that must survive a
        version transition (they are recomputed by the derivation worker, but a
        new version starting as NULL would blank them until the next drain)."""
        obj = self.compiled.objects[object_type]
        return [
            self.compiled.col(p) for p, d in obj.spec.properties.items()
            if d.derived_kind() == "function"
        ]

    def _un_col(self, object_type: str, col_name: str) -> str:
        for prop in self.compiled.objects[object_type].spec.properties:
            if self.compiled.col(prop) == col_name:
                return prop
        return col_name

    async def alive_ids(self, session, object_type: str) -> set[str]:
        t = self._table(object_type)
        pk = self._pk(object_type, t)[0]
        rows = (await session.execute(select(pk).where(t.c._valid_to.is_(None)))).scalars()
        return set(rows)

    # ----------------------------------------------------------- action writes

    async def action_insert(self, session, object_type: str, props: dict[str, Any], ts: _dt.datetime) -> dict[str, Any]:
        t = self._table(object_type)
        pk_cols = self._pk_cols(object_type)
        pk_vals = [props.get(c) for c in pk_cols]
        # The versioned schema keys rows by (business key, _valid_from), so a
        # duplicate business key does NOT violate any table constraint: without
        # this guard it produced two alive rows and `get` silently picked one
        # (newId() used to collide across executions exactly this way).
        where = _and(t.c._valid_to.is_(None), *[getattr(t.c, c) == v for c, v in zip(pk_cols, pk_vals)])
        if (await session.execute(select(func.count()).select_from(t).where(where))).scalar_one():
            raise ConflictError(
                f"{object_type}/{pk_vals} already exists",
                details={"object_type": object_type, "id": pk_vals},
            )
        values = {c: props.get(c) for c in self._prop_cols(object_type)}
        values.update({"_rev": 1, "_valid_from": ts, "_valid_to": None})
        await session.execute(t.insert().values(**values))
        return await self.get(session, object_type, pk_vals)

    async def action_update(
        self, session, object_type: str, obj_id: str, changes: dict[str, Any],
        ts: _dt.datetime, *, expected_revision: int | None = None,
    ) -> dict[str, Any]:
        t = self._table(object_type)
        pk = self._pk(object_type, t)[0]
        where = _and(t.c._valid_to.is_(None), pk == obj_id)
        current = (await session.execute(select(t).where(where).limit(1).with_for_update())).mappings().first()
        if current is None:
            raise NotFoundError(f"{object_type}/{obj_id} not found (or archived)")
        if expected_revision is not None and current["_rev"] != expected_revision:
            raise ConflictError(
                f"revision conflict: expected {expected_revision}, current {current['_rev']}",
                details={"expected": expected_revision, "current": current["_rev"]},
            )
        await session.execute(update(t).where(where).values(_valid_to=ts))
        merged = {c: current.get(c) for c in self._prop_cols(object_type)}
        # materialized function-derived values survive the version transition
        merged.update({c: current.get(c) for c in self._materialized_cols(object_type)})
        merged.update({self.compiled.col(k): v for k, v in changes.items()})
        merged.update({"_rev": current["_rev"] + 1, "_valid_from": ts, "_valid_to": None})
        await session.execute(t.insert().values(**merged))
        return dict(current) | merged

    async def archive(self, session, object_type: str, obj_id: str, ts: _dt.datetime) -> None:
        t = self._table(object_type)
        pk = self._pk(object_type, t)[0]
        await session.execute(
            update(t).where(_and(t.c._valid_to.is_(None), pk == obj_id)).values(_valid_to=ts)
        )

    # ------------------------------------------------------------------ links

    async def link_add(self, session, link_name: str, src_id: str, dst_id: str, ts: _dt.datetime) -> None:
        from .ddl import link_table

        t = link_table(self.compiled, link_name)
        existing = (await session.execute(
            select(t).where(and_(t.c.src_id == src_id, t.c.dst_id == dst_id, t.c._valid_to.is_(None)))
        )).mappings().first()
        if existing:
            return
        await session.execute(t.insert().values(src_id=src_id, dst_id=dst_id, _valid_from=ts, _valid_to=None))

    async def link_remove(self, session, link_name: str, src_id: str, dst_id: str, ts: _dt.datetime) -> None:
        from .ddl import link_table
        from sqlalchemy import update as sa_update

        t = link_table(self.compiled, link_name)
        await session.execute(sa_update(t).where(
            and_(t.c.src_id == src_id, t.c.dst_id == dst_id, t.c._valid_to.is_(None))
        ).values(_valid_to=ts))

    async def link_members(
        self, session, link_name: str, *, src_id: str | None = None, dst_id: str | None = None,
        at: _dt.datetime | None = None,
    ) -> list[tuple[str, str]]:
        from .ddl import link_table

        t = link_table(self.compiled, link_name)
        where = t.c._valid_to.is_(None) if at is None else and_(
            t.c._valid_from <= at, (t.c._valid_to.is_(None)) | (t.c._valid_to > at)
        )
        if src_id is not None:
            where = _and(where, t.c.src_id == src_id)
        if dst_id is not None:
            where = _and(where, t.c.dst_id == dst_id)
        rows = (await session.execute(select(t.c.src_id, t.c.dst_id).where(where))).all()
        return [(r[0], r[1]) for r in rows]

    # -------------------------------------------------- derived materialization
    async def set_derived_value(self, session, object_type: str, obj_id: str,
                                prop: str, value: Any, ts: _dt.datetime) -> None:
        """Engine-internal materialization of a function-derived property.

        Deliberately NOT a version bump or an audit revision: the value is
        recomputable, and treating recomputation as an "action" would flood the
        audit trail the first time a sync touches a thousand rows.
        """
        t = self._table(object_type)
        pk = self._pk(object_type, t)[0]
        col = getattr(t.c, self.compiled.col(prop))
        await session.execute(
            update(t).where(_and(t.c._valid_to.is_(None), pk == obj_id)).values({col.name: value})
        )

    # FK links are read from the object tables themselves
    async def fk_linked_ids(
        self, session, link_name: str, obj_id: str, *, from_source: bool, at: _dt.datetime | None = None,
    ) -> list[str]:
        from ..core.models import ForeignKeyJoin

        lnk = self.compiled.links[link_name]
        join = lnk.spec.join
        if not isinstance(join, ForeignKeyJoin):
            raise StoreError(f"link {link_name} is not foreign-key backed")
        # keys format: {"<target-side obj>.<prop>": "<source-side obj>.<prop>"}
        (tgt_side, src_side), = join.keys.items()
        tgt_obj, tgt_prop = tgt_side.split(".", 1)
        src_obj, src_prop = src_side.split(".", 1)

        if from_source:
            # obj is a source-side object id; return target-side PKs where fk == obj_id
            t = self._table(tgt_obj)
            fk_col = getattr(t.c, self.compiled.col(tgt_prop))
            pk_col = getattr(t.c, self._pk_cols(tgt_obj)[0])
            stmt = select(pk_col).where(_and(self._current_where(tgt_obj, at), fk_col == obj_id))
            return [str(v) for v in (await session.execute(stmt)).scalars()]
        # obj is a target-side object id; read its fk value as the source id
        row = await self.get(session, tgt_obj, obj_id, at=at)
        if row is None:
            return []
        value = row.get(self.compiled.col(tgt_prop))
        return [str(value)] if value is not None else []

    async def fk_link_pairs(self, session, link_name: str,
                            *, at: _dt.datetime | None = None) -> list[tuple[str, str]]:
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
        (tgt_side, _src_side), = join.keys.items()
        tgt_obj, tgt_prop = tgt_side.split(".", 1)

        t = self._table(tgt_obj)
        fk_col = getattr(t.c, self.compiled.col(tgt_prop))
        pk_col = getattr(t.c, self._pk_cols(tgt_obj)[0])
        where = _and(self._current_where(tgt_obj, at), fk_col.is_not(None))
        rows = (await session.execute(select(fk_col, pk_col).where(where))).all()
        return [(str(r[0]), str(r[1])) for r in rows]
