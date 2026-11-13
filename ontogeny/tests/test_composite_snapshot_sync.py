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

"""Snapshot presence and absence compare every typed primary-key component."""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest
import pytest_asyncio
import yaml
from sqlalchemy import select

from ontogeny.action.models import OutboxRow
from ontogeny.config import Settings
from ontogeny.core import load_package
from ontogeny.db import init_schema, make_engine, make_sessionmaker
from ontogeny.registry import RegistryService
from ontogeny.stores import ObjectRepository, SyncEngine
from ontogeny.stores.sources import SqlSource
from ontogeny.stores.sync import QuarantineRow


@pytest_asyncio.fixture()
async def env(tmp_path, request):
    source_path = tmp_path / "source.db"
    key_type = getattr(request, "param", "integer")
    numbers = ["2026-01-01T00:00:00", "2026-01-02T00:00:00"] if key_type == "timestamp" else ["1", "2"]
    with sqlite3.connect(source_path) as connection:
        connection.execute("CREATE TABLE inventory(group_key TEXT, line_no TEXT, amount TEXT)")
        connection.executemany(
            "INSERT INTO inventory VALUES (?, ?, ?)", [("A", numbers[0], "10"), ("A", numbers[1], "20")]
        )
    dsn = f"sqlite+aiosqlite:///{source_path}"
    root = tmp_path / "package"
    for directory in (root, root / "stores", root / "objects"):
        directory.mkdir(exist_ok=True)
    resources = {
        "ontology.yaml": ("Ontology", "composite-snapshot", {}),
        "stores/source.yaml": ("Store", "source", {"type": "sqlite", "connection": dsn}),
        "objects/stock-line.yaml": (
            "ObjectType",
            "stock-line",
            {
                "primaryKey": ["group-key", "line-no"],
                "properties": {
                    "group-key": {"type": "string", "required": True},
                    "line-no": {"type": key_type, "required": True},
                    "amount": {"type": "integer", "required": True, "owner": "source"},
                },
                "backing": {
                    "store": "source",
                    "source": {"table": "inventory"},
                    "mapping": {"group-key": "group_key", "line-no": "line_no"},
                    "sync": {"strategy": "snapshot"},
                },
            },
        ),
    }
    for filename, (kind, name, spec) in resources.items():
        (root / filename).write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "ontogeny/v1",
                    "kind": kind,
                    "metadata": {"name": name},
                    "spec": spec,
                }
            )
        )
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'main.db'}")
    await init_schema(engine)
    maker = make_sessionmaker(engine)
    async with maker() as session:
        compiled = await RegistryService().publish(session, load_package(root))
        await session.commit()
    repo = ObjectRepository(compiled)
    async with maker() as session:
        await repo.ensure(session)
        await session.commit()
    source = SqlSource(compiled.stores["source"], dsn)
    sync = SyncEngine(compiled, Settings(), repo, lambda _: source)
    try:
        yield {"maker": maker, "repo": repo, "sync": sync, "source": source_path}
    finally:
        await source.dispose()
        await engine.dispose()


async def run_sync(env):
    async with env["maker"]() as session:
        result = await env["sync"].sync(session, "stock-line")
        await session.commit()
        return result


async def test_missing_composite_key_archives_only_that_object(env):
    assert (await run_sync(env))["inserted"] == 2
    with sqlite3.connect(env["source"]) as connection:
        connection.execute("DELETE FROM inventory WHERE group_key='A' AND line_no='2'")
    result = await run_sync(env)
    assert result["archived"] == 1 and result["noop"] == 1
    async with env["maker"]() as session:
        assert await env["repo"].alive_keys(session, "stock-line") == {("A", 1)}
        assert (await env["repo"].get(session, "stock-line", ("A", 1)))["amount"] == 10
        assert await env["repo"].get(session, "stock-line", ("A", 2)) is None
        history = await env["repo"].history(session, "stock-line", ("A", 2))
        assert len(history) == 1 and history[0]["_valid_to"] is not None
        events = (await session.scalars(select(OutboxRow).where(OutboxRow.op == "archive"))).all()
        assert len(events) == 1


async def test_bad_row_preserves_its_complete_typed_key_but_true_absence_archives(env):
    with sqlite3.connect(env["source"]) as connection:
        connection.execute("INSERT INTO inventory VALUES ('A', '3', '30')")
    await run_sync(env)
    async with env["maker"]() as session:
        previous = await env["repo"].get(session, "stock-line", ("A", 2))
    with sqlite3.connect(env["source"]) as connection:
        connection.execute("UPDATE inventory SET line_no='002', amount='bad-value' WHERE line_no='2'")
        connection.execute("UPDATE inventory SET amount='11' WHERE line_no='1'")
        connection.execute("DELETE FROM inventory WHERE line_no='3'")
    result = await run_sync(env)
    assert result["quarantined"] == result["updated"] == result["archived"] == 1
    async with env["maker"]() as session:
        assert await env["repo"].alive_keys(session, "stock-line") == {("A", 1), ("A", 2)}
        assert await env["repo"].get(session, "stock-line", ("A", 2)) == previous
        assert (await env["repo"].get(session, "stock-line", ("A", 1)))["amount"] == 11
        quarantine = (await session.scalars(select(QuarantineRow))).one()
        assert quarantine.code == "TYPE_MISMATCH"
        assert quarantine.row["group_key"] == "A" and quarantine.row["line_no"] == "002"


@pytest.mark.parametrize("missing_column", ["group_key", "line_no"])
async def test_missing_any_key_component_is_quarantined_without_aborting_good_rows(env, missing_column):
    with sqlite3.connect(env["source"]) as connection:
        bad = {"group_key": "B", "line_no": "3"}
        bad[missing_column] = None
        connection.execute("INSERT INTO inventory VALUES (?, ?, '30')", (bad["group_key"], bad["line_no"]))
    result = await run_sync(env)
    assert result["inserted"] == 2 and result["quarantined"] == 1 and result["archived"] == 0
    async with env["maker"]() as session:
        assert await env["repo"].alive_keys(session, "stock-line") == {("A", 1), ("A", 2)}
        quarantine = (await session.scalars(select(QuarantineRow))).one()
        assert quarantine.code == "MISSING_PK"


@pytest.mark.parametrize("env", ["timestamp"], indirect=True)
async def test_timestamp_composite_keys_match_the_database_utc_representation(env):
    first = await run_sync(env)
    assert first["inserted"] == 2 and first["archived"] == 0
    second = await run_sync(env)
    assert second["noop"] == 2 and second["archived"] == 0
    async with env["maker"]() as session:
        assert await env["repo"].alive_keys(session, "stock-line") == {
            ("A", dt.datetime(2026, 1, 1, tzinfo=dt.UTC)),
            ("A", dt.datetime(2026, 1, 2, tzinfo=dt.UTC)),
        }
