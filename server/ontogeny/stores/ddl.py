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
"""Dynamic DDL: object/link tables compiled from the ontology snapshot.

Each ObjectType gets ``ontogeny_obj_<type>`` with typed property columns plus system
columns (``_rev/_valid_from/_valid_to/_synced_at``). Versioning is
append-only: updates close the current row and insert a successor; the
"alive current" state is exactly ``_valid_to IS NULL``. Derived properties are
never stored (computed at assembly time).
"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.types import TypeDecorator

from ..core.models import JoinTableJoin
from ..core.types import PropertyType

SYSTEM_COLUMNS = ("_rev", "_valid_from", "_valid_to", "_synced_at")


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC timestamps that survive a round trip.

    SQLite drops the offset, so a stored timestamp came back *naive* and every
    timestamp comparison/derivation against `now()` (which is aware) blew up.
    Normalizing on both sides keeps the platform's documented UTC convention
    true regardless of the backing store.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, _dt.date) and not isinstance(value, _dt.datetime):
            value = _dt.datetime(value.year, value.month, value.day)
        if value.tzinfo is None:
            return value.replace(tzinfo=_dt.timezone.utc)
        return value.astimezone(_dt.timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=_dt.timezone.utc)
        return value.astimezone(_dt.timezone.utc)

# One MetaData per ontology snapshot: two packages may both define an
# `equipment` table with different columns, and a republished package may change
# them. Sharing one global MetaData by table name silently returned the wrong
# Table object (Unconsumed column names on write).
_metadata_by_hash: dict[str, MetaData] = {}
_MAX_CACHED_SNAPSHOTS = 4


def _metadata_for(compiled) -> MetaData:
    key = getattr(compiled, "content_hash", "default")
    md = _metadata_by_hash.get(key)
    if md is None:
        if len(_metadata_by_hash) >= _MAX_CACHED_SNAPSHOTS:
            _metadata_by_hash.pop(next(iter(_metadata_by_hash)))
        md = MetaData()
        _metadata_by_hash[key] = md
    return md


def sql_type(ptype: PropertyType):
    k = ptype.kind
    if k in ("string", "enum"):
        return Text
    if k == "integer":
        return BigInteger
    if k == "decimal":
        return Float
    if k == "boolean":
        return Boolean
    if k == "date":
        return Date
    if k == "timestamp":
        return UTCDateTime()
    if k in ("array", "struct", "vector", "geo-point", "geo-shape", "media", "document"):
        return JSON
    raise ValueError(f"no sql mapping for {k}")  # pragma: no cover


def object_table(compiled, object_type: str) -> Table:
    metadata = _metadata_for(compiled)
    name = compiled.table_name(object_type)
    cached = metadata.tables.get(name)
    if cached is not None:
        return cached
    obj = compiled.objects[object_type]
    pk_cols = {compiled.col(p) for p in obj.spec.primaryKey}
    cols: list[Column] = []
    for prop, pdef in obj.spec.properties.items():
        # expression deriveds are computed at read time (no column);
        # function deriveds are MATERIALIZED by the derivation worker (column)
        if pdef.derived_kind() == "expr":
            continue
        cols.append(Column(
            compiled.col(prop), sql_type(pdef.ptype()),
            nullable=not pdef.required,
            # composite PK: business key + _valid_from -> versions coexist
            primary_key=compiled.col(prop) in pk_cols,
        ))
    cols += [
        Column("_rev", BigInteger, nullable=False),
        Column("_valid_from", DateTime(timezone=True), nullable=False, primary_key=True),
        Column("_valid_to", DateTime(timezone=True), nullable=True),
        Column("_synced_at", DateTime(timezone=True), nullable=True),
    ]
    return Table(name, metadata, *cols)


def link_table(compiled, link_name: str) -> Table:
    lnk = compiled.links[link_name]
    if not isinstance(lnk.spec.join, JoinTableJoin):
        raise ValueError(f"link {link_name} is not join-table backed")
    metadata = _metadata_for(compiled)
    name = compiled.link_table(link_name)
    cached = metadata.tables.get(name)
    if cached is not None:
        return cached
    return Table(
        name, metadata,
        # _valid_from is part of the key: without it, link_add -> link_remove ->
        # link_add of the same pair collided with the soft-closed row's PK
        # (objects solved this with (business key, _valid_from); links must too).
        Column("src_id", String(500), primary_key=True),
        Column("dst_id", String(500), primary_key=True),
        Column("_valid_from", DateTime(timezone=True), nullable=False, primary_key=True),
        Column("_valid_to", DateTime(timezone=True), nullable=True),
    )


def ensure_tables(conn, compiled) -> None:
    """Create missing tables and add missing columns (additive migration).

    Additive evolution must just work: when the evolution loop auto-merges a new
    optional property (T0), the object table has to gain that column, otherwise
    the promoted schema would be unqueryable. Destructive changes (drops, type
    changes) are deliberately NOT handled here -- they need `ontogeny migrate`.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(conn)
    existing = set(inspector.get_table_names())
    tables: list[Table] = [
        object_table(compiled, t) for t, o in compiled.objects.items() if o.spec.backing is not None
    ] + [
        link_table(compiled, lnk) for lnk in compiled.links
        if isinstance(compiled.links[lnk].spec.join, JoinTableJoin)
    ]
    for t in tables:
        if t.name not in existing:
            t.create(conn)
            continue
        present = {c["name"] for c in inspector.get_columns(t.name)}
        for column in t.columns:
            if column.name in present or column.primary_key:
                continue
            ddl_type = column.type.compile(conn.dialect)
            conn.execute(text(f'ALTER TABLE {t.name} ADD COLUMN {column.name} {ddl_type}'))


def reset_metadata_cache() -> None:
    """Test helper: forget compiled tables (e.g. across in-memory DBs)."""
    _metadata_by_hash.clear()
