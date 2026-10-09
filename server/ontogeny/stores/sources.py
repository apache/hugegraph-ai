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
"""Source stores: read connectors feeding the sync engine.

- SqlSource: postgres/sqlite source databases via a dedicated engine
- CsvSource: snapshot-only file source

The Store SPI is deliberately tiny: introspection + batched pull. Writes back
to source systems happen through the outbox (webhook/writeback adapters),
never through these readers.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ..core.models import SourceRef, StoreResource
from ..errors import StoreError


def source_engine(store: StoreResource, resolved_dsn: str) -> AsyncEngine:
    if store.spec.type in ("postgres", "sqlite", "mysql"):
        # a bare mysql:// URL has no async driver; normalize to SQLAlchemy's
        # asyncio scheme (requires aiomysql -- the sync error names it plainly)
        if store.spec.type == "mysql" and resolved_dsn.startswith("mysql://"):
            resolved_dsn = resolved_dsn.replace("mysql://", "mysql+aiomysql://", 1)
        return create_async_engine(resolved_dsn, future=True)
    raise StoreError(f"store type {store.spec.type!r} has no SQL source engine")


def qualified_name(ref: SourceRef, dsn: str) -> str:
    if dsn.startswith("sqlite"):
        return ref.table  # sqlite has no schemas in the postgres sense
    return f"{ref.schema_}.{ref.table}" if ref.schema_ else ref.table


class SqlSource:
    def __init__(self, store: StoreResource, dsn: str) -> None:
        self.store = store
        self.dsn = dsn
        self.engine: AsyncEngine | None = None

    async def _eng(self) -> AsyncEngine:
        if self.engine is None:
            self.engine = source_engine(self.store, self.dsn)
        return self.engine

    async def columns(self, ref: SourceRef) -> set[str]:
        eng = await self._eng()
        async with eng.connect() as conn:
            result = await conn.execute(text(
                f"SELECT * FROM {qualified_name(ref, self.dsn)} LIMIT 0"
            ))
            return set(result.keys())

    async def fetch(
        self, ref: SourceRef, *, columns: list[str] | None = None,
        watermark_col: str | None = None, after: Any = None, batch: int = 500,
    ) -> AsyncIterator[dict[str, Any]]:
        eng = await self._eng()
        table = qualified_name(ref, self.dsn)
        is_sqlite = self.dsn.startswith("sqlite")
        async with eng.connect() as conn:
            if watermark_col is not None:
                # Keyset pagination on the watermark: loop until a short batch
                # proves the `> after` range is drained. The old code returned
                # after the FIRST batch, so any source change touching more
                # than `batch` rows was permanently lost behind the advanced
                # watermark.
                cursor = after
                while True:
                    sql = f'SELECT * FROM {table}'
                    params: dict[str, Any] = {}
                    if cursor is not None:
                        sql += f' WHERE "{watermark_col}" > :wm'
                        params["wm"] = cursor
                    sql += " ORDER BY rowid" if is_sqlite else f' ORDER BY "{watermark_col}"'
                    sql += " LIMIT :lim"
                    params["lim"] = batch
                    rows = (await conn.execute(text(sql), params)).mappings().all()
                    if not rows:
                        return
                    for r in rows:
                        yield dict(r)
                    if len(rows) < batch:
                        return  # drained: every row > cursor has been seen
                    # NOTE: rows sharing the boundary watermark value *and*
                    # spanning a full batch edge can still strand behind the
                    # cursor (no cheap total order across dialects); a
                    # sub-second-precision monotonic watermark makes this a
                    # non-issue. The old code lost EVERY row past the first
                    # batch, ties or not.
                    cursor = max(r[watermark_col] for r in rows)
            else:
                # Snapshot pagination needs a deterministic order: LIMIT/OFFSET
                # without ORDER BY returns arbitrary subsets per page on
                # Postgres, a skipped row looks "absent" and is then ARCHIVED
                # -- soft-deleting live data. SQLite has the stable rowid; for
                # everything else order by the full column list (a total order
                # up to identical rows, which swapping is harmless).
                sel_cols = list(columns) if columns is not None else sorted(await self.columns(ref))
                offset = 0
                while True:
                    sql = "SELECT " + ", ".join(f'"{c}"' for c in sel_cols) + f" FROM {table}"
                    sql += " ORDER BY rowid" if is_sqlite else \
                        " ORDER BY " + ", ".join(f'"{c}"' for c in sel_cols)
                    sql += " LIMIT :lim OFFSET :off"
                    rows = (await conn.execute(text(sql), {"lim": batch, "off": offset})).mappings().all()
                    if not rows:
                        return
                    for r in rows:
                        yield dict(r)
                    offset += batch

    async def dispose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


class CsvSource:
    """Snapshot-only source: connection is the CSV file path."""

    def __init__(self, store: StoreResource, path: str) -> None:
        self.store = store
        self.path = Path(path)
        if not self.path.is_file():
            raise StoreError(f"csv source file not found: {path}")

    async def columns(self, ref: SourceRef) -> set[str]:
        with self.path.open(encoding="utf-8", newline="") as f:
            return set(next(csv.reader(f)))

    async def fetch(self, ref: SourceRef, *, columns=None, watermark_col=None, after=None, batch=500):
        with self.path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                yield dict(row)


def make_source(store: StoreResource, resolved_connection: str):
    if store.spec.type == "csv":
        return CsvSource(store, resolved_connection)
    if store.spec.type in ("postgres", "sqlite", "mysql"):
        return SqlSource(store, resolved_connection)
    raise StoreError(f"no source adapter for store type {store.spec.type!r} yet")
