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
# specific language governing permissions and limitations
# under the License.

"""Only one live version may exist for a business key."""

import asyncio
import os
import secrets
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from test_agent_governance import _make

from ontogeny.core import load_package
from ontogeny.db import make_engine, make_sessionmaker
from ontogeny.errors import ConflictError, StoreError
from ontogeny.registry.compiled import compile_package
from ontogeny.stores.ddl import live_index_name
from ontogeny.stores.repo import ObjectRepository, utcnow


async def test_existing_table_gets_index_and_allows_historical_versions(golden_pkg_path, tmp_path):
    compiled = compile_package(load_package(golden_pkg_path))
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'old.db'}")
    repo, maker = ObjectRepository(compiled), make_sessionmaker(engine)
    table = repo._table("material")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f'CREATE TABLE "{table.name}" (material_id TEXT NOT NULL, name TEXT NOT NULL, '
                "_rev INTEGER NOT NULL, _valid_from DATETIME NOT NULL, _valid_to DATETIME, "
                "_synced_at DATETIME, PRIMARY KEY(material_id, _valid_from))"
            )
        )
    async with maker() as db:
        await repo.ensure(db)
        await db.commit()
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda c: [i["name"] for i in inspect(c).get_indexes(table.name)])
    assert live_index_name(table.name) in names
    async with maker() as db:
        await repo.action_insert(db, "material", {"material_id": "M-new", "name": "one"}, utcnow())
        await repo.action_update(db, "material", "M-new", {"name": "two"}, utcnow())
        assert len(await repo.history(db, "material", "M-new")) == 2
        await db.commit()
    await engine.dispose()


async def test_duplicate_old_rows_block_migration_without_deletion(golden_pkg_path, tmp_path):
    compiled = compile_package(load_package(golden_pkg_path))
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'old-duplicates.db'}")
    repo, maker = ObjectRepository(compiled), make_sessionmaker(engine)
    table = repo._table("material")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f'CREATE TABLE "{table.name}" (material_id TEXT NOT NULL, name TEXT NOT NULL, '
                "_rev INTEGER NOT NULL, _valid_from DATETIME NOT NULL, _valid_to DATETIME, "
                "_synced_at DATETIME, PRIMARY KEY(material_id, _valid_from))"
            )
        )
        await conn.execute(
            text(
                f'INSERT INTO "{table.name}" VALUES '
                "('M-dup','first',1,'2026-01-01',NULL,NULL), "
                "('M-dup','second',2,'2026-01-02',NULL,NULL)"
            )
        )
    async with maker() as db:
        with pytest.raises(StoreError, match="duplicate business keys"):
            await repo.ensure(db)
        await db.rollback()
    async with engine.connect() as conn:
        assert (await conn.execute(text(f'SELECT count(*) FROM "{table.name}"'))).scalar_one() == 2
    await engine.dispose()


async def test_constraint_conflict_does_not_poison_transaction(golden_pkg_path, tmp_path):
    compiled = compile_package(load_package(golden_pkg_path))
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'current.db'}")
    repo, maker = ObjectRepository(compiled), make_sessionmaker(engine)
    async with maker() as db:
        await repo.ensure(db)
        await repo.action_insert(db, "material", {"material_id": "M-new", "name": "one"}, utcnow())
        table = repo._table("material")
        values = {"material_id": "M-new", "name": "two", "_rev": 1, "_valid_from": utcnow(), "_valid_to": None}
        with pytest.raises(ConflictError):
            await repo._insert_current(db, table, "material", values)
        assert (await db.execute(select(func.count()).select_from(table))).scalar_one() == 1
        with pytest.raises(IntegrityError):
            await repo._insert_current(db, table, "material", values | {"material_id": None})
        await db.commit()
    await engine.dispose()


async def test_create_is_rolled_back_with_outer_transaction(golden_pkg_path, tmp_path):
    compiled = compile_package(load_package(golden_pkg_path))
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'rollback.db'}")
    repo, maker = ObjectRepository(compiled), make_sessionmaker(engine)
    async with maker() as db:
        await repo.ensure(db)
        await db.commit()
    async with maker() as db:
        await repo.action_insert(db, "material", {"material_id": "M-rollback", "name": "one"}, utcnow())
        await db.rollback()
    async with maker() as db:
        assert await repo.get(db, "material", "M-rollback") is None
    await engine.dispose()


async def test_unique_index_uses_all_business_key_columns(golden_pkg_path, tmp_path):
    compiled = replace(compile_package(load_package(golden_pkg_path)), content_hash=uuid.uuid4().hex)
    compiled.objects["material"].spec.primaryKey = ["material_id", "name"]
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'composite.db'}")
    repo, maker = ObjectRepository(compiled), make_sessionmaker(engine)
    async with maker() as db:
        await repo.ensure(db)
        await repo.action_insert(db, "material", {"material_id": "M-composite", "name": "one"}, utcnow())
        await repo.action_insert(db, "material", {"material_id": "M-composite", "name": "two"}, utcnow())
        with pytest.raises(ConflictError):
            await repo.action_insert(db, "material", {"material_id": "M-composite", "name": "one"}, utcnow())
        await db.commit()
    await engine.dispose()


@pytest.mark.skipif(not os.environ.get("ONTOGENY_PG_DSN"), reason="PostgreSQL integration requires ONTOGENY_PG_DSN")
@pytest.mark.parametrize("method", ["action", "sync"])
@pytest.mark.parametrize("same_timestamp", [True, False])
async def test_postgres_concurrent_creates_one_live_version(
    golden_pkg_path, tmp_path, monkeypatch, method, same_timestamp
):
    monkeypatch.setenv("ONTOGENY_ADMIN_PASSWORD", secrets.token_urlsafe(32))
    sc = await _make(golden_pkg_path, tmp_path, db_dsn=os.environ["ONTOGENY_PG_DSN"])
    key = "M-" + uuid.uuid4().hex
    original = sc.repo._insert_current
    ready = asyncio.Event()
    arrived = 0

    async def race(*args):
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=10)
        return await original(*args)

    monkeypatch.setattr(sc.repo, "_insert_current", race)
    timestamp = utcnow()

    async def create():
        async with sc.sessionmaker() as db:
            try:
                props = {"material_id": key, "name": "race"}
                ts = timestamp if same_timestamp else utcnow()
                if method == "action":
                    await sc.repo.action_insert(db, "material", props, ts)
                else:
                    await sc.repo.sync_upsert(db, "material", props, ts)
            except ConflictError:
                # The savepoint has rolled back the failed statement; the
                # caller can still use and roll back the outer transaction.
                assert (await db.execute(select(1))).scalar_one() == 1
                await db.rollback()
                return "conflict"
            await db.commit()
            return "created"

    try:
        assert sorted(await asyncio.gather(create(), create())) == ["conflict", "created"]
        table = sc.repo._table("material")
        async with sc.sessionmaker() as db:
            count = (
                await db.execute(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.material_id == key, table.c._valid_to.is_(None))
                )
            ).scalar_one()
        assert count == 1
    finally:
        await sc.engine.dispose()
