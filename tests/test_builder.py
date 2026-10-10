# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Scenario Builder save endpoint: partial save, sidecar policies, deletes.

The builder's contract with the golden example's guard: tests operate on a
tmp copy, and partial saves must never rewrite untouched YAML (effects and
derived configs would be stripped by the lossy meta round-trip).
"""
from __future__ import annotations

import json
import shutil

import httpx
import pytest_asyncio
import yaml

from ontogeny.api import build_app
from ontogeny.config import Settings
from ontogeny.service import ServiceContext

INSPECTION_POINT = {
    "apiVersion": "ontogeny/v1",
    "kind": "ObjectType",
    "metadata": {"name": "inspection-point", "display": "Inspection point",
                 "description": "A quality inspection checkpoint"},
    "spec": {
        "primaryKey": ["point_id"],
        "properties": {
            "point_id": {"type": "string", "required": True},
            "name": {"type": "string"},
            "cycle_days": {"type": "integer"},
        },
        "backing": {
            "store": "mes",
            "mode": "materialized",
            "source": {"schema": "mes", "table": "inspection_point"},
            "mapping": {},
            "sync": {"strategy": "snapshot"},
        },
    },
}

INSPECTION_POLICY = {
    "apiVersion": "ontogeny/v1",
    "kind": "PolicySet",
    "metadata": {"name": "inspection-policy", "display": "Inspection policy"},
    "spec": {
        "language": "cedar",
        # inline text on the wire; must land as policies/<name>.cedar on disk
        "source": 'permit(principal, action == Action::"record-inspection", resource);',
    },
}

SCENARIO_STORE = {
    "apiVersion": "ontogeny/v1",
    "kind": "Store",
    "metadata": {"name": "scenario-store", "display": "Scenario object store"},
    "spec": {"type": "sqlite", "connection": "${SCENARIO_DSN}", "access": "read-write"},
}


@pytest_asyncio.fixture()
async def client(golden_pkg_path, tmp_path):
    pkg_root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, pkg_root)
    src = tmp_path / "erp.db"
    # the package owns its source data: execute its own seed SQL (same path the
    # demo bootstrap uses), so tests always agree with the shipped example
    from ontogeny.demo.bootstrap import seed_from_package

    seed_from_package(golden_pkg_path, src, force=True)

    settings = Settings(dev_auth=True, db_dsn=f"sqlite+aiosqlite:///{tmp_path/'main.db'}",
                        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}",
                             "WMS_WEBHOOK": "https://wms.example.test/hook",
                             "SCENARIO_DSN": f"sqlite+aiosqlite:///{tmp_path/'scenario.db'}"})
    sc = ServiceContext(settings, str(pkg_root))
    await sc.initialize()
    app = build_app(sc)
    transport = httpx.ASGITransport(app=app)
    import json as J
    async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                 headers={"X-Ontogeny-Principal": J.dumps({"id": "ci-admin", "is_admin": True})}) as c:
        yield c, sc, pkg_root


def _save(c, resources, deletes=None, layout=None):
    body: dict = {"resources": resources, "deletes": deletes or []}
    if layout is not None:
        body["layout"] = layout  # absent key = "leave the stored layout alone"
    return c.post("/api/v1/admin/builder/save",
                  json=body)


class TestBuilderSave:
    async def test_partial_save_writes_yaml_and_publishes(self, client):
        c, sc, pkg = client
        work_center_yaml = (pkg / "objects" / "work-center.yaml").read_bytes()

        r = await _save(c, [SCENARIO_STORE, INSPECTION_POINT])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["published"] is True
        assert "ObjectType/inspection-point" in body["written"]
        assert body["removed"] == []

        # untouched golden YAML is byte-identical (no lossy meta rewrite)
        assert (pkg / "objects" / "work-center.yaml").read_bytes() == work_center_yaml
        # the new object landed as its own file and is live in the meta
        assert (pkg / "objects" / "inspection-point.yaml").is_file()
        meta = (await c.get("/api/v1/meta/ontology")).json()
        assert "inspection-point" in meta["objects"]

    async def test_policy_inline_cedar_materializes_as_sidecar(self, client):
        c, sc, pkg = client
        r = await _save(c, [INSPECTION_POLICY])
        assert r.status_code == 200, r.text

        written = pkg / "policies" / "inspection-policy.yaml"
        sidecar = pkg / "policies" / "inspection-policy.cedar"
        assert sidecar.is_file()
        assert sidecar.read_text(encoding="utf-8").startswith("permit(")
        doc = yaml.safe_load(written.read_text(encoding="utf-8"))
        assert doc["spec"]["source"] == "inspection-policy.cedar"  # file ref, not inline

        # live snapshot AND a cold restart both resolve the rule text
        assert "record-inspection" in sc.compiled.cedar_texts["inspection-policy"]
        from ontogeny.registry.compiled import compile_package
        from ontogeny.core import load_package
        recompiled = compile_package(load_package(pkg))
        assert "record-inspection" in recompiled.cedar_texts["inspection-policy"]

    async def test_deletes_remove_files_and_publish(self, client):
        c, sc, pkg = client
        assert (await _save(c, [INSPECTION_POINT])).status_code == 200
        assert (pkg / "objects" / "inspection-point.yaml").is_file()

        r = await _save(c, [], deletes=["ObjectType/inspection-point"])
        assert r.status_code == 200, r.text
        assert r.json()["removed"] == ["ObjectType/inspection-point"]
        assert not (pkg / "objects" / "inspection-point.yaml").is_file()
        meta = (await c.get("/api/v1/meta/ontology")).json()
        assert "inspection-point" not in meta["objects"]

        # deletes never escape the package dir
        r = await _save(c, [], deletes=["ObjectType/../../etc/passwd"])
        assert r.status_code == 200
        assert r.json()["removed"] == []

    async def test_invalid_resources_reported_not_written(self, client):
        c, sc, pkg = client
        bad = {
            "apiVersion": "ontogeny/v1",
            "kind": "ObjectType",
            "metadata": {"name": "broken-object"},
            "spec": {"primaryKey": ["id"], "properties": {}},  # min_length=1
        }
        r = await _save(c, [bad])
        assert r.status_code == 422
        body = r.json()
        assert body["code"] == "BUILDER_INVALID"
        assert any("broken-object" in e["resource"] for e in body["errors"])
        assert not (pkg / "objects" / "broken-object.yaml").exists()

    async def test_new_object_is_queryable_after_create_action(self, client):
        """The full builder loop: publish a scenario, then create + read a row."""
        c, sc, pkg = client
        task_obj = {
            "apiVersion": "ontogeny/v1",
            "kind": "ObjectType",
            "metadata": {"name": "inspection-task", "display": "Inspection task"},
            "spec": {
                "primaryKey": ["task_id"],
                "properties": {
                    "task_id": {"type": "string", "required": True},
                    "point_id": {"type": "string", "required": True},
                    "status": {"type": "enum[OPEN, DONE]", "required": True},
                },
                "backing": {
                    "store": "scenario-store",
                    "mode": "materialized",
                    "source": {"schema": "scenario", "table": "inspection_task"},
                    "mapping": {},
                    "sync": {"strategy": "snapshot"},
                },
            },
        }
        create_action = {
            "apiVersion": "ontogeny/v1",
            "kind": "Action",
            "metadata": {"name": "create-inspection-task", "display": "Create inspection task"},
            "spec": {
                "target": "inspection-task",
                "parameters": {
                    "task_id": {"type": "string", "required": True},
                    "point_id": {"type": "string", "required": True},
                },
                "rules": [],
                "effects": [{"kind": "create-object",
                             "properties": {"task_id": "parameters.task_id",
                                            "point_id": "parameters.point_id",
                                            "status": "OPEN"}}],
            },
        }
        policy = {
            "apiVersion": "ontogeny/v1",
            "kind": "PolicySet",
            "metadata": {"name": "inspection-policy"},
            "spec": {"language": "cedar",
                     "source": 'permit(principal, action == Action::"create-inspection-task", resource);'},
        }
        create_action["spec"]["policy"] = "inspection-policy"
        r = await _save(c, [SCENARIO_STORE, task_obj, create_action, policy])
        assert r.status_code == 200, r.text

        execr = await c.post("/api/v1/actions/create-inspection-task/execute",
                             json={"parameters": {"task_id": "T-1", "point_id": "P-1"}})
        assert execr.status_code == 200, execr.text
        assert execr.json()["after"]["status"] == "OPEN"

        q = await c.post("/api/v1/objects/inspection-task/query", json={})
        assert q.status_code == 200
        assert q.json()["total"] == 1


class TestBuilderResources:
    """GET /admin/builder/resources: the editors' lossless seed.

    `/meta/ontology` is a consumer view: it lists a function's capability
    *names* but not their values, a projection's graph but not its endpoint /
    include properties / indexes, and a policy's Cedar file name but not its
    text. An editor seeded from it would strip all three on the next save.
    """

    async def test_returns_every_editable_kind_with_full_specs(self, client):
        c, sc, pkg = client
        r = await c.get("/api/v1/admin/builder/resources")
        assert r.status_code == 200, r.text
        body = r.json()
        by_key = {f"{x['kind']}/{x['metadata']['name']}": x for x in body["resources"]}

        assert body["content_hash"] == sc.compiled.content_hash
        # every editable kind is represented
        assert {k.split("/")[0] for k in by_key} == {
            "ObjectType", "LinkType", "Projection", "Action", "Function", "PolicySet"}

        # a function keeps its capability VALUES, not just the capability name
        fn = by_key["Function/capacity-check"]
        assert fn["spec"]["runtime"] == "python"
        assert fn["spec"]["entry"] == "capacity.py:capacity_check"
        assert fn["spec"]["returns"]["type"] == "string"
        assert fn["spec"]["capabilities"] == [{"read-objects": ["work-center", "production-order"]}]

        # a projection keeps the endpoint, per-object property lists and indexes
        prj = by_key["Projection/production-graph"]
        assert prj["spec"]["endpoint"] == "${HUGEGRAPH_URL}"
        assert prj["spec"]["include"]["objects"]["production-order"]["properties"] == [
            "qty", "status", "priority"]
        assert prj["spec"]["indexes"] == [
            {"object": "production-order", "property": "status"},
            {"object": "operation", "property": "status"},
            {"object": "work-center", "property": "status"},
        ]

        # a policy carries its Cedar TEXT inline (the save endpoint turns it
        # back into policies/<name>.cedar)
        pol = by_key["PolicySet/production"]
        assert "permit(" in pol["spec"]["source"]

    async def test_round_trip_edit_does_not_strip_untouched_spec_fields(self, client):
        """Load → change one label → save → reload: nothing else moves."""
        c, sc, pkg = client
        before = {f"{x['kind']}/{x['metadata']['name']}": x
                  for x in (await c.get("/api/v1/admin/builder/resources")).json()["resources"]}

        edited = json.loads(json.dumps(before["Function/capacity-check"]))
        edited["metadata"]["display"] = "Capacity check (edited)"
        r = await _save(c, [edited])
        assert r.status_code == 200, r.text

        after = {f"{x['kind']}/{x['metadata']['name']}": x
                 for x in (await c.get("/api/v1/admin/builder/resources")).json()["resources"]}
        assert after["Function/capacity-check"]["metadata"]["display"] == "Capacity check (edited)"
        # the fields the editor never touched survive the round-trip
        assert after["Function/capacity-check"]["spec"] == before["Function/capacity-check"]["spec"]
        # and so does every other resource
        for key, res in before.items():
            if key == "Function/capacity-check":
                continue
            assert after[key] == res, key


class TestCanvasLayout:
    """Node positions are package state: saved as the package's layout.yaml
    sidecar (next to ontology.yaml) when the user saves, not browser state."""

    async def test_layout_roundtrips_through_save_and_resources(self, client):
        c, sc, pkg = client
        r = await _save(c, [], layout={"type:work-center": {"x": 120, "y": 80}})
        assert r.status_code == 200, r.text

        # the sidecar lives with the package, next to ontology.yaml, and the
        # editor seed answers it back
        assert (pkg / "layout.yaml").is_file()
        res = await c.get("/api/v1/admin/builder/resources")
        assert res.json()["layout"]["type:work-center"] == {"x": 120, "y": 80}

    async def test_empty_layout_removes_the_sidecar(self, client):
        c, sc, pkg = client
        await _save(c, [], layout={"type:work-center": {"x": 1, "y": 2}})
        assert (pkg / "layout.yaml").is_file()

        r = await _save(c, [], layout={})  # "reset to automatic layout"
        assert r.status_code == 200, r.text
        assert not (pkg / "layout.yaml").exists()
        res = await c.get("/api/v1/admin/builder/resources")
        assert res.json()["layout"] == {}

    async def test_save_without_layout_key_keeps_stored_positions(self, client):
        c, sc, pkg = client
        await _save(c, [], layout={"type:work-center": {"x": 1, "y": 2}})
        await _save(c, [INSPECTION_POINT])  # a plain resource save: no layout key

        res = await c.get("/api/v1/admin/builder/resources")
        assert res.json()["layout"]["type:work-center"] == {"x": 1, "y": 2}

    async def test_malformed_positions_are_dropped_not_fatal(self, client):
        c, sc, pkg = client
        r = await _save(c, [], layout={"a": {"x": "ghost", "y": 2}, "b": {"x": 3, "y": 4}})
        assert r.status_code == 200, r.text
        res = await c.get("/api/v1/admin/builder/resources")
        assert list(res.json()["layout"]) == ["b"]
