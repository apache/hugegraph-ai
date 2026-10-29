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

"""Source stores: read connectors feeding the sync engine.

- SqlSource: postgres/sqlite source databases via a dedicated engine
- CsvSource: snapshot-only file source

The Store SPI is deliberately tiny: introspection + batched pull. Writes back
to source systems happen through the outbox (webhook/writeback adapters),
never through these readers.
"""

from __future__ import annotations

import csv
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
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
            result = await conn.execute(text(f"SELECT * FROM {qualified_name(ref, self.dsn)} LIMIT 0"))
            return set(result.keys())

    async def fetch(
        self,
        ref: SourceRef,
        *,
        columns: list[str] | None = None,
        watermark_col: str | None = None,
        after: Any = None,
        batch: int = 500,
    ) -> AsyncIterator[dict[str, Any]]:
        eng = await self._eng()
        table = qualified_name(ref, self.dsn)
        is_sqlite = self.dsn.startswith("sqlite")
        async with eng.connect() as conn:
            if watermark_col is not None:
                # Keep one ordered result open while fetching bounded batches.
                # Advancing a cursor using only the last watermark would skip
                # equal-valued rows straddling a batch boundary. A single SQL
                # result drains that whole boundary before sync checkpoints it.
                pk_columns = await conn.run_sync(
                    lambda sync_conn: (
                        inspect(sync_conn)
                        .get_pk_constraint(ref.table, schema=None if is_sqlite else ref.schema_)
                        .get("constrained_columns")
                        or []
                    )
                )
                if not pk_columns:
                    # Views and tables without a PK still need deterministic
                    # order. Identical full rows may tie harmlessly: a streamed
                    # result returns each occurrence once without a new seek.
                    result = await conn.execute(text(f"SELECT * FROM {table} LIMIT 0"))
                    pk_columns = sorted(result.keys())
                quote = eng.dialect.identifier_preparer.quote
                order = [watermark_col, *(c for c in pk_columns if c != watermark_col)]
                sql = f"SELECT * FROM {table}"
                params: dict[str, Any] = {}
                if after is not None:
                    # The persisted checkpoint stores only the watermark, not
                    # all source keys seen there. Replay its equality boundary
                    # so a late row with the same timestamp is not stranded.
                    # Repository upserts make that replay idempotent.
                    if eng.dialect.name == "postgresql":
                        # Checkpoints are persisted as text. asyncpg otherwise
                        # infers the column's native type for :wm and rejects
                        # that string before PostgreSQL can cast it. Bind text
                        # first, then cast to the reflected source column type.
                        columns_info = await conn.run_sync(
                            lambda sync_conn: inspect(sync_conn).get_columns(ref.table, schema=ref.schema_)
                        )
                        column = next((c for c in columns_info if c["name"] == watermark_col), None)
                        if column is None:
                            raise StoreError(f"unknown watermark column {watermark_col!r} on {table}")
                        sql_type = column["type"].compile(dialect=eng.dialect)
                        sql += f" WHERE {quote(watermark_col)} >= CAST(CAST(:wm AS TEXT) AS {sql_type})"
                        params["wm"] = str(after)
                    else:
                        sql += f" WHERE {quote(watermark_col)} >= :wm"
                        params["wm"] = after
                sql += " ORDER BY " + ", ".join(quote(c) for c in order)
                async with conn.stream(text(sql), params, execution_options={"yield_per": batch}) as result:
                    async for rows in result.mappings().partitions(batch):
                        for row in rows:
                            yield dict(row)
            else:
                # A deterministic ORDER BY alone does not make LIMIT/OFFSET
                # safe: a concurrent deletion shifts later pages and can make a
                # still-present object look absent to snapshot reconciliation.
                # Keep one result (and its statement snapshot) open instead.
                sel_cols = list(columns) if columns is not None else sorted(await self.columns(ref))
                quote = eng.dialect.identifier_preparer.quote
                sql = "SELECT " + ", ".join(quote(c) for c in sel_cols) + f" FROM {table}"
                # No synthetic ordering is needed within a single statement.
                # Sources may be views/WITHOUT ROWID tables, and PostgreSQL
                # native JSON columns do not even define ordering operators.
                async with conn.stream(text(sql), execution_options={"yield_per": batch}) as result:
                    async for rows in result.mappings().partitions(batch):
                        for row in rows:
                            yield dict(row)

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
