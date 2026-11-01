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
    tapeout_path = root / "objects" / "tapeout-version.yaml"
    tapeout = yaml.safe_load(tapeout_path.read_text())
    spec = tapeout["spec"]
    spec["primaryKey"] = ["version-id"]
    props = spec["properties"]
    props["version-id"] = props.pop("version_id")
    props["mask-cost"] = props.pop("mask_cost")
    props["SupplierCode"] = {"type": "string"}
    props["keys"] = {"type": "string"}
    props["reticleCount"] = {"type": "integer"}
    props["doubleReticle"] = {"type": "integer", "derived": "target.reticleCount * 2"}
    props["LiveScore"] = {"type": "integer", "derived": {"kind": "function", "entry": "capacity.py:capacity_check"}}
    spec["backing"]["mapping"] = {
        "version-id": "version_id",
        "mask-cost": "mask_cost",
        "SupplierCode": "project",
        "keys": "notes",
    }
    # the seeded package watermarks every object; snapshot semantics (absent
    # means archive, source value beats a stale action edit) is what the
    # resync assertion below needs -- same revert test_stores applies
    spec["backing"].pop("sync", None)
    tapeout_path.write_text(yaml.safe_dump(tapeout, sort_keys=False))
    for link_name in ("version-lots", "version-includes"):
        link_path = root / "links" / f"{link_name}.yaml"
        link_path.write_text(
            link_path.read_text()
            .replace("wafer-lot.version_id", "wafer-lot.version-ref")
            .replace("tapeout-version.version_id", "tapeout-version.version-id")
        )
    lot_path = root / "objects" / "wafer-lot.yaml"
    lot = yaml.safe_load(lot_path.read_text())
    lot["spec"]["properties"]["version-ref"] = lot["spec"]["properties"].pop("version_id")
    lot["spec"]["backing"]["mapping"] = {"version-ref": "version_id"}
    lot_path.write_text(yaml.safe_dump(lot, sort_keys=False))
    for action_name in ("start-lot", "create-tapeout-version"):
        action_path = root / "actions" / f"{action_name}.yaml"
        action = yaml.safe_load(action_path.read_text())
        properties = action["spec"]["effects"][0]["properties"]
        new_key = "version-ref" if action_name == "start-lot" else "version-id"
        properties[new_key] = properties.pop("version_id")
        action_path.write_text(yaml.safe_dump(action, sort_keys=False))
    source = tmp_path / "erp.db"
    seed_from_package(golden_pkg_path, source, force=True)
    settings = Settings(
        dev_auth=True,
        db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{source}", "FAB_WEBHOOK": "https://fab-portal.example.test/hook"},
    )
    sc = ServiceContext(settings, str(root))
    await sc.initialize()
    table = sc.repo._table("tapeout-version")
    async with sc.sessionmaker() as session:
        await session.execute(
            table.insert().values(
                version_id="TO-A0",
                project="A",
                mask_cost=1850000,
                suppliercode="S",
                keys="sheet",
                reticlecount=5,
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
    get = await client.get("/api/v1/objects/tapeout-version/TO-A0")
    assert get.status_code == 200
    assert "mask_cost" not in get.json()
    assert get.json()["mask-cost"] == "__masked__"
    query = await client.post("/api/v1/objects/tapeout-version/query", json={})
    assert query.json()["objects"][0]["mask-cost"] == "__masked__"
    filtered = await client.post("/api/v1/objects/tapeout-version/query", json={"filter": {"keys": "sheet"}})
    assert filtered.status_code == 200 and filtered.json()["total"] == 1
    history = await client.get("/api/v1/objects/tapeout-version/TO-A0/history")
    assert history.json()["versions"][0]["mask-cost"] == "__masked__"
    authorized = await client.get("/api/v1/objects/tapeout-version/TO-A0", headers=_claim())
    assert authorized.json()["mask-cost"] == 1850000
    assert authorized.json()["version-id"] == "TO-A0"
    assert authorized.json()["SupplierCode"] == "S"
    assert authorized.json()["doubleReticle"] == 10


async def test_declared_names_are_preserved_through_sync_actions_and_links(named_client):
    from ontogeny.stores.repo import utcnow

    _, sc = named_client
    assert (await sc.sync("tapeout-version"))["inserted"] > 0
    assert (await sc.sync("wafer-lot"))["inserted"] > 0
    async with sc.sessionmaker() as session:
        tapeout = await sc.repo.get(session, "tapeout-version", "TO-A0")
        assert tapeout["version-id"] == "TO-A0" and tapeout["mask-cost"] == 1850000
        assert tapeout["SupplierCode"] == "X1"
        assert (await sc.repo.get_many(session, "tapeout-version", ["TO-A0"]))[0] == tapeout
        await sc.repo.set_derived_value(session, "tapeout-version", "TO-A0", "LiveScore", 42, utcnow())
        updated = await sc.repo.action_update(
            session, "tapeout-version", "TO-A0", {"SupplierCode": "changed", "mask-cost": 211}, utcnow()
        )
        assert updated["SupplierCode"] == "changed" and updated["LiveScore"] == 42
        assert updated["mask-cost"] == 211
        assert updated["version-id"] == "TO-A0" and "version_id" not in updated
        inserted = await sc.repo.action_insert(
            session,
            "tapeout-version",
            {"version-id": "TO-X", "project": "Test", "mask-cost": 9, "SupplierCode": "K"},
            utcnow(),
        )
        assert inserted["version-id"] == "TO-X" and inserted["SupplierCode"] == "K" and inserted["mask-cost"] == 9
        assert (await sc.repo.history(session, "tapeout-version", "TO-A0"))[-1]["SupplierCode"] == "changed"
        assert await sc.repo.fk_linked_ids(session, "version-lots", "LOT-2417", from_source=False) == ["TO-A0"]
        links = await sc.query.links(session, "wafer-lot", "LOT-2417", "version-lots", {"id": "anon"})
        assert links[0]["version-id"] == "TO-A0" and links[0]["mask-cost"] == "__masked__"
        traversal = await sc.query.traverse(
            session, "wafer-lot", ["LOT-2417"], {"id": "anon"}, [{"link": "version-lots", "direction": "in"}]
        )
        assert traversal["steps"][-1]["objects"][0]["mask-cost"] == "__masked__"
        await session.commit()
    await sc.sync("tapeout-version")
    async with sc.sessionmaker() as session:
        resynced = await sc.repo.get(session, "tapeout-version", "TO-A0")
        assert resynced["mask-cost"] == 1850000 and resynced["LiveScore"] == 42


async def test_marked_filters_sort_and_aggregates_preserve_claims(named_client):
    client, _ = named_client
    for payload in ({"filter": {"mask-cost": 1850000}}, {"sort": "mask-cost-desc"}):
        assert (await client.post("/api/v1/objects/tapeout-version/query", json=payload)).status_code == 403
        allowed = await client.post("/api/v1/objects/tapeout-version/query", json=payload, headers=_claim())
        assert allowed.status_code == 200 and allowed.json()["objects"][0]["mask-cost"] == 1850000
    denied = await client.post("/api/v1/objects/tapeout-version/aggregate", json={"fn": "sum", "field": "mask-cost"})
    assert denied.status_code == 403
    assert (
        await client.post("/api/v1/objects/tapeout-version/query", json={"filter": {"mask_cost": 1850000}})
    ).status_code == 403
    assert (
        await client.post("/api/v1/objects/tapeout-version/aggregate", json={"fn": "sum", "field": "mask_cost"})
    ).status_code == 403
    allowed = await client.post(
        "/api/v1/objects/tapeout-version/aggregate", json={"fn": "sum", "field": "mask-cost"}, headers=_claim()
    )
    assert allowed.status_code == 200 and allowed.json()["value"] == 1850000


async def test_repeated_updates_and_archive_have_strictly_ordered_versions(named_client):
    _, sc = named_client
    async with sc.sessionmaker() as session:
        original = await sc.repo.get(session, "tapeout-version", "TO-A0")
        ts = original["_valid_from"]
        await sc.repo.action_update(session, "tapeout-version", "TO-A0", {"SupplierCode": "first"}, ts)
        await sc.repo.action_update(session, "tapeout-version", "TO-A0", {"SupplierCode": "second"}, ts)
        await sc.repo.archive(session, "tapeout-version", "TO-A0", ts)
        versions = await sc.repo.history(session, "tapeout-version", "TO-A0")
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
        await sc.repo.action_insert(session, "tapeout-version", {"version-id": "TO-RECREATE", "project": "first"}, ts)
        await sc.repo.archive(session, "tapeout-version", "TO-RECREATE", ts)
        inserted = await sc.repo.action_insert(
            session, "tapeout-version", {"version-id": "TO-RECREATE", "project": "restored"}, ts
        )
        assert inserted["project"] == "restored"
        versions = await sc.repo.history(session, "tapeout-version", "TO-RECREATE")
        assert len(versions) == 2
        assert versions[0]["_valid_from"] < versions[0]["_valid_to"] < versions[1]["_valid_from"]
        await session.commit()
