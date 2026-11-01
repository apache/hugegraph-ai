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

"""Content contract for the chip-lifecycle domain package.

The package is the second showcase domain (semiconductor lifecycle); this
module pins the promises that make it a complete case --

* the package validates cleanly;
* after seeding its source SQL and syncing, EVERY object type has rows;
* EVERY declared function runs successfully against that data and its
  answers match the seeded story (yield loss, impact, pareto);
* EVERY action dry-runs as allowed for its role, and a real requirement ->
  tapeout -> lot -> test -> alert -> root-cause chain plus a field-failure
  chain execute end to end;
* the detailed FMEA document extracts into 7 fmea-notes resolved to the
  existing design module DSG-201.

If any of these break (a renamed seed column, a capability that no longer
covers a query, a policy that stopped permitting), the showcase would be
shipping a broken domain -- which is exactly what this catches.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from ontogeny.api import build_app
from ontogeny.config import Settings
from ontogeny.service import ServiceContext

REPO = Path(__file__).resolve().parent.parent
DOMAIN = REPO / "domains" / "chip-lifecycle"
FMEA_AGENT = DOMAIN / "tools" / "doc_agent_fmea_module.py"

PRODUCT = {"id": "u-pm", "Role": ["product"]}
FAB = {"id": "u-fab", "Role": ["fab"]}
CQE = {"id": "u-cqe", "Role": ["cqe"]}


def _hdr(p):
    return {"X-Ontogeny-Principal": json.dumps(p)}


@pytest_asyncio.fixture()
async def chip(tmp_path):
    """A live ServiceContext + ASGI client over the chip-lifecycle domain,
    with its seed SQL materialized into a private SQLite source."""
    pkg_root = tmp_path / "pkg"
    shutil.copytree(DOMAIN, pkg_root)
    src = tmp_path / "source.db"
    con = sqlite3.connect(str(src))
    con.executescript((DOMAIN / "seed" / "01_source.sql").read_text(encoding="utf-8"))
    con.commit()
    con.close()

    settings = Settings(
        dev_auth=True,
        db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'ontogeny.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}"},
    )
    sc = ServiceContext(settings, str(pkg_root))
    await sc.initialize()
    app = build_app(sc)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://t",
        headers={"X-Ontogeny-Principal": json.dumps({"id": "ci-admin", "is_admin": True})},
    ) as c:
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

    async def test_every_object_type_has_data(self, chip):
        c, sc = chip
        for obj_type in sc.compiled.objects:
            if sc.compiled.objects[obj_type].spec.backing.sync.strategy == "extract":
                continue  # populated by document extraction, not the source seed
            r = await c.post(f"/api/v1/objects/{obj_type}/query", json={"filter": None}, headers=_hdr(PRODUCT))
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["total"] > 0, f"object type {obj_type} has no seeded rows"

    async def test_every_function_runs_successfully(self, chip):
        """Each function is invoked with a real seeded id: the showcase must
        never ship a declared function that cannot run."""
        c, sc = chip
        cases = {
            "requirement-impact": {"requirement_id": "REQ-101"},
            "analyze-yield-loss": {"test_id": "WT-501"},
            "analyze-field-failure": {"failure_id": "FF-8001"},
            "yield-pareto": {},
        }
        assert set(cases) == set(sc.compiled.functions), "a function was added to the package without a contract case"
        for name, params in cases.items():
            r = await c.post(f"/api/v1/functions/{name}/invoke", json={"parameters": params}, headers=_hdr(PRODUCT))
            assert r.status_code == 200, r.text
            assert r.json()["value"], f"function {name} returned nothing"

    async def test_function_answers_match_the_seeded_story(self, chip):
        c, _sc = chip

        # WT-501: 36 defects on 200 tested units -> 18% loss, HOLD,
        # PROCESS 0.82 above the 10% line plus the standing DESIGN 0.55
        r = await c.post(
            "/api/v1/functions/analyze-yield-loss/invoke",
            json={"parameters": {"test_id": "WT-501"}},
            headers=_hdr(FAB),
        )
        value = r.json()["value"]
        assert value["yield"] == 0.82 and value["loss"] == 0.18
        assert value["recommended_action"] == "HOLD"
        by_class = {cand["root_cause_class"]: cand["confidence"] for cand in value["candidates"]}
        assert by_class == {"PROCESS": 0.82, "DESIGN": 0.55}

        # WT-502: 4% loss stays below the 5% line -> REVIEW, DESIGN only
        r = await c.post(
            "/api/v1/functions/analyze-yield-loss/invoke",
            json={"parameters": {"test_id": "WT-502"}},
            headers=_hdr(FAB),
        )
        value = r.json()["value"]
        assert value["recommended_action"] == "REVIEW"
        assert [cand["root_cause_class"] for cand in value["candidates"]] == ["DESIGN"]

        # REQ-101 is implemented by DSG-201 (TO-A0) and DSG-211 (TO-A1);
        # TO-A0 has LOT-2417/2418 complete and LOT-2419 still running
        r = await c.post(
            "/api/v1/functions/requirement-impact/invoke",
            json={"parameters": {"requirement_id": "REQ-101"}},
            headers=_hdr(PRODUCT),
        )
        value = r.json()["value"]
        assert {m["module_id"] for m in value["modules"]} == {"DSG-201", "DSG-211"}
        assert {v["version_id"] for v in value["versions"]} == {"TO-A0", "TO-A1"}
        assert value["at_risk_lots"] == ["LOT-2419"]
        assert value["at_risk_wafers"] == 25

        # the pareto ranks LOT-2417 (18% loss, etched on EQ-07) first
        r = await c.post(
            "/api/v1/functions/yield-pareto/invoke",
            json={"parameters": {}},
            headers=_hdr(FAB),
        )
        value = r.json()["value"]
        assert value["ranking"][0]["lot_id"] == "LOT-2417"
        assert "Etch@EQ-07" in value["ranking"][0]["route"]

        # a parametric field failure yields both candidates, DESIGN on top
        r = await c.post(
            "/api/v1/functions/analyze-field-failure/invoke",
            json={"parameters": {"failure_id": "FF-8001"}},
            headers=_hdr(CQE),
        )
        value = r.json()["value"]
        assert value["customer"] == "ASTRA Mobility"
        assert value["candidates"][0]["root_cause_class"] == "DESIGN"

    async def test_every_action_dry_runs_allowed_for_its_role(self, chip):
        """One seeded target per action, dry-run (validate) with the role its
        policy permits: every action in the package must be usable."""
        c, sc = chip
        cases = {
            "create-requirement": (PRODUCT, {"title": "IO slew rate control", "priority": "NORMAL"}),
            "change-requirement": (PRODUCT, {"spec": "±12kV contact discharge", "reason": "field feedback"}),
            "create-design-module": (PRODUCT, {"name": "Thermal sensor", "requirement_id": "REQ-104"}),
            "create-tapeout-version": (PRODUCT, {"project": "X3"}),
            "tapeout": (PRODUCT, {}),
            "start-lot": (FAB, {"version_id": "TO-A1", "qty_wafers": 25, "site": "fab-site-a"}),
            "complete-process-step": (FAB, {}),
            "hold-lot": (FAB, {"reason": "yield investigation"}),
            "record-wafer-test": (FAB, {"lot_id": "LOT-2419", "tested_qty": 25, "defect_qty": 1, "result": "PENDING"}),
            "retract-wafer-test": (FAB, {"reason": "recorded in error"}),
            "reassign-step": (FAB, {"equipment_id": "EQ-09"}),
            "open-field-failure": (
                CQE,
                {"customer_id": "C-202", "symptom": "no boot on 3.3 V rail", "failure_mode": "FUNCTIONAL"},
            ),
            "raise-yield-alert": (FAB, {"severity": "MAJOR", "kind": "YIELD_DROP"}),
            "raise-surge-alert": (CQE, {"severity": "MAJOR", "kind": "DEFECT_SURGE"}),
            "record-root-cause": (
                FAB,
                {"root_cause": "Etch drift on EQ-07", "root_cause_class": "PROCESS", "confidence": 0.82},
            ),
            "record-failure-root-cause": (
                CQE,
                {"root_cause": "EQ-07 lot excursion", "root_cause_class": "PROCESS", "confidence": 0.85},
            ),
        }
        assert set(cases) == set(sc.compiled.actions), "an action was added to the package without a contract case"
        target_ids = {
            "change-requirement": ("requirement", "REQ-101"),
            "tapeout": ("tapeout-version", "TO-A1"),
            "complete-process-step": ("process-step", "PS-7132"),
            "retract-wafer-test": ("wafer-test", "WT-503"),
            "reassign-step": ("process-step", "PS-7212"),
            "hold-lot": ("wafer-lot", "LOT-2419"),
            "raise-yield-alert": ("wafer-test", "WT-501"),
            "raise-surge-alert": ("field-failure", "FF-8001"),
            "record-root-cause": ("wafer-test", "WT-501"),
            "record-failure-root-cause": ("field-failure", "FF-8001"),
        }
        for name, (principal, params) in cases.items():
            body: dict = {"parameters": params}
            if name in target_ids:
                body["target_id"] = target_ids[name][1]
            r = await c.post(f"/api/v1/actions/{name}/validate", json=body, headers=_hdr(principal))
            assert r.status_code == 200, f"{name}: {r.text}"
            assert r.json()["policy"]["allow"] is True, f"{name} denied: {r.json()}"

    async def test_a_real_chain_executes_end_to_end(self, chip):
        """requirement -> module -> version -> tapeout -> lot -> step -> test
        -> alert -> root cause, plus the field-failure chain: the action
        shapes (create-object, conditional modify, modify, modify-linked,
        emit-event) really run."""
        c, _sc = chip

        r = await c.post(
            "/api/v1/actions/create-requirement/execute",
            json={
                "parameters": {
                    "title": "JTAG debug port lock",
                    "priority": "HIGH",
                    "spec": "JTAG port locks unless unlocked by fuse",
                }
            },
            headers=_hdr(PRODUCT),
        )
        assert r.status_code == 200, r.text
        requirement_id = r.json()["object_id"]
        assert r.json()["after"]["status"] == "OPEN"

        r = await c.post(
            "/api/v1/actions/create-design-module/execute",
            json={"parameters": {"name": "Debug port controller", "requirement_id": requirement_id}},
            headers=_hdr(PRODUCT),
        )
        assert r.status_code == 200, r.text

        r = await c.post(
            "/api/v1/actions/create-tapeout-version/execute",
            json={"parameters": {"project": "X1", "notes": "metal spin for debug port"}},
            headers=_hdr(PRODUCT),
        )
        assert r.status_code == 200, r.text
        version_id = r.json()["object_id"]
        assert r.json()["after"]["status"] == "PLANNED"

        r = await c.post(
            "/api/v1/actions/tapeout/execute",
            json={"parameters": {}, "target_id": version_id},
            headers=_hdr(PRODUCT),
        )
        assert r.status_code == 200 and r.json()["after"]["status"] == "FAB"

        r = await c.post(
            "/api/v1/actions/start-lot/execute",
            json={"parameters": {"version_id": version_id, "qty_wafers": 10, "site": "fab-site-a"}},
            headers=_hdr(FAB),
        )
        assert r.status_code == 200, r.text
        lot_id = r.json()["object_id"]
        assert r.json()["after"]["status"] == "RUNNING"

        r = await c.post(
            "/api/v1/actions/hold-lot/execute",
            json={"parameters": {"reason": "pending engineering hold"}, "target_id": lot_id},
            headers=_hdr(FAB),
        )
        assert r.status_code == 200 and r.json()["after"]["status"] == "ON_HOLD"

        r = await c.post(
            "/api/v1/actions/complete-process-step/execute",
            json={"parameters": {}, "target_id": "PS-7132"},
            headers=_hdr(FAB),
        )
        assert r.status_code == 200 and r.json()["after"]["status"] == "COMPLETED"

        r = await c.post(
            "/api/v1/actions/record-wafer-test/execute",
            json={
                "parameters": {
                    "lot_id": "LOT-2419",
                    "tested_qty": 40,
                    "defect_qty": 5,
                    "result": "FAIL",
                    "tester": "cp-eng-02",
                }
            },
            headers=_hdr(FAB),
        )
        assert r.status_code == 200, r.text
        test_id = r.json()["object_id"]
        assert r.json()["after"]["defect_qty"] == 5

        r = await c.post(
            "/api/v1/actions/raise-yield-alert/execute",
            json={"parameters": {"severity": "MAJOR", "kind": "YIELD_DROP"}, "target_id": test_id},
            headers=_hdr(FAB),
        )
        assert r.status_code == 200 and r.json()["after"]["alert_status"] == "OPEN"

        r = await c.post(
            "/api/v1/actions/record-root-cause/execute",
            json={
                "parameters": {"root_cause": "Etch drift on EQ-07", "root_cause_class": "PROCESS", "confidence": 0.82},
                "target_id": test_id,
            },
            headers=_hdr(FAB),
        )
        assert r.status_code == 200 and r.json()["after"]["root_cause_class"] == "PROCESS"

        # the field-failure chain: open -> surge alert -> root cause
        r = await c.post(
            "/api/v1/actions/open-field-failure/execute",
            json={
                "parameters": {
                    "customer_id": "C-202",
                    "symptom": "IO pin leakage above 10 nA at 25 °C",
                    "failure_mode": "PARAMETRIC",
                }
            },
            headers=_hdr(CQE),
        )
        assert r.status_code == 200, r.text
        failure_id = r.json()["object_id"]
        assert r.json()["after"]["status"] == "OPEN"

        r = await c.post(
            "/api/v1/actions/raise-surge-alert/execute",
            json={"parameters": {"severity": "MAJOR", "kind": "DEFECT_SURGE"}, "target_id": failure_id},
            headers=_hdr(CQE),
        )
        assert r.status_code == 200 and r.json()["after"]["alert_severity"] == "MAJOR"

        r = await c.post(
            "/api/v1/actions/record-failure-root-cause/execute",
            json={
                "parameters": {
                    "root_cause": "EQ-07 etch lot excursion",
                    "root_cause_class": "PROCESS",
                    "confidence": 0.85,
                },
                "target_id": failure_id,
            },
            headers=_hdr(CQE),
        )
        assert r.status_code == 200
        assert r.json()["after"]["status"] == "ANALYZED"
        assert r.json()["after"]["confidence"] == 0.85

    async def test_rules_actually_reject(self, chip):
        """A broken rule would make the showcase permissive: prove the guards."""
        c, _sc = chip
        # validate is a dry-run: a failing rule is REPORTED, not raised
        r = await c.post(
            "/api/v1/actions/record-wafer-test/validate",
            json={"parameters": {"lot_id": "LOT-2419", "tested_qty": 10, "defect_qty": 11, "result": "FAIL"}},
            headers=_hdr(FAB),
        )
        assert r.status_code == 200
        assert any(not rule["ok"] for rule in r.json()["rules"])
        r = await c.post(
            "/api/v1/actions/tapeout/validate",
            json={"parameters": {}, "target_id": "TO-A0"},  # already FAB
            headers=_hdr(PRODUCT),
        )
        assert r.status_code == 200
        assert any(not rule["ok"] for rule in r.json()["rules"])
        # ... and execute refuses the same input outright
        r = await c.post(
            "/api/v1/actions/record-wafer-test/execute",
            json={"parameters": {"lot_id": "LOT-2419", "tested_qty": 10, "defect_qty": 11, "result": "FAIL"}},
            headers=_hdr(FAB),
        )
        assert r.status_code == 422

    async def test_role_isolation_is_enforced(self, chip):
        """Cedar grants are role-scoped: the fab role must not write
        requirements, the cqe role must not write test root causes."""
        c, _sc = chip
        r = await c.post(
            "/api/v1/actions/change-requirement/validate",
            json={"parameters": {"spec": "±12kV"}, "target_id": "REQ-101"},
            headers=_hdr(FAB),
        )
        assert r.status_code == 200
        assert r.json()["policy"]["allow"] is False
        r = await c.post(
            "/api/v1/actions/record-root-cause/validate",
            json={
                "parameters": {"root_cause": "x", "root_cause_class": "PROCESS", "confidence": 0.5},
                "target_id": "WT-501",
            },
            headers=_hdr(CQE),
        )
        assert r.status_code == 200
        assert r.json()["policy"]["allow"] is False


@pytest.mark.asyncio
async def test_fmea_document_extracts_notes_to_design_module(tmp_path):
    """The detailed FMEA document: 7 table rows -> 7 fmea-notes, each
    resolved to the existing design-module DSG-201, written only after
    human confirm."""
    import sys

    pkg = tmp_path / "pkg"
    shutil.copytree(DOMAIN, pkg)
    src = tmp_path / "source.db"
    con = sqlite3.connect(src)
    con.executescript((pkg / "seed" / "01_source.sql").read_text(encoding="utf-8"))
    con.commit()
    con.close()
    sc = ServiceContext(
        Settings(
            db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}",
            dev_auth=True,
            env={"ERP_DSN": f"sqlite+aiosqlite:///{src}"},
            extensions_dir=str(REPO / "extensions"),
            doc_agent_cmd=f"{sys.executable} {FMEA_AGENT}",
        ),
        str(pkg),
    )
    await sc.initialize()
    try:
        for object_type in sc.compiled.objects:
            if object_type != "fmea-note":
                await sc.sync(object_type)
        docs = (await sc.documents.list_documents("chip-docs"))["documents"]
        assert [d["name"] for d in docs] == ["fmea-io-esd-dsg201.md"]
        fmea = docs[0]

        schema = await sc.documents.tasks.schema_options("chip-docs")
        fmea_option = next(o for o in schema["objects"] if o["name"] == "fmea-note")
        props = [p["name"] for p in fmea_option["properties"]]
        assert {(link["name"], link["source"]) for link in schema["links"]} == {("design-fmea-notes", "design-module")}

        task = (
            await sc.documents.tasks.create_tasks(
                "chip-docs",
                [],
                doc_ids=[fmea["id"]],
                scope={"objects": {"fmea-note": props}, "links": ["design-fmea-notes"]},
                skill={"id": "graph-extract"},
                principal="tester",
            )
        )["tasks"][0]
        detail = await sc.documents.tasks.run(task["id"], "tester")
        assert detail["attempt"]["validation"]["blockers"] == []
        assert detail["attempt"]["validation"]["references"] == [["design-module", "DSG-201"]]
        assert detail["attempt"]["validation"]["objects"] == 7
        assert detail["attempt"]["validation"]["links"] == 7

        confirmed = await sc.documents.tasks.confirm(task["id"], "tester")
        assert confirmed["summary"]["inserted"] == 7 and confirmed["summary"]["links"] == 7

        async with sc.sessionmaker() as session:
            notes, total = await sc.repo.query(session, "fmea-note", limit=20)
            links = await sc.repo.link_members(session, "design-fmea-notes")
        assert total == 7
        assert {n["fmea_id"] for n in notes} == {
            "FM-DSG201-01",
            "FM-DSG201-02",
            "FM-DSG201-03",
            "FM-DSG201-04",
            "FM-DSG201-05",
            "FM-DSG201-06",
            "FM-DSG201-07",
        }
        assert {src for src, _ in links} == {"DSG-201"}
        by_fmea_id = {n["fmea_id"]: n for n in notes}
        # RPN = S x O x D: FM-DSG201-02 is 7x3x5 = 105, the only one above 100
        assert by_fmea_id["FM-DSG201-02"]["rpn"] == 105
        assert by_fmea_id["FM-DSG201-01"]["cause"].startswith("Clamp footprint")
        assert all(n["source_doc"] == "fmea-io-esd-dsg201.md" for n in notes)
    finally:
        if sc.engine is not None:
            await sc.engine.dispose()


def test_demo_bootstrap_seeds_the_chip_domain(tmp_path):
    """`ontogeny serve --demo --package domains/chip-lifecycle` must bootstrap:
    the package's own seed SQL builds the demo source DB and the env points
    the fab store at it. Runs on a copy so the repo tree stays untouched."""
    from ontogeny.demo.bootstrap import prepare_demo

    src = tmp_path / "domains" / "chip-lifecycle"
    src.parent.mkdir()
    shutil.copytree(DOMAIN, src)
    paths = prepare_demo(tmp_path / "demo", package=src)
    assert (paths.package_root / "ontology.yaml").is_file()

    env = paths.as_env()
    assert env["ONTOGENY_PACKAGE_ROOT"] == str(paths.package_root)
    assert env["ERP_DSN"].startswith("sqlite+aiosqlite:///")

    con = sqlite3.connect(paths.erp_dsn.removeprefix("sqlite+aiosqlite:///"))
    try:
        assert con.execute("SELECT COUNT(*) FROM wafer_tests").fetchone()[0] == 3
        assert con.execute("SELECT COUNT(*) FROM field_failures").fetchone()[0] == 3
        assert con.execute("SELECT lot_id FROM field_failures WHERE failure_id = 'FF-8001'").fetchone()[0] == "LOT-2417"
    finally:
        con.close()


def _run_router(request: dict) -> dict:
    import subprocess

    out = subprocess.run(
        [sys.executable, REPO / "tools" / "doc_agent_demo.py"],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def _doc_request(doc_path: Path, schema: dict) -> dict:
    return {
        "protocol": "ontogeny-doc-agent/v1",
        "schema": schema,
        "document": {"id": "doc-1", "name": doc_path.name, "text": doc_path.read_text(encoding="utf-8")},
    }


CHIP_SCHEMA = {
    "vertexlabels": [
        {
            "name": "fmea-note",
            "properties": [
                "title",
                "fmea_id",
                "module_id",
                "failure_mode",
                "cause",
                "effect",
                "severity",
                "occurrence",
                "detection",
                "rpn",
                "recommended_action",
                "source_doc",
                "status",
            ],
        },
        {"name": "design-module", "properties": ["module_id"]},
    ],
    "edgelabels": [{"name": "design-fmea-notes"}],
}


def test_doc_agent_demo_routes_module_fmea_by_reference_type():
    """One ONTOGENY_DOC_AGENT_CMD serves every document case: the router
    picks the module FMEA agent when the schema carries the design-module
    reference, so the daemon console extracts chip FMEA documents with
    module_id, and falls back to the generic reference agent otherwise."""
    result = _run_router(_doc_request(DOMAIN / "data" / "docs" / "fmea-io-esd-dsg201.md", CHIP_SCHEMA))
    chunks = result["chunks"]
    assert len(chunks) == 7
    notes = [v for c in chunks for v in c["graph"]["vertices"] if v["label"] == "fmea-note"]
    refs = [v for c in chunks for v in c["graph"]["vertices"] if v["label"] == "design-module"]
    edges = [e for c in chunks for e in c["graph"]["edges"]]
    assert all(n["properties"]["module_id"] == "DSG-201" for n in notes)
    assert all(n["properties"]["title"].startswith("DSG-201 · ") for n in notes)
    assert refs and all(r["properties"] == {"module_id": "DSG-201"} for r in refs)
    assert {e["label"] for e in edges} == {"design-fmea-notes"}

    # a schema without the design-module reference falls through to the
    # generic reference agent instead of the FMEA table parser
    generic = {"vertexlabels": [{"name": "memo-note", "properties": ["title"]}], "edgelabels": []}
    result = _run_router(_doc_request(DOMAIN / "data" / "docs" / "fmea-io-esd-dsg201.md", generic))
    assert len(result["chunks"]) == 1
