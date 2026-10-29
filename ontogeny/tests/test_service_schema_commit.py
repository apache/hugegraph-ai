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

"""All service snapshot callers commit DDL before exposing runtime and MCP."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
import yaml
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from test_domain_table_conflicts import package

from ontogeny.config import Settings
from ontogeny.core import load_package
from ontogeny.mcp_server import McpSurface
from ontogeny.service import ServiceContext
from ontogeny.stores.ddl import object_table
from ontogeny.stores.repo import utcnow


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def database(request, tmp_path, monkeypatch):
    import ontogeny.service as service

    monkeypatch.setenv("ONTOGENY_ADMIN_PASSWORD", "schema-regression-password")
    schema = None
    admin = None
    contexts = []
    if request.param == "postgres":
        dsn = os.environ.get("ONTOGENY_PG_DSN")
        if not dsn:
            pytest.skip("PostgreSQL integration requires ONTOGENY_PG_DSN")
        schema = "schema_commit_" + uuid.uuid4().hex
        admin = create_async_engine(dsn)
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        monkeypatch.setattr(
            service,
            "make_engine",
            lambda dsn: create_async_engine(dsn, connect_args={"server_settings": {"search_path": schema}}),
        )
    else:
        dsn = f"sqlite+aiosqlite:///{tmp_path / 'main.db'}"
    root = package(tmp_path / "source", "source-domain", ["product"])
    settings = Settings(db_dsn=dsn, data_dir=str(tmp_path / "credentials"))

    async def context(path=root):
        sc = ServiceContext(settings, str(path))
        contexts.append(sc)
        await sc.initialize()
        return sc

    try:
        sc = await context()
        yield {"sc": sc, "root": root, "tmp": tmp_path, "context": context}
    finally:
        for sc in reversed(contexts):
            if sc.engine is not None:
                await sc.engine.dispose()
        if admin is not None:
            async with admin.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()


async def columns(sc, name):
    async with sc.engine.connect() as connection:
        return await connection.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns(name)})


async def tables(sc):
    async with sc.engine.connect() as connection:
        return await connection.run_sync(lambda c: set(inspect(c).get_table_names()))


async def test_reload_commits_new_optional_column(database):
    sc, root = database["sc"], database["root"]
    path = root / "objects/product.yaml"
    document = yaml.safe_load(path.read_text())
    document["spec"]["properties"]["extra"] = {"type": "string"}
    path.write_text(yaml.safe_dump(document))
    # An evolution publisher commits the registry before asking the service
    # to reload; the service must durably install the additive DDL itself.
    async with sc.sessionmaker() as session:
        await sc.registry.publish(session, load_package(root))
        await session.commit()
    await sc.reload()
    assert "extra" in await columns(sc, sc.compiled.table_name("product"))
    async with sc.sessionmaker() as session:
        await sc.repo.action_insert(session, "product", {"id": "P-1", "name": "product", "extra": "new"}, utcnow())
        await session.commit()
    async with sc.sessionmaker() as session:
        assert (await sc.repo.get(session, "product", "P-1"))["extra"] == "new"


async def test_activate_commits_new_object_table_and_survives_restart(database):
    sc = database["sc"]
    target = package(database["tmp"] / "target", "target-domain", ["shipment"])
    await sc.activate_domain(target)
    assert sc.compiled.table_name("shipment") in await tables(sc)
    async with sc.sessionmaker() as session:
        await sc.repo.action_insert(session, "shipment", {"id": "S-1", "name": "shipment"}, utcnow())
        await session.commit()
    restarted = await database["context"](target)
    assert restarted.compiled.package_name == "target-domain"
    async with restarted.sessionmaker() as session:
        assert (await restarted.repo.get(session, "shipment", "S-1"))["name"] == "shipment"


async def test_existing_registry_initialization_commits_missing_tables(database):
    sc = database["sc"]
    table = object_table(sc.compiled, "product")
    async with sc.engine.begin() as connection:
        await connection.run_sync(lambda c: table.drop(c))
    assert table.name not in await tables(sc)
    restarted = await database["context"]()
    assert table.name in await tables(restarted)
    async with restarted.sessionmaker() as session:
        await restarted.repo.action_insert(session, "product", {"id": "P-1", "name": "restored"}, utcnow())
        await session.commit()
    async with restarted.sessionmaker() as session:
        assert (await restarted.repo.get(session, "product", "P-1"))["name"] == "restored"


@pytest.mark.parametrize("operation", ["reload", "activate"])
@pytest.mark.parametrize("commit_succeeds", [True, False])
async def test_snapshot_runtime_and_mcp_remain_committed_until_schema_commit(
    database, monkeypatch, operation, commit_succeeds
):
    sc, root = database["sc"], database["root"]
    async with sc.sessionmaker() as session:
        await sc.repo.action_insert(session, "product", {"id": "P-1", "name": "old runtime"}, utcnow())
        await session.commit()
    surface = sc.mcp_surface = McpSurface(sc)
    surface.build()
    assert surface.server is not None
    manager, runtime, original_path = surface.server._tool_manager, sc.compiled, sc.package_root
    if operation == "reload":
        package(root, "source-domain", ["product", "shipment"])
        async with sc.sessionmaker() as session:
            await sc.registry.publish(session, load_package(root))
            await session.commit()
        run = sc.reload
    else:
        target = package(database["tmp"] / "target", "target-domain", ["shipment"])

        async def run():
            return await sc.activate_domain(target)

    commit = AsyncSession.commit
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_commit(session):
        entered.set()
        await release.wait()
        if not commit_succeeds:
            raise RuntimeError("schema commit rejected")
        await commit(session)

    monkeypatch.setattr(AsyncSession, "commit", blocked_commit)
    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        assert sc.compiled is runtime and sc.package_root == original_path
        assert surface.server._tool_manager is manager
        assert "search_shipment" not in {tool.name for tool in await surface.server.list_tools()}
        async with sc.sessionmaker() as session:
            row = await sc.query.get(session, "product", "P-1", {"id": "reader"})
        assert row["name"] == "old runtime"
    finally:
        release.set()
    if commit_succeeds:
        await task
        assert "shipment" in sc.compiled.objects
        assert surface.server._tool_manager is not manager
        assert "search_shipment" in {tool.name for tool in await surface.server.list_tools()}
        assert sc.compiled.table_name("shipment") in await tables(sc)
    else:
        with pytest.raises(RuntimeError, match="schema commit rejected"):
            await task
        assert sc.compiled is runtime and sc.package_root == original_path
        assert surface.server._tool_manager is manager
        if operation == "activate":
            async with sc.sessionmaker() as session:
                assert (await sc.registry.load_latest(session)).package_name == "source-domain"
