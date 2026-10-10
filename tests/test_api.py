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
"""HTTP shell end-to-end: publish -> sync -> query -> act -> audit -> evolve,
over a real (file-backed sqlite) ServiceContext through ASGI transport."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

# plant-north planner: the role the production policies grant planning actions
PLANNER = {"id": "u-planner", "Role": ["planner"], "site": "plant-north"}

OBJECT_TYPES = ("product", "material", "bom", "work-center",
                "production-order", "operation", "quality-inspection")


def _hdr(p):
    return {"X-Ontogeny-Principal": json.dumps(p)}


class TestEndToEnd:
    async def test_meta(self, client):
        c, _ = client
        r = await c.get("/api/v1/meta/ontology")
        assert r.status_code == 200
        assert "production-order" in r.json()["objects"]

    async def test_sync_then_query_and_masking(self, client):
        c, sc = client
        for t in OBJECT_TYPES:
            r = await c.post(f"/api/v1/admin/sync/{t}")
            assert r.status_code == 200

        r = await c.post("/api/v1/objects/production-order/query",
                         json={"filter": {"status": "RELEASED"}}, headers=_hdr(PLANNER))
        body = r.json()
        assert body["total"] == 2  # PO-1001 + PO-1003 both RELEASED after sync
        assert {o["order_id"] for o in body["objects"]} == {"PO-1001", "PO-1003"}

        # material.unit_cost carries the `internal` marking: masked for a
        # principal without the claim, visible for one that holds it
        r = await c.get("/api/v1/objects/material/M-101", headers=_hdr(PLANNER))
        assert r.json()["unit_cost"] == "__masked__"
        r = await c.get("/api/v1/objects/material/M-101",
                        headers=_hdr({**PLANNER, "markings": ["internal"]}))
        assert r.json()["unit_cost"] == 210.0  # decimal coerced on sync

    async def test_action_execute_full_cycle(self, client):
        c, sc = client
        await c.post("/api/v1/admin/sync/production-order")

        r = await c.post("/api/v1/actions/release-production-order/validate",
                         json={"parameters": {}, "target_id": "PO-1002"},
                         headers=_hdr(PLANNER))
        assert r.status_code == 200 and r.json()["policy"]["allow"]

        r = await c.post("/api/v1/actions/release-production-order/execute",
                         json={"parameters": {}, "target_id": "PO-1002",
                               "idempotency_key": "api-1"},
                         headers=_hdr(PLANNER))
        assert r.status_code == 200
        rev_id = r.json()["revision_id"]
        assert r.json()["after"]["status"] == "RELEASED"

        # idempotent replay through the API
        r2 = await c.post("/api/v1/actions/release-production-order/execute",
                          json={"parameters": {}, "target_id": "PO-1002",
                                "idempotency_key": "api-1"},
                          headers=_hdr(PLANNER))
        assert r2.json()["revision_id"] == rev_id

        # rule rejection surfaces as structured 422 (already RELEASED)
        r3 = await c.post("/api/v1/actions/release-production-order/execute",
                          json={"parameters": {}, "target_id": "PO-1002"},
                          headers=_hdr(PLANNER))
        assert r3.status_code == 422 and r3.json()["code"] == "RULE_REJECTED"

        # policy denial as 403 (fresh PLANNED target so rules pass first)
        created = await c.post("/api/v1/actions/create-production-order/execute",
                               json={"parameters": {"product_id": "P-100", "qty": 5}},
                               headers=_hdr(PLANNER))
        assert created.status_code == 200, created.text
        new_order = created.json()["object_id"]
        r4 = await c.post("/api/v1/actions/release-production-order/execute",
                          json={"parameters": {}, "target_id": new_order},
                          headers=_hdr({"id": "visitor"}))
        assert r4.status_code == 403

        # audit trail
        r5 = await c.get("/api/v1/audit/revisions", params={"object_id": "PO-1002"})
        outcomes = [x["outcome"] for x in r5.json()["revisions"]]
        assert "executed" in outcomes and "rejected_rule" in outcomes

    async def test_links_and_traverse(self, client):
        c, _ = client
        for t in OBJECT_TYPES:
            await c.post(f"/api/v1/admin/sync/{t}")
        # WC-01 runs OP-2001, OP-2002 (order PO-1001) and OP-2301 (order PO-1004)
        r = await c.get("/api/v1/objects/work-center/WC-01/links/operation-work-center",
                        headers=_hdr(PLANNER))
        assert r.status_code == 200
        assert {o["operation_id"] for o in r.json()} == {"OP-2001", "OP-2002", "OP-2301"}

        r = await c.post("/api/v1/graph/traverse", json={
            "start_type": "work-center", "start_ids": ["WC-01"],
            "path": [{"link": "operation-work-center", "direction": "out"}],
        }, headers=_hdr(PLANNER))
        assert r.status_code == 200
        assert r.json()["steps"][-1]["type"] == "operation"

    async def test_outbox_dispatch_and_history(self, client):
        c, _ = client
        await c.post("/api/v1/admin/sync/production-order")
        await c.post("/api/v1/actions/release-production-order/execute",
                     json={"parameters": {}, "target_id": "PO-1002"}, headers=_hdr(PLANNER))
        r = await c.post("/api/v1/admin/outbox/dispatch")
        assert r.status_code == 200

        r = await c.get("/api/v1/objects/production-order/PO-1002/history")
        versions = r.json()["versions"]
        assert len(versions) == 2 and versions[0]["_valid_to"] is not None

    async def test_evolve_loop_via_api(self, client):
        c, sc = client
        # the eval suite queries orders, operations and work centres: all of
        # them must be materialized for a proposal to eval green
        for t in OBJECT_TYPES:
            await c.post(f"/api/v1/admin/sync/{t}")
        # generate telemetry: repeated unmapped filter usage
        for _ in range(6):
            await c.post("/api/v1/objects/production-order/query",
                         json={"filter": {"field": "shift", "op": "eq", "value": "DAY"}},
                         headers=_hdr(PLANNER))
        r = await c.post("/api/v1/evolve/aggregate")
        assert any(s["kind"] == "unmapped_filter_field" for s in r.json()["created"])

        r = await c.post("/api/v1/evolve/diagnose")
        proposals = r.json()["proposals"]
        assert proposals and proposals[0]["gap_kind"] == "add-optional-property"
        pid = proposals[0]["id"]

        r = await c.post(f"/api/v1/evolve/proposals/{pid}/eval")
        assert r.status_code == 200 and r.json()["passed"] is True

        r = await c.post(f"/api/v1/evolve/proposals/{pid}/promote")
        assert r.status_code == 200 and r.json()["status"] == "promoted"

        # the mutation is live in the registry (M5 acceptance, API flavor)
        from ontogeny.core import load_package

        mutated = load_package(sc.package_root)
        assert "shift" in mutated.find("ObjectType", "production-order").spec.properties
        r = await c.get("/api/v1/meta/ontology")
        assert "shift" in r.json()["objects"]["production-order"]["properties"]

    async def test_evolve_loop_is_convergent(self, client):
        """The loop's writes are idempotent: re-running aggregate re-detects
        nothing, and re-running diagnose does not re-file a live proposal.
        Together these are what make the evolution console safe to click
        repeatedly (and what the one-click demo rides on)."""
        c, _ = client
        for t in OBJECT_TYPES:
            await c.post(f"/api/v1/admin/sync/{t}")
        for _ in range(6):
            await c.post("/api/v1/objects/production-order/query",
                         json={"filter": {"field": "shift", "op": "eq", "value": "DAY"}},
                         headers=_hdr(PLANNER))
        r1 = await c.post("/api/v1/evolve/aggregate")
        assert any(s["kind"] == "unmapped_filter_field" for s in r1.json()["created"])
        r2 = await c.post("/api/v1/evolve/aggregate")
        assert r2.json()["created"] == []

        p1 = (await c.post("/api/v1/evolve/diagnose")).json()["proposals"]
        assert p1 and p1[0]["diff"][0]["prop"] == "shift"
        p2 = (await c.post("/api/v1/evolve/diagnose")).json()["proposals"]
        assert p2 == []  # the live proposal already covers this signal

        # a rejected proposal releases its signal for a fresh attempt
        pid = p1[0]["id"]
        await c.post(f"/api/v1/evolve/proposals/{pid}/eval")
        await c.post(f"/api/v1/evolve/proposals/{pid}/promote")  # T0: promoted, still live
        p3 = (await c.post("/api/v1/evolve/diagnose")).json()["proposals"]
        assert p3 == []

    async def test_rejection_outcomes_reach_telemetry_distinctly(self, client):
        """The rule-reject detector counts `rejected_rule` specifically; the API
        used to collapse rule rejections and policy denials into "rejected",
        starving it. The two classes are different findings."""
        c, sc = client
        await c.post("/api/v1/admin/sync/production-order")
        await c.post("/api/v1/actions/release-production-order/execute",
                     json={"parameters": {}, "target_id": "PO-1002"},
                     headers=_hdr(PLANNER))
        await c.post("/api/v1/actions/release-production-order/execute",
                     json={"parameters": {}, "target_id": "PO-1002"},
                     headers=_hdr(PLANNER))  # rule rejection (already RELEASED)
        created = await c.post("/api/v1/actions/create-production-order/execute",
                               json={"parameters": {"product_id": "P-100", "qty": 5}},
                               headers=_hdr(PLANNER))
        await c.post("/api/v1/actions/release-production-order/execute",
                     json={"parameters": {}, "target_id": created.json()["object_id"]},
                     headers=_hdr({"id": "visitor"}))  # policy denial
        from sqlalchemy import select

        from ontogeny.telemetry.service import TelemetryActionRow

        async with sc.sessionmaker() as s:
            rows = (await s.execute(select(TelemetryActionRow))).scalars().all()
        outcomes = {r.outcome for r in rows}
        assert "rejected_rule" in outcomes
        assert "denied_policy" in outcomes
        assert "rejected" not in outcomes

    async def test_evolve_diagnose_reports_who_decided(self, client):
        """With an LLM wired, the loop's proposals say so: origin=llm, the
        model-chosen type and business metadata ride along, and decided_by
        exposes the round's provenance. The deterministic fallback is the same
        endpoint with no model attached."""
        import json as _json

        c, sc = client
        for t in OBJECT_TYPES:
            await c.post(f"/api/v1/admin/sync/{t}")
        for _ in range(6):
            await c.post("/api/v1/objects/production-order/query",
                         json={"filter": {"field": "shift", "op": "eq", "value": "DAY"}},
                         headers=_hdr(PLANNER))
        await c.post("/api/v1/evolve/aggregate")

        class _FakeLLM:
            model = "fake"

            async def chat(self, messages, **kw):
                return {"content": _json.dumps({
                    "act": True,
                    "analysis": "shift is the shop-floor shift enum",
                    "mutations": [{"mutation": "add-optional-property", "object": "production-order",
                                   "prop": "shift", "type": "enum[DAY, NIGHT]",
                                   "display": "Shift", "description": "Production shift this order belongs to"}],
                    "rationale": "filter field shift recurs; semantically a shift enum"})}

            async def health(self):
                return {"ok": True}

            def scoped(self, model):
                return self

        from ontogeny.evolve.proposer import DecidingProposer

        sc.proposer = DecidingProposer(_FakeLLM())
        r = await c.post("/api/v1/evolve/diagnose")
        body = r.json()
        assert body["decided_by"]["llm_decided"] >= 1
        p0 = body["proposals"][0]
        assert p0["origin"] == "llm"
        m = p0["diff"][0]
        assert m["type"] == "enum[DAY, NIGHT]" and m["display"] == "Shift"

        # the model's metadata promotes all the way into the package
        pid = p0["id"]
        await c.post(f"/api/v1/evolve/proposals/{pid}/eval")
        await c.post(f"/api/v1/evolve/proposals/{pid}/promote")
        from ontogeny.core import load_package

        pdef = load_package(sc.package_root).find("ObjectType", "production-order").spec.properties["shift"]
        assert pdef.display == "Shift" and pdef.description == "Production shift this order belongs to"
        assert pdef.type == "enum[DAY, NIGHT]"

    async def test_mount_csv_and_sync(self, client):
        """Data mounting end-to-end: CSV content -> store resource + object
        backing on disk -> publish -> sync pulls the rows through the normal
        engine (masking/quarantine apply)."""
        c, sc = client
        # the export carries only SOURCE-owned facts (no status/released_at:
        # those are ontology-owned — release-production-order writes them;
        # mounting a CSV that claims them makes the validator correctly refuse
        # the binding)
        csv_text = (
            "order_id,product_id,qty,priority,created_at\n"
            "PO-M1,P-100,5,HIGH,2026-09-18T08:00:00+00:00\n"
            "PO-M2,P-200,10,LOW,2026-09-18T09:00:00+00:00\n"
            "PO-M3,P-300,8,NORMAL,2026-09-18T10:00:00+00:00\n"
            "PO-BAD,P-100,3,URGENT,2026-09-18T11:00:00+00:00\n"  # off-enum value -> quarantined
        )
        # the frontend preview auto-maps same-name columns and sends the FULL
        # mapping (empty mapping would mean "everything source-owned")
        full_mapping = {k: k for k in
                        ["order_id", "product_id", "qty", "priority", "created_at"]}
        r = await c.post("/api/v1/admin/builder/mount", json={
            "object": "production-order",
            "store": "csv-production-orders",
            "source": {"kind": "csv", "filename": "production_orders.csv", "content": csv_text},
            "mapping": full_mapping,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["published"] is True and body["store"] == "csv-production-orders"
        assert body["sync"]["inserted"] == 3
        assert body["sync"]["quarantined"] == 1
        assert any(q["code"] and q["pk"] == "PO-BAD" for q in body["quarantine"])

        # the rows are queryable through the normal door
        r = await c.post("/api/v1/objects/production-order/query",
                         json={"filter": {"field": "order_id", "op": "eq", "value": "PO-M1"}},
                         headers=_hdr(PLANNER))
        assert r.status_code == 200 and r.json()["total"] == 1

        # the store resource and the binding are on disk (builder-visible)
        pkg = Path(sc.package_root)
        assert (pkg / "stores" / "csv-production-orders.yaml").is_file()
        import yaml as _yaml

        obj_doc = _yaml.safe_load((pkg / "objects" / "production-order.yaml").read_text())
        assert obj_doc["spec"]["backing"]["store"] == "csv-production-orders"
        assert obj_doc["spec"]["backing"]["source"]["table"] == "production_orders"

        # remount is idempotent (snapshot upsert -> noop)
        r2 = await c.post("/api/v1/admin/builder/mount", json={
            "object": "production-order",
            "store": "csv-production-orders",
            "source": {"kind": "csv", "filename": "production_orders.csv", "content": csv_text},
            "mapping": full_mapping,
        })
        assert r2.json()["sync"]["inserted"] == 0

        # a mount WITHOUT a mapping derives the same-name mapping from the CSV
        # header (never empty mapping = everything source-owned)
        r3 = await c.post("/api/v1/admin/builder/mount", json={
            "object": "production-order",
            "store": "csv-production-orders",
            "source": {"kind": "csv", "filename": "production_orders.csv", "content": csv_text},
        })
        assert r3.status_code == 200
        assert r3.json()["mapping"]["order_id"] == "order_id"

    async def test_mount_sqlite_source(self, client, tmp_path):
        c, sc = client

        src = tmp_path / "extra.db"
        con = sqlite3.connect(str(src))
        con.execute("CREATE TABLE materials_extra (material_id TEXT PRIMARY KEY, name TEXT, "
                    "unit_cost TEXT, stock_qty TEXT)")
        con.execute("INSERT INTO materials_extra VALUES ('MX-1','Gasket','3.5','80')")
        con.commit()
        con.close()

        r = await c.post("/api/v1/admin/builder/mount", json={
            "object": "material",
            "source": {"kind": "sqlite", "dsn": f"sqlite+aiosqlite:///{src}", "table": "materials_extra"},
            "mapping": {"material_id": "material_id", "name": "name",
                        "unit_cost": "unit_cost", "stock_qty": "stock_qty"},
        })
        assert r.status_code == 200, r.text
        assert r.json()["sync"]["inserted"] == 1

    async def test_mount_rejects_unknown_object_and_bad_source(self, client):
        c, _ = client
        r = await c.post("/api/v1/admin/builder/mount", json={
            "object": "nope", "source": {"kind": "csv", "content": "a\n1"}})
        assert r.status_code == 404
        r2 = await c.post("/api/v1/admin/builder/mount", json={
            "object": "production-order", "source": {"kind": "csv"}})  # no content
        assert r2.status_code == 422
        r3 = await c.post("/api/v1/admin/builder/mount", json={
            "object": "production-order", "source": {"kind": "sqlite"}})  # no dsn/table
        assert r3.status_code == 422

    async def test_mount_refuses_source_missing_required_properties(self, client):
        """A CSV lacking a required property would hit NOT NULL mid-insert (a
        raw 500); the mount must refuse with the actual list instead."""
        c, _ = client
        r = await c.post("/api/v1/admin/builder/mount", json={
            "object": "production-order",  # product_id/qty are required too
            "source": {"kind": "csv", "filename": "bad.csv",
                       "content": "order_id\nPO-X"},
        })
        assert r.status_code == 422
        assert "qty" in r.json()["message"]

    async def test_meta_exposes_cedar_role_vocabulary(self, client):
        c, _ = client
        r = (await c.get("/api/v1/meta/ontology")).json()
        assert "planner" in r["roles"]

    async def test_create_agent_plugin_via_builder(self, client):
        """The plugins tab's "new plugin" flow: AgentPlugin resource through the
        builder door -> on disk -> published -> listed with its effective
        toolset. The role vocabulary comes from meta.roles."""
        c, sc = client
        meta = (await c.get("/api/v1/meta/ontology")).json()
        assert meta["roles"], "demo package must reference at least one role"

        plugin = {
            "apiVersion": "ontogeny/v1", "kind": "AgentPlugin",
            "metadata": {"name": "qc-copilot", "display": "Quality copilot",
                         "description": "read-only queries"},
            "spec": {
                "engine": {"kind": "builtin-llm"},
                "principal": {"id": "agent:qc-copilot", "Role": meta["roles"][:1],
                              "site": "plant-north"},
                "tools": {"allow": ["describe_ontology", "search_production_order"]},
                "approval": {"writes": "never"},
                "budget": {"steps": 20, "wall_ms": 60000, "writes_per_session": 0},
            },
        }
        r = await c.post("/api/v1/admin/builder/save", json={"resources": [plugin]})
        assert r.status_code == 200, r.text
        assert "AgentPlugin/qc-copilot" in r.json()["written"]

        # listed at runtime with its narrowed toolset
        r = await c.get("/api/v1/agent/plugins")
        by_name = {p["name"]: p for p in r.json()["plugins"]}
        assert "qc-copilot" in by_name
        assert "describe_ontology" in by_name["qc-copilot"]["tools"]
        assert "search_production_order" in by_name["qc-copilot"]["tools"]

    async def test_error_shape(self, client):
        c, _ = client
        r = await c.get("/api/v1/objects/nope/x")
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


async def test_meta_storage_names_the_physical_target(client):
    """/meta/storage spells out where materialized data lives: the platform's
    own db (the console renders this next to every "materialized" label)."""
    c, sc = client
    r = await c.get("/api/v1/meta/storage")
    assert r.status_code == 200
    body = r.json()
    assert body["target"]["kind"] == "sqlite"
    assert body["target"]["target"].endswith("main.db")
    po = body["objects"]["production-order"]
    assert po["table"] == "ontogeny_obj_production_order"
    assert po["store"] == "mes" and po["mode"] == "materialized"
    assert po["source_table"] == "production_orders"
    assert po["sync"] == "watermark" and po["sync_watermark"] == "updated_at"
    # rows is a live count (0 right after ensure_tables, null if never synced)
    assert po.get("rows") in (None, 0)
