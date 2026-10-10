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
"""Content contract for the product-manufacturing domain package.

The package is the importable showcase domain: this module pins the promises
that "make it a complete case" --

* the package validates cleanly;
* after seeding its source SQL and syncing, EVERY object type has rows;
* EVERY declared function runs successfully against that data;
* EVERY action dry-runs as allowed for its role, and a real create -> release
  -> complete -> inspect chain executes end to end.

If any of these break (a renamed seed column, a capability that no longer
covers a query, a policy that stopped permitting), the import showcase would
be shipping a broken domain -- which is exactly what this catches.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import httpx
import pytest_asyncio

from ontogeny.api import build_app
from ontogeny.config import Settings
from ontogeny.service import ServiceContext

REPO = Path(__file__).resolve().parent.parent
DOMAIN = REPO / "domains" / "product-manufacturing"

PLANNER = {"id": "u-planner", "Role": ["planner"]}
OPERATOR = {"id": "u-op", "Role": ["operator"]}
QUALITY = {"id": "u-qa", "Role": ["quality"]}


def _hdr(p):
    return {"X-Ontogeny-Principal": json.dumps(p)}


@pytest_asyncio.fixture()
async def pm(tmp_path):
    """A live ServiceContext + ASGI client over the product-manufacturing
    domain, with its seed SQL materialized into a private SQLite source."""
    pkg_root = tmp_path / "pkg"
    shutil.copytree(DOMAIN, pkg_root)
    src = tmp_path / "erp.db"
    con = sqlite3.connect(str(src))
    con.executescript((DOMAIN / "seed" / "01_source.sql").read_text(encoding="utf-8"))
    con.commit()
    con.close()

    settings = Settings(dev_auth=True, db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'ontogeny.db'}",
                        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}"})
    sc = ServiceContext(settings, str(pkg_root))
    await sc.initialize()
    app = build_app(sc)
    transport = httpx.ASGITransport(app=app)
    import json as J
    async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                 headers={"X-Ontogeny-Principal": J.dumps({"id": "ci-admin", "is_admin": True})}) as c:
        # bring the seeded source rows into the ontology's own tables
        for obj_type in sc.compiled.objects:
            r = await c.post(f"/api/v1/admin/sync/{obj_type}")
            assert r.status_code == 200, r.text
        yield c, sc


class TestPackageContract:
    def test_the_package_validates_cleanly(self):
        from ontogeny.core import load_package
        from ontogeny.core.validator import validate

        report = validate(load_package(str(DOMAIN)))
        assert report.ok, [i.message for i in report.issues]

    async def test_every_object_type_has_data(self, pm):
        c, sc = pm
        for obj_type in sc.compiled.objects:
            r = await c.post(f"/api/v1/objects/{obj_type}/query",
                             json={"filter": None}, headers=_hdr(PLANNER))
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["total"] > 0, f"object type {obj_type} has no seeded rows"

    async def test_every_function_runs_successfully(self, pm):
        """Each function is invoked with a real seeded id: the showcase must
        never ship a declared function that cannot run."""
        c, _sc = pm
        cases = {
            "material-availability": {"product_id": "P-100", "qty": 20},
            "capacity-check": {"work_center_id": "WC-01", "qty": 40},
            "order-yield": {"order_id": "PO-1003"},
        }
        assert set(cases) == set(_sc.compiled.functions), \
            "a function was added to the package without a contract case"
        for name, params in cases.items():
            r = await c.post(f"/api/v1/functions/{name}/invoke",
                             json={"parameters": params}, headers=_hdr(PLANNER))
            assert r.status_code == 200, r.text
            assert r.json()["value"], f"function {name} returned nothing"

    async def test_function_answers_make_sense(self, pm):
        c, _sc = pm
        # M-104 stock is 9, P-100 needs 4 per unit with 1% scrap: 20 units
        # require ceil(4*20*1.01)=81 -> a shortage must be reported
        r = await c.post("/api/v1/functions/material-availability/invoke",
                         json={"parameters": {"product_id": "P-100", "qty": 20}},
                         headers=_hdr(PLANNER))
        value = r.json()["value"]
        assert value["ready"] is False
        shortage = {s["material_id"]: s for s in value["shortage"]}
        assert shortage["M-104"]["gap"] == 81 - 9

        # PO-1003 is fully inspected (100/2 defects) and fully routed
        r = await c.post("/api/v1/functions/order-yield/invoke",
                         json={"parameters": {"order_id": "PO-1003"}},
                         headers=_hdr(PLANNER))
        value = r.json()["value"]
        assert value["routing_complete"] is True
        assert value["pass_rate"] == 0.98

    async def test_every_action_dry_runs_allowed_for_its_role(self, pm):
        """One seeded target per action, dry-run (validate) with the role its
        policy permits: every action in the package must be usable."""
        c, _sc = pm
        cases = {
            "introduce-product": (PLANNER, {"name": "Hydraulic Power Unit"}),
            "register-work-center": (PLANNER, {"name": "Paint Booth",
                                               "capacity_per_shift": 120}),
            "add-bom-line": (PLANNER, {"product_id": "P-300", "material_id": "M-102",
                                       "qty_per_unit": 0.5}),
            "receive-material": (PLANNER, {"counted_qty": 60}),
            "create-production-order": (PLANNER, {"product_id": "P-200", "qty": 5}),
            "release-production-order": (PLANNER, {}),
            "complete-operation": (OPERATOR, {}),
            "record-inspection": (QUALITY, {"order_id": "PO-1002", "inspected_qty": 5,
                                            "defect_qty": 0, "result": "PASS"}),
            "assign-operation": (PLANNER, {"work_center_id": "WC-02"}),
            "cancel-production-order": (PLANNER, {"reason": "demand withdrawn"}),
            "retract-inspection": (QUALITY, {"reason": "recorded in error"}),
        }
        assert set(cases) == set(_sc.compiled.actions), \
            "an action was added to the package without a contract case"
        target_ids = {
            "receive-material": ("material", "M-101"),
            "release-production-order": ("production-order", "PO-1002"),
            "complete-operation": ("operation", "OP-2001"),
            "assign-operation": ("operation", "OP-2002"),  # QUEUED: reassignable
            "cancel-production-order": ("production-order", "PO-1003"),
            "retract-inspection": ("quality-inspection", "QI-3003"),
        }
        for name, (principal, params) in cases.items():
            body: dict = {"parameters": params}
            if name in target_ids:
                body["target_id"] = target_ids[name][1]
            r = await c.post(f"/api/v1/actions/{name}/validate",
                             json=body, headers=_hdr(principal))
            assert r.status_code == 200, f"{name}: {r.text}"
            assert r.json()["policy"]["allow"] is True, f"{name} denied: {r.json()}"

    async def test_a_real_chain_executes_end_to_end(self, pm):
        """create -> release -> complete -> inspect: the four action shapes
        (create-object, conditional modify, modify, linked create) really run."""
        c, _sc = pm

        r = await c.post("/api/v1/actions/create-production-order/execute",
                         json={"parameters": {"product_id": "P-200", "qty": 12,
                                              "priority": "HIGH"}},
                         headers=_hdr(PLANNER))
        assert r.status_code == 200, r.text
        order_id = r.json()["object_id"]
        assert r.json()["after"]["status"] == "PLANNED"

        r = await c.post("/api/v1/actions/release-production-order/execute",
                         json={"parameters": {}, "target_id": order_id},
                         headers=_hdr(PLANNER))
        assert r.status_code == 200 and r.json()["after"]["status"] == "RELEASED"

        r = await c.post("/api/v1/actions/complete-operation/execute",
                         json={"parameters": {}, "target_id": "OP-2101"},
                         headers=_hdr(OPERATOR))
        assert r.status_code == 200 and r.json()["after"]["status"] == "COMPLETED"

        r = await c.post("/api/v1/actions/record-inspection/execute",
                         json={"parameters": {"order_id": order_id, "inspected_qty": 12,
                                              "defect_qty": 1, "result": "PASS",
                                              "inspector": "qa-eng-01"}},
                         headers=_hdr(QUALITY))
        assert r.status_code == 200, r.text
        assert r.json()["after"]["defect_qty"] == 1

    async def test_rules_actually_reject(self, pm):
        """A broken rule would make the showcase permissive: prove the guard."""
        c, _sc = pm
        # validate is a dry-run: a failing rule is REPORTED, not raised
        r = await c.post("/api/v1/actions/create-production-order/validate",
                         json={"parameters": {"product_id": "P-200", "qty": 0}},
                         headers=_hdr(PLANNER))
        assert r.status_code == 200
        assert any(not rule["ok"] for rule in r.json()["rules"])
        r = await c.post("/api/v1/actions/release-production-order/validate",
                         json={"parameters": {}, "target_id": "PO-1001"},  # RELEASED
                         headers=_hdr(PLANNER))
        assert r.status_code == 200
        assert any(not rule["ok"] for rule in r.json()["rules"])
        # ... and execute refuses the same input outright
        r = await c.post("/api/v1/actions/create-production-order/execute",
                         json={"parameters": {"product_id": "P-200", "qty": 0}},
                         headers=_hdr(PLANNER))
        assert r.status_code == 422

    async def test_hardening_rules_reject(self, pm):
        """Review-hardened rules (PR #380): cancelled operations cannot be
        completed, only queued operations can be reassigned, defect counts
        cannot go negative and scrap_rate stays within [0, 1]."""
        c, _sc = pm
        # scrap_rate bounds: 1.5 is refused, an omitted rate (null -> 0) passes
        r = await c.post("/api/v1/actions/add-bom-line/validate",
                         json={"parameters": {"product_id": "P-300", "material_id": "M-102",
                                              "qty_per_unit": 0.5, "scrap_rate": 1.5}},
                         headers=_hdr(PLANNER))
        assert r.status_code == 200
        assert any(not rule["ok"] for rule in r.json()["rules"])
        r = await c.post("/api/v1/actions/add-bom-line/validate",
                         json={"parameters": {"product_id": "P-300", "material_id": "M-102",
                                              "qty_per_unit": 0.5}},
                         headers=_hdr(PLANNER))
        assert r.status_code == 200
        assert all(rule["ok"] for rule in r.json()["rules"])
        # negative defect counts are refused outright
        r = await c.post("/api/v1/actions/record-inspection/execute",
                         json={"parameters": {"order_id": "PO-1001", "inspected_qty": 5,
                                              "defect_qty": -1, "result": "PASS"}},
                         headers=_hdr(QUALITY))
        assert r.status_code == 422
        # only queued operations can be reassigned: OP-2201 is COMPLETED
        r = await c.post("/api/v1/actions/assign-operation/validate",
                         json={"parameters": {"work_center_id": "WC-01"},
                               "target_id": "OP-2201"},
                         headers=_hdr(PLANNER))
        assert r.status_code == 200
        assert any(not rule["ok"] for rule in r.json()["rules"])
        # cancelling an order cancels its routing with it: those operations
        # can no longer be completed
        r = await c.post("/api/v1/actions/cancel-production-order/execute",
                         json={"parameters": {"reason": "review-fix test"},
                               "target_id": "PO-1001"},
                         headers=_hdr(PLANNER))
        assert r.status_code == 200, r.text
        r = await c.post("/api/v1/actions/complete-operation/validate",
                         json={"parameters": {}, "target_id": "OP-2001"},  # RUNNING -> cancelled
                         headers=_hdr(PLANNER))
        assert r.status_code == 200
        assert any(not rule["ok"] for rule in r.json()["rules"])


def test_demo_actions_cover_all_seven_effect_kinds():
    """The demo is the product tour: between its actions it must exercise every
    effect kind the runtime implements, so no effect path is only ever run by
    unit tests with synthetic packages."""
    from ontogeny.core import load_package

    pkg = load_package("domains/product-manufacturing")
    kinds = {eff.kind for action in pkg.actions() for eff in action.spec.effects}
    assert kinds >= {"modify-target", "modify-linked", "create-object", "archive-object",
                     "set-link", "webhook", "emit-event"}
