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

"""HTTP shell end-to-end: publish -> sync -> query -> act -> audit -> evolve,
over a real (file-backed sqlite) ServiceContext through ASGI transport."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

# hq product engineer: the role the production policies grant lifecycle planning actions
PRODUCT = {"id": "u-product", "Role": ["product"], "site": "hq"}

# every SQL-backed object type of the golden package; fmea-note is
# extract-backed (document plane) and never pulls source rows
OBJECT_TYPES = (
    "requirement",
    "design-module",
    "tapeout-version",
    "equipment",
    "wafer-lot",
    "process-step",
    "wafer-test",
    "customer",
    "field-failure",
)


def _hdr(p):
    return {"X-Ontogeny-Principal": json.dumps(p)}


class TestEndToEnd:
    async def test_meta(self, client):
        c, _ = client
        r = await c.get("/api/v1/meta/ontology")
        assert r.status_code == 200
        assert "wafer-lot" in r.json()["objects"]

    async def test_sync_then_query_and_masking(self, client):
        c, _sc = client
        for t in OBJECT_TYPES:
            r = await c.post(f"/api/v1/admin/sync/{t}")
            assert r.status_code == 200

        r = await c.post(
            "/api/v1/objects/wafer-lot/query", json={"filter": {"status": "RUNNING"}}, headers=_hdr(PRODUCT)
        )
        body = r.json()
        assert body["total"] == 2  # LOT-2419 + LOT-2501 both RUNNING after sync
        assert {o["lot_id"] for o in body["objects"]} == {"LOT-2419", "LOT-2501"}

        # tapeout-version.mask_cost carries the `internal` marking: masked for a
        # principal without the claim, visible for one that holds it
        r = await c.get("/api/v1/objects/tapeout-version/TO-A0", headers=_hdr(PRODUCT))
        assert r.json()["mask_cost"] == "__masked__"
        r = await c.get("/api/v1/objects/tapeout-version/TO-A0", headers=_hdr({**PRODUCT, "markings": ["internal"]}))
        assert r.json()["mask_cost"] == 1850000.0  # decimal coerced on sync

    async def test_action_execute_full_cycle(self, client):
        c, _sc = client
        await c.post("/api/v1/admin/sync/tapeout-version")

        r = await c.post(
            "/api/v1/actions/tapeout/validate",
            json={"parameters": {}, "target_id": "TO-A1"},
            headers=_hdr(PRODUCT),
        )
        assert r.status_code == 200 and r.json()["policy"]["allow"]

        r = await c.post(
            "/api/v1/actions/tapeout/execute",
            json={"parameters": {}, "target_id": "TO-A1", "idempotency_key": "api-1"},
            headers=_hdr(PRODUCT),
        )
        assert r.status_code == 200
        rev_id = r.json()["revision_id"]
        assert r.json()["after"]["status"] == "FAB"

        # idempotent replay through the API
        r2 = await c.post(
            "/api/v1/actions/tapeout/execute",
            json={"parameters": {}, "target_id": "TO-A1", "idempotency_key": "api-1"},
            headers=_hdr(PRODUCT),
        )
        assert r2.json()["revision_id"] == rev_id

        # rule rejection surfaces as structured 422 (already FAB)
        r3 = await c.post(
            "/api/v1/actions/tapeout/execute",
            json={"parameters": {}, "target_id": "TO-A1"},
            headers=_hdr(PRODUCT),
        )
        assert r3.status_code == 422 and r3.json()["code"] == "RULE_REJECTED"

        # policy denial as 403 (fresh PLANNED target so rules pass first)
        created = await c.post(
            "/api/v1/actions/create-tapeout-version/execute",
            json={"parameters": {"project": "X1", "notes": "planned by the api test"}},
            headers=_hdr(PRODUCT),
        )
        assert created.status_code == 200, created.text
        new_version = created.json()["object_id"]
        r4 = await c.post(
            "/api/v1/actions/tapeout/execute",
            json={"parameters": {}, "target_id": new_version},
            headers=_hdr({"id": "visitor"}),
        )
        assert r4.status_code == 403

        # audit trail
        r5 = await c.get("/api/v1/audit/revisions", params={"object_id": "TO-A1"})
        outcomes = [x["outcome"] for x in r5.json()["revisions"]]
        assert "executed" in outcomes and "rejected_rule" in outcomes

    async def test_links_and_traverse(self, client):
        c, _ = client
        for t in OBJECT_TYPES:
            await c.post(f"/api/v1/admin/sync/{t}")
        # EQ-07 runs PS-7112 (lot LOT-2417) and PS-7132 (lot LOT-2419)
        r = await c.get("/api/v1/objects/equipment/EQ-07/links/step-equipment", headers=_hdr(PRODUCT))
        assert r.status_code == 200
        assert {o["step_id"] for o in r.json()} == {"PS-7112", "PS-7132"}

        r = await c.post(
            "/api/v1/graph/traverse",
            json={
                "start_type": "equipment",
                "start_ids": ["EQ-07"],
                "path": [{"link": "step-equipment", "direction": "out"}],
            },
            headers=_hdr(PRODUCT),
        )
        assert r.status_code == 200
        assert r.json()["steps"][-1]["type"] == "process-step"

    async def test_outbox_dispatch_and_history(self, client):
        c, _ = client
        await c.post("/api/v1/admin/sync/tapeout-version")
        await c.post(
            "/api/v1/actions/tapeout/execute",
            json={"parameters": {}, "target_id": "TO-A1"},
            headers=_hdr(PRODUCT),
        )
        r = await c.post("/api/v1/admin/outbox/dispatch")
        assert r.status_code == 200

        r = await c.get("/api/v1/objects/tapeout-version/TO-A1/history")
        versions = r.json()["versions"]
        assert len(versions) == 2 and versions[0]["_valid_to"] is not None

    async def test_evolve_loop_via_api(self, client):
        c, sc = client
        # the eval suite queries lots, steps, tests and field failures: all of
        # them must be materialized for a proposal to eval green
        for t in OBJECT_TYPES:
            await c.post(f"/api/v1/admin/sync/{t}")
        # generate telemetry: repeated unmapped filter usage
        for _ in range(6):
            await c.post(
                "/api/v1/objects/wafer-lot/query",
                json={"filter": {"field": "shift", "op": "eq", "value": "DAY"}},
                headers=_hdr(PRODUCT),
            )
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
        assert "shift" in mutated.find("ObjectType", "wafer-lot").spec.properties
        r = await c.get("/api/v1/meta/ontology")
        assert "shift" in r.json()["objects"]["wafer-lot"]["properties"]

    async def test_evolve_loop_is_convergent(self, client):
        """The loop's writes are idempotent: re-running aggregate re-detects
        nothing, and re-running diagnose does not re-file a live proposal.
        Together these are what make the evolution console safe to click
        repeatedly (and what the one-click demo rides on)."""
        c, _ = client
        for t in OBJECT_TYPES:
            await c.post(f"/api/v1/admin/sync/{t}")
        for _ in range(6):
            await c.post(
                "/api/v1/objects/wafer-lot/query",
                json={"filter": {"field": "shift", "op": "eq", "value": "DAY"}},
                headers=_hdr(PRODUCT),
            )
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
        await c.post("/api/v1/admin/sync/tapeout-version")
        await c.post(
            "/api/v1/actions/tapeout/execute",
            json={"parameters": {}, "target_id": "TO-A1"},
            headers=_hdr(PRODUCT),
        )
        await c.post(
            "/api/v1/actions/tapeout/execute",
            json={"parameters": {}, "target_id": "TO-A1"},
            headers=_hdr(PRODUCT),
        )  # rule rejection (already FAB)
        created = await c.post(
            "/api/v1/actions/create-tapeout-version/execute",
            json={"parameters": {"project": "X1", "notes": "telemetry probe"}},
            headers=_hdr(PRODUCT),
        )
        await c.post(
            "/api/v1/actions/tapeout/execute",
            json={"parameters": {}, "target_id": created.json()["object_id"]},
            headers=_hdr({"id": "visitor"}),
        )  # policy denial
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
            await c.post(
                "/api/v1/objects/wafer-lot/query",
                json={"filter": {"field": "shift", "op": "eq", "value": "DAY"}},
                headers=_hdr(PRODUCT),
            )
        await c.post("/api/v1/evolve/aggregate")

        class _FakeLLM:
            model = "fake"

            async def chat(self, messages, **kw):
                return {
                    "content": _json.dumps(
                        {
                            "act": True,
                            "analysis": "shift is the fab shift enum",
                            "mutations": [
                                {
                                    "mutation": "add-optional-property",
                                    "object": "wafer-lot",
                                    "prop": "shift",
                                    "type": "enum[DAY, NIGHT]",
                                    "display": "Shift",
                                    "description": "Fab shift this lot was started in",
                                }
                            ],
                            "rationale": "filter field shift recurs; semantically a shift enum",
                        }
                    )
                }

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

        pdef = load_package(sc.package_root).find("ObjectType", "wafer-lot").spec.properties["shift"]
        assert pdef.display == "Shift" and pdef.description == "Fab shift this lot was started in"
        assert pdef.type == "enum[DAY, NIGHT]"

    async def test_mount_csv_and_sync(self, client):
        """Data mounting end-to-end: CSV content -> store resource + object
        backing on disk -> publish -> sync pulls the rows through the normal
        engine (masking/quarantine apply)."""
        c, sc = client
        # the export carries only SOURCE-owned facts (no status/spec: those are
        # ontology-owned — change-requirement writes them; mounting a CSV that
        # claims them makes the validator correctly refuse the binding)
        csv_text = (
            "requirement_id,title,priority,created_at\n"
            "REQ-M1,Thermal margin review,HIGH,2026-09-18T08:00:00+00:00\n"
            "REQ-M2,Power budget cut,LOW,2026-09-18T09:00:00+00:00\n"
            "REQ-M3,ESD clamp resize,NORMAL,2026-09-18T10:00:00+00:00\n"
            "REQ-BAD,Bad enum,URGENT,2026-09-18T11:00:00+00:00\n"  # off-enum value -> quarantined
        )
        # the frontend preview auto-maps same-name columns and sends the FULL
        # mapping (empty mapping would mean "everything source-owned")
        full_mapping = {k: k for k in ["requirement_id", "title", "priority", "created_at"]}
        r = await c.post(
            "/api/v1/admin/builder/mount",
            json={
                "object": "requirement",
                "store": "csv-requirements",
                "source": {"kind": "csv", "filename": "requirements.csv", "content": csv_text},
                "mapping": full_mapping,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["published"] is True and body["store"] == "csv-requirements"
        assert body["sync"]["inserted"] == 3
        assert body["sync"]["quarantined"] == 1
        assert any(q["code"] and q["pk"] == "REQ-BAD" for q in body["quarantine"])

        # the rows are queryable through the normal door
        r = await c.post(
            "/api/v1/objects/requirement/query",
            json={"filter": {"field": "requirement_id", "op": "eq", "value": "REQ-M1"}},
            headers=_hdr(PRODUCT),
        )
        assert r.status_code == 200 and r.json()["total"] == 1

        # the store resource and the binding are on disk (builder-visible)
        pkg = Path(sc.package_root)
        assert (pkg / "stores" / "csv-requirements.yaml").is_file()
        import yaml as _yaml

        obj_doc = _yaml.safe_load((pkg / "objects" / "requirement.yaml").read_text())
        assert obj_doc["spec"]["backing"]["store"] == "csv-requirements"
        assert obj_doc["spec"]["backing"]["source"]["table"] == "requirements"

        # remount is idempotent (snapshot upsert -> noop)
        r2 = await c.post(
            "/api/v1/admin/builder/mount",
            json={
                "object": "requirement",
                "store": "csv-requirements",
                "source": {"kind": "csv", "filename": "requirements.csv", "content": csv_text},
                "mapping": full_mapping,
            },
        )
        assert r2.json()["sync"]["inserted"] == 0

        # a mount WITHOUT a mapping derives the same-name mapping from the CSV
        # header (never empty mapping = everything source-owned)
        r3 = await c.post(
            "/api/v1/admin/builder/mount",
            json={
                "object": "requirement",
                "store": "csv-requirements",
                "source": {"kind": "csv", "filename": "requirements.csv", "content": csv_text},
            },
        )
        assert r3.status_code == 200
        assert r3.json()["mapping"]["requirement_id"] == "requirement_id"

    async def test_mount_sqlite_source(self, client, tmp_path):
        c, _sc = client

        src = tmp_path / "extra.db"
        con = sqlite3.connect(str(src))
        con.execute("CREATE TABLE customers_extra (customer_id TEXT PRIMARY KEY, name TEXT, segment TEXT, region TEXT)")
        con.execute("INSERT INTO customers_extra VALUES ('CX-1','Gasket Co','industrial','NA')")
        con.commit()
        con.close()

        r = await c.post(
            "/api/v1/admin/builder/mount",
            json={
                "object": "customer",
                "source": {"kind": "sqlite", "dsn": f"sqlite+aiosqlite:///{src}", "table": "customers_extra"},
                "mapping": {
                    "customer_id": "customer_id",
                    "name": "name",
                    "segment": "segment",
                    "region": "region",
                },
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["sync"]["inserted"] == 1

    async def test_mount_rejects_unknown_object_and_bad_source(self, client):
        c, _ = client
        r = await c.post(
            "/api/v1/admin/builder/mount", json={"object": "nope", "source": {"kind": "csv", "content": "a\n1"}}
        )
        assert r.status_code == 404
        r2 = await c.post(
            "/api/v1/admin/builder/mount", json={"object": "wafer-lot", "source": {"kind": "csv"}}
        )  # no content
        assert r2.status_code == 422
        r3 = await c.post(
            "/api/v1/admin/builder/mount", json={"object": "wafer-lot", "source": {"kind": "sqlite"}}
        )  # no dsn/table
        assert r3.status_code == 422

    async def test_mount_refuses_source_missing_required_properties(self, client):
        """A CSV lacking a required property would hit NOT NULL mid-insert (a
        raw 500); the mount must refuse with the actual list instead."""
        c, _ = client
        r = await c.post(
            "/api/v1/admin/builder/mount",
            json={
                "object": "requirement",  # title is required too
                "source": {"kind": "csv", "filename": "bad.csv", "content": "requirement_id\nREQ-X"},
            },
        )
        assert r.status_code == 422
        assert "title" in r.json()["message"]

    async def test_meta_exposes_cedar_role_vocabulary(self, client):
        c, _ = client
        r = (await c.get("/api/v1/meta/ontology")).json()
        assert "product" in r["roles"]

    async def test_create_agent_plugin_via_builder(self, client):
        """The plugins tab's "new plugin" flow: AgentPlugin resource through the
        builder door -> on disk -> published -> listed with its effective
        toolset. The role vocabulary comes from meta.roles."""
        c, _sc = client
        meta = (await c.get("/api/v1/meta/ontology")).json()
        assert meta["roles"], "demo package must reference at least one role"

        plugin = {
            "apiVersion": "ontogeny/v1",
            "kind": "AgentPlugin",
            "metadata": {"name": "fab-copilot-test", "display": "Fab copilot", "description": "read-only queries"},
            "spec": {
                "engine": {"kind": "builtin-llm"},
                "principal": {"id": "agent:fab-copilot-test", "Role": meta["roles"][:1], "site": "fab-site-a"},
                "tools": {"allow": ["describe_ontology", "search_wafer_lot"]},
                "approval": {"writes": "never"},
                "budget": {"steps": 20, "wall_ms": 60000, "writes_per_session": 0},
            },
        }
        r = await c.post("/api/v1/admin/builder/save", json={"resources": [plugin]})
        assert r.status_code == 200, r.text
        assert "AgentPlugin/fab-copilot-test" in r.json()["written"]

        # listed at runtime with its narrowed toolset
        r = await c.get("/api/v1/agent/plugins")
        by_name = {p["name"]: p for p in r.json()["plugins"]}
        assert "fab-copilot-test" in by_name
        assert "describe_ontology" in by_name["fab-copilot-test"]["tools"]
        assert "search_wafer_lot" in by_name["fab-copilot-test"]["tools"]

    async def test_error_shape(self, client):
        c, _ = client
        r = await c.get("/api/v1/objects/nope/x")
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


async def test_meta_storage_names_the_physical_target(client):
    """/meta/storage spells out where materialized data lives: the platform's
    own db (the console renders this next to every "materialized" label)."""
    c, _sc = client
    r = await c.get("/api/v1/meta/storage")
    assert r.status_code == 200
    body = r.json()
    assert body["target"]["kind"] == "sqlite"
    assert body["target"]["target"].endswith("main.db")
    lot = body["objects"]["wafer-lot"]
    assert lot["table"] == "ontogeny_obj_wafer_lot"
    assert lot["store"] == "fab" and lot["mode"] == "materialized"
    assert lot["source_table"] == "wafer_lots"
    assert lot["sync"] == "watermark" and lot["sync_watermark"] == "updated_at"
    # rows is a live count (0 right after ensure_tables, null if never synced)
    assert lot.get("rows") in (None, 0)
