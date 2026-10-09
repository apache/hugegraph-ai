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
"""Domain switching: several ontology packages, one active at a time.

The registry holds exactly one domain's rows; activating another retires the
previous rows (soft delete) so ``load_latest`` rebuilds only the active domain
— including across a restart. The HTTP surface is the console's domain picker.
"""
from __future__ import annotations

import pytest

from ontogeny.service import ServiceContext

pytestmark = pytest.mark.anyio


async def test_list_domains_active_first(client):
    c, sc = client
    r = await c.get("/api/v1/admin/domains")
    assert r.status_code == 200
    body = r.json()
    assert body["active"] == "product-manufacturing"
    assert len(body["domains"]) == 1
    dom = body["domains"][0]
    assert dom["name"] == "product-manufacturing"
    assert dom["active"] is True
    assert dom["objects"] > 0  # the golden package ships object types
    assert (sc.domains_root()) == sc.domains_root()  # deterministic


async def test_create_activate_and_switch_back(client):
    c, sc = client
    # create an empty domain and land in it
    r = await c.post("/api/v1/admin/domains", json={
        "name": "logistics", "display": "物流域", "description": "test domain",
    })
    assert r.status_code == 200
    assert r.json()["active"] is True

    # the snapshot is now the new domain: no object types yet
    r = await c.get("/api/v1/meta/ontology")
    body = r.json()
    assert body["package"] == "logistics"
    assert body["objects"] == {}

    # listing shows both, active first
    r = await c.get("/api/v1/admin/domains")
    doms = r.json()["domains"]
    assert [d["name"] for d in doms] == ["logistics", "product-manufacturing"]
    assert doms[0]["active"] is True and doms[1]["active"] is False

    # switch back: the product-manufacturing snapshot (types AND published rows) returns
    r = await c.post("/api/v1/admin/domains/activate", json={"name": "product-manufacturing"})
    assert r.status_code == 200
    r = await c.get("/api/v1/meta/ontology")
    assert "production-order" in r.json()["objects"]


async def test_switch_survives_restart(client):
    c, sc = client
    r = await c.post("/api/v1/admin/domains", json={"name": "logistics"})
    assert r.status_code == 200

    # a fresh ServiceContext over the same DB boots into the activated domain,
    # and its package root re-derives to the domain directory on disk
    sc2 = ServiceContext(sc.settings, sc.package_root)
    await sc2.initialize()
    from pathlib import Path as _P

    assert sc2.compiled is not None
    assert sc2.compiled.package_name == "logistics"
    assert (_P(sc2.compiled.package_root) / "ontology.yaml").is_file()


async def test_create_rejects_bad_and_duplicate_names(client):
    c, _ = client
    r = await c.post("/api/v1/admin/domains", json={"name": "Bad Name"})
    assert r.status_code == 400 and r.json()["code"] == "DOMAIN_INVALID"

    r = await c.post("/api/v1/admin/domains", json={"name": "ok-domain"})
    assert r.status_code == 200
    r = await c.post("/api/v1/admin/domains", json={"name": "ok-domain"})
    assert r.status_code == 400 and r.json()["code"] == "DOMAIN_INVALID"


async def test_activate_unknown_domain(client):
    c, _ = client
    r = await c.post("/api/v1/admin/domains/activate", json={"name": "nope"})
    assert r.status_code == 404


async def test_list_domains_reports_a_health_check(client):
    """Every listed domain carries a live check: load + validate from disk."""
    c, sc = client
    r = await c.get("/api/v1/admin/domains")
    dom = r.json()["domains"][0]
    assert dom["check"] == {"ok": True, "errors": []}


async def test_domain_check_flags_a_broken_package(client):
    """A half-written domain directory must not break the switcher: it is
    listed with check.ok=false and the first errors, activation would refuse."""
    c, sc = client
    broken = sc.domains_root() / "broken"
    (broken / "objects").mkdir(parents=True)
    (broken / "ontology.yaml").write_text(
        "apiVersion: ontogeny/v1\nkind: Ontology\nmetadata:\n  name: broken\nspec: {}\n",
        encoding="utf-8")
    (broken / "objects" / "bad.yaml").write_text("::: not yaml [", encoding="utf-8")

    r = await c.get("/api/v1/admin/domains")
    doms = {d["name"]: d for d in r.json()["domains"]}
    assert doms["broken"]["check"]["ok"] is False
    assert doms["broken"]["check"]["errors"]
    # and the healthy one still passes
    assert doms["product-manufacturing"]["check"]["ok"] is True
