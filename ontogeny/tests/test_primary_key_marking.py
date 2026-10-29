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

"""Marked primary keys cannot be safely returned as graph identities."""

import copy
from pathlib import Path

import yaml
from sqlalchemy import select

from ontogeny.core import validate
from ontogeny.registry.store import ResourceRow


def _tree(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_validator_rejects_marked_primary_key_but_accepts_non_key(golden_pkg):
    pkg = copy.deepcopy(golden_pkg)
    obj = pkg.find("ObjectType", "material")
    obj.spec.properties["material_id"].marking = "internal"
    issues = validate(pkg).issues
    assert any(i.code == "PK-MARKING" and i.resource == "ObjectType/material" for i in issues)
    obj.spec.properties["material_id"].marking = None
    assert obj.spec.properties["unit_cost"].marking == "internal"
    assert not any(i.code == "PK-MARKING" for i in validate(pkg).issues)
    obj.spec.primaryKey.append("name")
    obj.spec.properties["name"].marking = "internal"
    assert any(i.code == "PK-MARKING" and "name" in i.message for i in validate(pkg).issues)


async def test_builder_api_refuses_marked_primary_key_without_writing(client):
    c, sc = client
    root = Path(sc.package_root)
    before = _tree(root)
    compiled = sc.compiled
    resource = yaml.safe_load((root / "objects/material.yaml").read_text())
    resource["spec"]["properties"]["material_id"]["marking"] = "internal"
    response = await c.post("/api/v1/admin/builder/save", json={"resources": [resource]})
    assert response.status_code == 400, response.text
    assert any(i["code"] == "PK-MARKING" for i in response.json()["details"]["issues"])
    assert _tree(root) == before
    assert sc.compiled is compiled


async def test_publish_api_rejects_marked_primary_key_without_changing_registry(client):
    c, sc = client
    root = Path(sc.package_root)
    resource_path = root / "objects/material.yaml"
    resource = yaml.safe_load(resource_path.read_text())
    resource["spec"]["properties"]["material_id"]["marking"] = "internal"
    resource_path.write_text(yaml.safe_dump(resource, sort_keys=False))
    before = _tree(root)
    compiled = sc.compiled
    response = await c.post("/api/v1/admin/publish")
    assert response.status_code == 400, response.text
    assert "PK-MARKING" in response.text
    assert "surrogate key" in response.text
    assert _tree(root) == before
    assert sc.compiled is compiled
    async with sc.sessionmaker() as db:
        persisted = await sc.registry.load_latest(db)
    assert persisted.content_hash == compiled.content_hash


async def test_legacy_registry_preserves_marking_without_silent_changes(client):
    _, sc = client
    async with sc.sessionmaker() as db:
        row = (
            await db.execute(
                select(ResourceRow).where(ResourceRow.kind == "ObjectType", ResourceRow.api_name == "material")
            )
        ).scalar_one()
        definition = copy.deepcopy(row.definition)
        definition["spec"]["properties"]["material_id"]["marking"] = "internal"
        row.definition = definition
        await db.commit()
    async with sc.sessionmaker() as db:
        compiled = await sc.registry.load_latest(db)
        assert compiled.objects["material"].spec.properties["material_id"].marking == "internal"
    async with sc.sessionmaker() as db:
        saved = (
            await db.execute(
                select(ResourceRow).where(ResourceRow.kind == "ObjectType", ResourceRow.api_name == "material")
            )
        ).scalar_one()
        assert saved.definition == definition
