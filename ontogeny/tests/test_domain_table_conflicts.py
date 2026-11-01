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

"""Reject shared domain tables before touching registry or object data."""

import asyncio

import pytest
import yaml
from sqlalchemy import select

from ontogeny.config import Settings
from ontogeny.core import load_package
from ontogeny.errors import DSLValidationError
from ontogeny.registry.store import ResourceRow
from ontogeny.service import ServiceContext
from ontogeny.stores.repo import utcnow
from ontogeny.stores.sync import SyncStateRow


def package(root, name, objects=(), link=None):
    root.mkdir(parents=True, exist_ok=True)

    def resource(kind, name, spec):
        directory = {"Ontology": "", "Store": "stores", "ObjectType": "objects", "LinkType": "links"}[kind]
        path = root / directory
        path.mkdir(exist_ok=True)
        (path / ("ontology.yaml" if kind == "Ontology" else name + ".yaml")).write_text(
            yaml.safe_dump({"apiVersion": "ontogeny/v1", "kind": kind, "metadata": {"name": name}, "spec": spec})
        )

    resource("Ontology", name, {"imports": []})
    if objects:
        resource("Store", "source", {"type": "sqlite", "connection": "sqlite+aiosqlite:///:memory:"})
    for obj in objects:
        resource(
            "ObjectType",
            obj,
            {
                "primaryKey": ["id"],
                "properties": {"id": {"type": "string", "required": True}, "name": {"type": "string"}},
                "backing": {"store": "source", "mode": "materialized", "source": {"table": obj}},
            },
        )
    if link:
        resource(
            "LinkType",
            link,
            {
                "source": objects[0],
                "target": objects[1],
                "cardinality": "MANY_TO_MANY",
                "join": {
                    "kind": "join-table",
                    "store": "source",
                    "relation": {"table": "members"},
                    "keys": {"source": {"id": "src_id"}, "target": {"id": "dst_id"}},
                },
            },
        )
    return root


async def test_conflicting_activation_preserves_objects_checkpoint_and_restart(tmp_path):
    first = package(tmp_path / "first", "first-domain", ["product"])
    second = package(tmp_path / "second", "second-domain", ["product"])
    sc = ServiceContext(Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}"), str(first))
    await sc.initialize()
    try:
        async with sc.sessionmaker() as db:
            await sc.repo.action_insert(db, "product", {"id": "P-1", "name": "first"}, utcnow())
            db.add(SyncStateRow(store="source", object_type="product", watermark="9"))
            await db.commit()
        old_runtime = sc.compiled
        with pytest.raises(DSLValidationError, match="already owned"):
            await sc.activate_domain(second)
        assert sc.compiled is old_runtime
        assert sc.package_root == str(first)
        async with sc.sessionmaker() as db:
            assert (await sc.repo.get(db, "product", "P-1"))["name"] == "first"
            assert (await db.get(SyncStateRow, ("source", "product"))).watermark == "9"
            assert await db.scalar(select(ResourceRow).where(ResourceRow.pkg == "second-domain")) is None
            assert (await sc.registry.load_latest(db)).package_name == "first-domain"
        restarted = ServiceContext(sc.settings, str(first))
        try:
            await restarted.initialize()
            assert restarted.compiled.package_name == "first-domain"
            async with restarted.sessionmaker() as db:
                assert (await restarted.repo.get(db, "product", "P-1"))["name"] == "first"
        finally:
            await restarted.engine.dispose()
    finally:
        await sc.engine.dispose()


@pytest.mark.parametrize("retire", [False, True])
async def test_publish_cannot_claim_another_domains_current_or_retired_tables(tmp_path, retire):
    first = package(tmp_path / "first", "first-domain", ["product"])
    empty = package(tmp_path / "empty", "empty-domain")
    second = package(tmp_path / "second", "second-domain", ["product"])
    sc = ServiceContext(Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}"), str(first))
    await sc.initialize()
    try:
        if retire:
            await sc.activate_domain(empty)
        async with sc.sessionmaker() as db:
            with pytest.raises(DSLValidationError, match="first-domain"):
                await sc.registry.publish(db, load_package(second))
            # A caller committing after handling rejection must not change active rows.
            await db.commit()
            active = await sc.registry.load_latest(db)
            assert active.package_name == ("empty-domain" if retire else "first-domain")
        await sc.activate_domain(first)
        assert sc.compiled.package_name == "first-domain"
    finally:
        await sc.engine.dispose()


async def test_join_table_names_are_reserved_even_with_disjoint_object_names(tmp_path):
    first = package(tmp_path / "first", "first-domain", ["container", "item"], "members")
    second = package(tmp_path / "second", "second-domain", ["group", "person"], "members")
    sc = ServiceContext(Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}"), str(first))
    await sc.initialize()
    try:
        async with sc.sessionmaker() as db:
            await sc.repo.link_add(db, "members", "C-1", "I-1", utcnow())
            await db.commit()
        with pytest.raises(DSLValidationError, match="ontogeny_lnk_members"):
            await sc.activate_domain(second)
        async with sc.sessionmaker() as db:
            assert await sc.repo.link_members(db, "members") == [("C-1", "I-1")]
    finally:
        await sc.engine.dispose()


async def test_disjoint_domains_can_switch_and_retain_their_data(tmp_path):
    first = package(tmp_path / "first", "first-domain", ["product"])
    second = package(tmp_path / "second", "second-domain", ["shipment"])
    sc = ServiceContext(Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}"), str(first))
    await sc.initialize()
    try:
        async with sc.sessionmaker() as db:
            await sc.repo.action_insert(db, "product", {"id": "1", "name": "product"}, utcnow())
            await db.commit()
        await sc.activate_domain(second)
        async with sc.sessionmaker() as db:
            assert await sc.repo.get(db, "shipment", "1") is None
            await sc.repo.action_insert(db, "shipment", {"id": "1", "name": "shipment"}, utcnow())
            await db.commit()
        await sc.activate_domain(first)
        async with sc.sessionmaker() as db:
            assert (await sc.repo.get(db, "product", "1"))["name"] == "product"
        await sc.activate_domain(second)
        async with sc.sessionmaker() as db:
            assert (await sc.repo.get(db, "shipment", "1"))["name"] == "shipment"
    finally:
        await sc.engine.dispose()


async def test_concurrent_activation_cannot_claim_the_same_table(tmp_path):
    empty = package(tmp_path / "empty", "empty-domain")
    first = package(tmp_path / "first", "first-domain", ["product"])
    second = package(tmp_path / "second", "second-domain", ["product"])
    sc = ServiceContext(Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}"), str(empty))
    await sc.initialize()
    try:
        results = await asyncio.gather(sc.activate_domain(first), sc.activate_domain(second), return_exceptions=True)
        assert sum(isinstance(result, DSLValidationError) for result in results) == 1
        assert sum(not isinstance(result, BaseException) for result in results) == 1
        async with sc.sessionmaker() as db:
            assert (await sc.registry.load_latest(db)).package_name == sc.compiled.package_name
    finally:
        await sc.engine.dispose()


async def test_join_table_remains_reserved_after_the_link_becomes_foreign_key(tmp_path):
    first = package(tmp_path / "first", "first-domain", ["container", "item"], "members")
    second = package(tmp_path / "second", "second-domain", ["group", "person"], "members")
    sc = ServiceContext(Settings(db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}"), str(first))
    await sc.initialize()
    try:
        async with sc.sessionmaker() as db:
            await sc.repo.link_add(db, "members", "C-1", "I-1", utcnow())
            await db.commit()
        item_file = first / "objects" / "item.yaml"
        item = yaml.safe_load(item_file.read_text())
        item["spec"]["properties"]["container_id"] = {"type": "string"}
        item_file.write_text(yaml.safe_dump(item))
        link_file = first / "links" / "members.yaml"
        link = yaml.safe_load(link_file.read_text())
        link["spec"]["join"] = {"kind": "foreign-key", "keys": {"item.container_id": "container.id"}}
        link_file.write_text(yaml.safe_dump(link))
        await sc.publish(str(first))
        with pytest.raises(DSLValidationError, match="ontogeny_lnk_members"):
            await sc.activate_domain(second)
        async with sc.sessionmaker() as db:
            from sqlalchemy import text

            rows = (await db.execute(text("SELECT src_id, dst_id FROM ontogeny_lnk_members"))).all()
            assert rows == [("C-1", "I-1")]
    finally:
        await sc.engine.dispose()
