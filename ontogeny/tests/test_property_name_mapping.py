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

"""Declared property names survive SQL storage without bypassing masking."""

import json
import shutil
from datetime import UTC, datetime

import httpx
import pytest_asyncio
import yaml

from ontogeny.api import build_app
from ontogeny.config import Settings
from ontogeny.demo import seed_from_package
from ontogeny.service import ServiceContext


@pytest_asyncio.fixture()
async def named_client(golden_pkg_path, tmp_path):
    root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, root)
    material_path = root / "objects" / "material.yaml"
    material = yaml.safe_load(material_path.read_text())
    spec = material["spec"]
    spec["primaryKey"] = ["material-id"]
    props = spec["properties"]
    props["material-id"] = props.pop("material_id")
    props["unit-cost"] = props.pop("unit_cost")
    props["SupplierCode"] = {"type": "string"}
    props["keys"] = {"type": "string"}
    props["doubleStock"] = {"type": "integer", "derived": "target.stock_qty * 2"}
    props["LiveScore"] = {"type": "integer", "derived": {"kind": "function", "entry": "capacity.py:capacity_check"}}
    spec["backing"]["mapping"] = {
        "material-id": "material_id",
        "unit-cost": "unit_cost",
        "SupplierCode": "name",
        "keys": "unit",
    }
    material_path.write_text(yaml.safe_dump(material, sort_keys=False))
    link_path = root / "links" / "bom-material.yaml"
    link_path.write_text(
        link_path.read_text()
        .replace("material.material_id", "material.material-id")
        .replace("bom.material_id", "bom.material-ref")
    )
    bom_path = root / "objects" / "bom.yaml"
    bom = yaml.safe_load(bom_path.read_text())
    bom["spec"]["properties"]["material-ref"] = bom["spec"]["properties"].pop("material_id")
    bom["spec"]["backing"]["mapping"] = {"material-ref": "material_id"}
    bom_path.write_text(yaml.safe_dump(bom, sort_keys=False))
    action_path = root / "actions" / "add-bom-line.yaml"
    action = yaml.safe_load(action_path.read_text())
    action["spec"]["effects"][0]["properties"]["material-ref"] = action["spec"]["effects"][0]["properties"].pop(
        "material_id"
    )
    action_path.write_text(yaml.safe_dump(action, sort_keys=False))
    source = tmp_path / "erp.db"
    seed_from_package(golden_pkg_path, source, force=True)
    settings = Settings(
        dev_auth=True,
        db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{source}", "WMS_WEBHOOK": "https://wms.example.test/hook"},
    )
    sc = ServiceContext(settings, str(root))
    await sc.initialize()
    table = sc.repo._table("material")
    async with sc.sessionmaker() as session:
        await session.execute(
            table.insert().values(
                material_id="M-101",
                name="A",
                unit_cost=210,
                suppliercode="S",
                keys="sheet",
                stock_qty=5,
                _rev=1,
                _valid_from=datetime.now(UTC),
            )
        )
        await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_app(sc)), base_url="http://test") as c:
        try:
            yield c, sc
        finally:
            await sc.engine.dispose()


def _claim():
    return {"X-Ontogeny-Principal": json.dumps({"id": "owner", "markings": ["internal"]})}


async def test_declared_marked_name_is_masked_on_get_and_query(named_client):
    client, _ = named_client
    get = await client.get("/api/v1/objects/material/M-101")
    assert get.status_code == 200
    assert "unit_cost" not in get.json()
    assert get.json()["unit-cost"] == "__masked__"
    query = await client.post("/api/v1/objects/material/query", json={})
    assert query.json()["objects"][0]["unit-cost"] == "__masked__"
    filtered = await client.post("/api/v1/objects/material/query", json={"filter": {"keys": "sheet"}})
    assert filtered.status_code == 200 and filtered.json()["total"] == 1
    history = await client.get("/api/v1/objects/material/M-101/history")
    assert history.json()["versions"][0]["unit-cost"] == "__masked__"
    authorized = await client.get("/api/v1/objects/material/M-101", headers=_claim())
    assert authorized.json()["unit-cost"] == 210
    assert authorized.json()["material-id"] == "M-101"
    assert authorized.json()["SupplierCode"] == "S"
    assert authorized.json()["doubleStock"] == 10


async def test_declared_names_are_preserved_through_sync_actions_and_links(named_client):
    from ontogeny.stores.repo import utcnow

    _, sc = named_client
    assert (await sc.sync("material"))["inserted"] > 0
    assert (await sc.sync("bom"))["inserted"] > 0
    async with sc.sessionmaker() as session:
        material = await sc.repo.get(session, "material", "M-101")
        assert material["material-id"] == "M-101" and material["unit-cost"] == 210
        assert material["SupplierCode"] == "Steel Plate S45C"
        assert (await sc.repo.get_many(session, "material", ["M-101"]))[0] == material
        await sc.repo.set_derived_value(session, "material", "M-101", "LiveScore", 42, utcnow())
        updated = await sc.repo.action_update(
            session, "material", "M-101", {"SupplierCode": "changed", "unit-cost": 211}, utcnow()
        )
        assert updated["SupplierCode"] == "changed" and updated["LiveScore"] == 42
        assert updated["unit-cost"] == 211
        assert updated["material-id"] == "M-101" and "material_id" not in updated
        inserted = await sc.repo.action_insert(
            session, "material", {"material-id": "M-X", "name": "Test", "unit-cost": 9, "SupplierCode": "K"}, utcnow()
        )
        assert inserted["material-id"] == "M-X" and inserted["SupplierCode"] == "K" and inserted["unit-cost"] == 9
        assert (await sc.repo.history(session, "material", "M-101"))[-1]["SupplierCode"] == "changed"
        assert await sc.repo.fk_linked_ids(session, "bom-material", "B-1001", from_source=False) == ["M-101"]
        links = await sc.query.links(session, "bom", "B-1001", "bom-material", {"id": "anon"})
        assert links[0]["material-id"] == "M-101" and links[0]["unit-cost"] == "__masked__"
        traversal = await sc.query.traverse(
            session, "bom", ["B-1001"], {"id": "anon"}, [{"link": "bom-material", "direction": "in"}]
        )
        assert traversal["steps"][-1]["objects"][0]["unit-cost"] == "__masked__"
        await session.commit()
    await sc.sync("material")
    async with sc.sessionmaker() as session:
        resynced = await sc.repo.get(session, "material", "M-101")
        assert resynced["unit-cost"] == 210 and resynced["LiveScore"] == 42


async def test_marked_filters_sort_and_aggregates_preserve_claims(named_client):
    client, _ = named_client
    for payload in ({"filter": {"unit-cost": 210}}, {"sort": "unit-cost-desc"}):
        assert (await client.post("/api/v1/objects/material/query", json=payload)).status_code == 403
        allowed = await client.post("/api/v1/objects/material/query", json=payload, headers=_claim())
        assert allowed.status_code == 200 and allowed.json()["objects"][0]["unit-cost"] == 210
    denied = await client.post("/api/v1/objects/material/aggregate", json={"fn": "sum", "field": "unit-cost"})
    assert denied.status_code == 403
    assert (await client.post("/api/v1/objects/material/query", json={"filter": {"unit_cost": 210}})).status_code == 403
    assert (
        await client.post("/api/v1/objects/material/aggregate", json={"fn": "sum", "field": "unit_cost"})
    ).status_code == 403
    allowed = await client.post(
        "/api/v1/objects/material/aggregate", json={"fn": "sum", "field": "unit-cost"}, headers=_claim()
    )
    assert allowed.status_code == 200 and allowed.json()["value"] == 210


async def test_repeated_updates_and_archive_have_strictly_ordered_versions(named_client):
    _, sc = named_client
    async with sc.sessionmaker() as session:
        original = await sc.repo.get(session, "material", "M-101")
        ts = original["_valid_from"]
        await sc.repo.action_update(session, "material", "M-101", {"SupplierCode": "first"}, ts)
        await sc.repo.action_update(session, "material", "M-101", {"SupplierCode": "second"}, ts)
        await sc.repo.archive(session, "material", "M-101", ts)
        versions = await sc.repo.history(session, "material", "M-101")
        assert len(versions) == 3
        assert [v["SupplierCode"] for v in versions] == ["S", "first", "second"]
        assert all(v["_valid_from"] < v["_valid_to"] for v in versions)
        assert versions[0]["_valid_to"] == versions[1]["_valid_from"]
        assert versions[1]["_valid_to"] == versions[2]["_valid_from"]
        await session.commit()


async def test_recreate_archived_key_at_same_timestamp_keeps_valid_history(named_client):
    _, sc = named_client
    async with sc.sessionmaker() as session:
        ts = datetime.now(UTC)
        await sc.repo.action_insert(session, "material", {"material-id": "M-recreate", "name": "first"}, ts)
        await sc.repo.archive(session, "material", "M-recreate", ts)
        inserted = await sc.repo.action_insert(
            session, "material", {"material-id": "M-recreate", "name": "restored"}, ts
        )
        assert inserted["name"] == "restored"
        versions = await sc.repo.history(session, "material", "M-recreate")
        assert len(versions) == 2
        assert versions[0]["_valid_from"] < versions[0]["_valid_to"] < versions[1]["_valid_from"]
        await session.commit()
