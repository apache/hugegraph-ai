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

import json
import os
import secrets
import shutil
import uuid
from dataclasses import replace

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ontogeny.action.models import OutboxRow
from ontogeny.api import build_app
from ontogeny.config import Settings
from ontogeny.core.models import PropertyDef
from ontogeny.functions.derivation import DerivationPendingRow
from ontogeny.service import ServiceContext
from ontogeny.stores.repo import utcnow


@pytest.mark.skipif(not os.environ.get("ONTOGENY_PG_DSN"), reason="PostgreSQL integration requires ONTOGENY_PG_DSN")
async def test_postgres_numeric_and_string_keys_across_api_action_and_repository(
    golden_pkg_path, tmp_path, monkeypatch
):
    dsn = os.environ["ONTOGENY_PG_DSN"]
    schema = f"keys_test_{uuid.uuid4().hex}"
    admin = create_async_engine(dsn)
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(dsn, connect_args={"server_settings": {"search_path": schema}})
    monkeypatch.setattr("ontogeny.service.make_engine", lambda _: engine)
    monkeypatch.setenv("ONTOGENY_ADMIN_PASSWORD", secrets.token_urlsafe(32))
    pkg = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, pkg)
    sc = ServiceContext(Settings(db_dsn=dsn, dev_auth=True, data_dir=str(tmp_path)), str(pkg))
    try:
        await sc.initialize()
        compiled = sc.compiled
        numeric = compiled.objects["material"].model_copy(deep=True)
        numeric.metadata.name = "int-material"
        numeric.spec.properties["material_id"].type = "integer"
        numeric.spec.properties["derived_count"] = PropertyDef(
            type="integer", derived={"kind": "function", "entry": "unused.py:count", "triggers": ["int-bom"]}
        )
        composite = numeric.model_copy(deep=True)
        composite.metadata.name = "composite-material"
        composite.spec.primaryKey = ["material_id", "name"]
        composite.spec.properties.pop("derived_count")
        bom = compiled.objects["bom"].model_copy(deep=True)
        bom.metadata.name = "int-bom"
        bom.spec.properties["material_id"].type = "integer"
        link = compiled.links["bom-material"].model_copy(deep=True)
        link.metadata.name = "int-bom-material"
        link.spec.source = "int-material"
        link.spec.target = "int-bom"
        link.spec.join.keys = {"int-bom.material_id": "int-material.material_id"}
        action = compiled.actions["receive-material"].model_copy(deep=True)
        action.spec.target = "int-material"
        sc._rebuild_services(
            replace(
                compiled,
                content_hash=uuid.uuid4().hex,
                objects={**compiled.objects, "int-material": numeric, "composite-material": composite, "int-bom": bom},
                actions={**compiled.actions, "receive-material": action},
                links={**compiled.links, "int-bom-material": link},
            )
        )
        async with sc.sessionmaker() as s:
            await sc.repo.ensure(s)
            await sc.repo.action_insert(
                s, "int-material", {"material_id": "42", "name": "numeric", "stock_qty": 1}, utcnow()
            )
            await sc.repo.action_insert(s, "material", {"material_id": "0042", "name": "leading"}, utcnow())
            await sc.repo.action_insert(s, "material", {"material_id": "42", "name": "plain"}, utcnow())
            await sc.repo.action_insert(s, "composite-material", {"material_id": 42, "name": "a"}, utcnow())
            await sc.repo.action_insert(s, "composite-material", {"material_id": 42, "name": "b"}, utcnow())
            await sc.repo.action_insert(
                s, "int-bom", {"bom_id": "line", "material_id": 42, "product_id": "p"}, utcnow()
            )
            await s.commit()

        await sc.derivation.handle_event(OutboxRow(object_type="int-bom", object_id="line", op="upsert"))
        async with sc.sessionmaker() as s:
            assert await s.get(DerivationPendingRow, {"object_type": "int-material", "object_id": "42"}) is not None

        headers = {"X-Ontogeny-Principal": json.dumps({"id": "planner", "Role": ["planner"]})}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=build_app(sc)), base_url="http://test", headers=headers
        ) as client:
            response = await client.get("/api/v1/objects/int-material/42")
            assert response.status_code == 200 and response.json()["material_id"] == 42
            response = await client.get("/api/v1/objects/material/0042")
            assert response.status_code == 200 and response.json()["name"] == "leading"
            response = await client.get("/api/v1/objects/int-material/42/links/int-bom-material")
            assert response.status_code == 200, response.text
            assert response.json()[0]["bom_id"] == "line"
            response = await client.post(
                "/api/v1/actions/receive-material/execute", json={"target_id": "42", "parameters": {"counted_qty": 12}}
            )
            assert response.status_code == 200, response.text
            assert response.json()["after"]["stock_qty"] == 12
            response = await client.get("/api/v1/objects/int-material/42/history")
            assert response.status_code == 200 and len(response.json()["versions"]) == 2
            assert (await client.get("/api/v1/objects/int-material/not-an-integer")).status_code == 422

        async with sc.sessionmaker() as s:
            assert (await sc.repo.get_many(s, "int-material", ["42"]))[0]["material_id"] == 42
            assert (await sc.repo.get(s, "material", "42"))["name"] == "plain"
            await sc.repo.set_derived_value(s, "int-material", "42", "stock_qty", 15, utcnow())
            assert (await sc.repo.get(s, "int-material", "42"))["stock_qty"] == 15
            assert (
                await sc.repo.sync_upsert(s, "int-material", {"material_id": "43", "name": "source"}, utcnow())
                == "inserted"
            )
            assert (await sc.repo.get(s, "int-material", "43"))["material_id"] == 43
            assert await sc.repo.alive_keys(s, "composite-material") == {(42, "a"), (42, "b")}
            assert len(await sc.repo.get_many(s, "composite-material", [("42", "a"), ("42", "b")])) == 2
            await sc.repo.action_update(s, "composite-material", ("42", "a"), {"stock_qty": 8}, utcnow())
            assert len(await sc.repo.history(s, "composite-material", ("42", "a"))) == 2
            await sc.repo.archive(s, "composite-material", ("42", "a"), utcnow())
            assert await sc.repo.get(s, "composite-material", ("42", "a")) is None
            assert (await sc.repo.get(s, "composite-material", ("42", "b")))["name"] == "b"
            await s.commit()
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
