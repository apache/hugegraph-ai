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

"""Snapshot consistency and native database value quarantine regressions."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine
from test_stores import env as env

from ontogeny.core.models import SourceRef, StoreResource
from ontogeny.stores.sources import SqlSource
from ontogeny.stores.sync import QuarantineRow, _jsonable


@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
async def test_snapshot_stream_does_not_skip_last_row_when_first_page_is_deleted(tmp_path, dialect):
    if dialect == "postgres":
        dsn = os.environ.get("ONTOGENY_PG_DSN")
        if not dsn:
            pytest.skip("PostgreSQL integration requires ONTOGENY_PG_DSN")
    else:
        db_path = tmp_path / "source.db"
        with sqlite3.connect(db_path) as db:
            db.execute("PRAGMA journal_mode=WAL")
        dsn = f"sqlite+aiosqlite:///{db_path}"
    table = "snapshot_" + uuid.uuid4().hex
    store = StoreResource.model_validate(
        {
            "apiVersion": "ontogeny/v1",
            "kind": "Store",
            "metadata": {"name": "snapshot"},
            "spec": {"type": dialect, "connection": dsn},
        }
    )
    source = SqlSource(store, dsn)
    engine = await source._eng()
    async with engine.begin() as connection:
        await connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, value TEXT)"))
        await connection.execute(
            text(f"INSERT INTO {table} VALUES (:id, :value)"),
            [{"id": number, "value": str(number)} for number in range(501)],
        )
    try:
        seen = []
        async for row in source.fetch(SourceRef(table=table), batch=500):
            seen.append(row["id"])
            if len(seen) == 500:
                async with engine.begin() as writer:
                    await writer.execute(text(f"DELETE FROM {table} WHERE id = 0"))
        # Deleting an already-read row must not shift the final live row behind
        # OFFSET 500 and make the sync engine archive it as absent.
        assert len(seen) == 501 and set(seen) == set(range(501))
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE {table}"))
        await source.dispose()


async def test_native_decimal_bad_row_is_quarantined_while_good_rows_commit(env):
    decimal_type = "ONTOGENY_DECIMAL_TEXT"
    previous_converter = sqlite3.converters.get(decimal_type)
    sqlite3.register_converter(decimal_type, lambda raw: Decimal(raw.decode()))
    precise = "12345678901234567890.1234567890123456789"
    with sqlite3.connect(env["src"]) as db:
        db.execute(f"ALTER TABLE work_centers ADD COLUMN native_amount {decimal_type}")
        db.execute("UPDATE work_centers SET native_amount=?, status='INVALID' WHERE work_center_id='WC-01'", (precise,))
    dsn = f"sqlite+aiosqlite:///{env['src']}"
    source = SqlSource(env["compiled"].stores["mes"], dsn)
    source.engine = create_async_engine(dsn, connect_args={"detect_types": sqlite3.PARSE_DECLTYPES})
    env["sync"].source_factory = lambda _: source
    try:
        async with env["maker"]() as session:
            summary = await env["sync"].sync(session, "work-center")
            await session.commit()
            quarantine = (await session.execute(select(QuarantineRow))).scalar_one()
            alive = await env["repo"].alive_ids(session, "work-center")
        assert summary["quarantined"] == 1 and summary["inserted"] == 2
        assert alive == {"WC-02", "WC-03"}
        assert quarantine.row["native_amount"] == precise
        assert quarantine.source_pk == "WC-01"
    finally:
        await source.dispose()
        if previous_converter is None:
            sqlite3.converters.pop(decimal_type, None)
        else:
            sqlite3.converters[decimal_type] = previous_converter


def test_quarantine_conversion_preserves_nested_native_values():
    precise = Decimal("12345678901234567890.1234567890123456789")
    identifier = uuid.UUID("14392e58-a663-42c1-b44d-4a7b799b9996")
    timestamp = dt.datetime(2026, 10, 30, 1, 2, 3, tzinfo=dt.UTC)
    converted = _jsonable(
        {
            "amount": precise,
            "nested": [{"uuid": identifier, "time": timestamp, "date": timestamp.date()}, (precise, None)],
            "binary": memoryview(b"\x00\xff"),
        }
    )
    assert converted == {
        "amount": str(precise),
        "nested": [
            {"uuid": str(identifier), "time": timestamp.isoformat(), "date": "2026-10-30"},
            [str(precise), None],
        ],
        "binary": "00ff",
    }
    json.dumps(converted, allow_nan=False)


@pytest.mark.parametrize("source_kind", ["without-rowid", "view"])
async def test_snapshot_stream_handles_sources_without_rowid(tmp_path, source_kind):
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE base (id TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID")
        db.executemany("INSERT INTO base VALUES (?, ?)", [("a", "first"), ("b", "second")])
        db.execute("CREATE VIEW exposed AS SELECT id, value FROM base")
    dsn = f"sqlite+aiosqlite:///{path}"
    store = StoreResource.model_validate(
        {
            "apiVersion": "ontogeny/v1",
            "kind": "Store",
            "metadata": {"name": "snapshot"},
            "spec": {"type": "sqlite", "connection": dsn},
        }
    )
    source = SqlSource(store, dsn)
    try:
        name = "base" if source_kind == "without-rowid" else "exposed"
        rows = [row async for row in source.fetch(SourceRef(table=name), columns=["id", "value"], batch=1)]
        assert {row["id"] for row in rows} == {"a", "b"}
        assert all(set(row) == {"id", "value"} for row in rows)
    finally:
        await source.dispose()


@pytest.mark.skipif(not os.environ.get("ONTOGENY_PG_DSN"), reason="PostgreSQL integration requires ONTOGENY_PG_DSN")
async def test_postgres_numeric_array_json_and_uuid_bad_row_is_quarantined(env):
    dsn = os.environ["ONTOGENY_PG_DSN"]
    table = "native_source_" + uuid.uuid4().hex
    precise = Decimal("12345678901234567890.1234567890123456789")
    identifier = uuid.uuid4()
    source = SqlSource(env["compiled"].stores["mes"], dsn)
    engine = await source._eng()
    async with engine.begin() as connection:
        await connection.execute(
            text(f"""CREATE TABLE {table} (
            work_center_id TEXT PRIMARY KEY, name TEXT, status TEXT,
            native_amount NUMERIC, native_array NUMERIC[], native_payload JSON, native_uuid UUID
        )""")
        )
        await connection.execute(
            text(f"""INSERT INTO {table} VALUES (
            'WC-01', 'Bad row', 'INVALID', :amount, :amounts, CAST(:payload AS JSON), :identifier
        )"""),
            {
                "amount": precise,
                "amounts": [precise, Decimal("0.01")],
                "payload": json.dumps({"nested": [True, {"label": "native JSON"}]}),
                "identifier": identifier,
            },
        )
        await connection.execute(
            text(f"INSERT INTO {table} (work_center_id, name, status) VALUES ('WC-02', 'Good row', 'ACTIVE')")
        )
    env["compiled"].objects["work-center"].spec.backing.source = SourceRef(table=table)
    env["sync"].source_factory = lambda _: source
    try:
        async with env["maker"]() as session:
            summary = await env["sync"].sync(session, "work-center")
            await session.commit()
            quarantine = (await session.execute(select(QuarantineRow))).scalar_one()
            alive = await env["repo"].alive_ids(session, "work-center")
        assert summary["inserted"] == 1 and summary["quarantined"] == 1
        assert alive == {"WC-02"}
        assert quarantine.row["native_amount"] == str(precise)
        assert quarantine.row["native_array"] == [str(precise), "0.01"]
        assert quarantine.row["native_uuid"] == str(identifier)
        assert quarantine.row["native_payload"] == {"nested": [True, {"label": "native JSON"}]}
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE {table}"))
        await source.dispose()
