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

"""Domain example, system level: package integrity plus the full
requirement -> tapeout -> lot -> step -> test execution chain, and every cross-cutting
capability the golden package must keep demonstrating: masking, derived
properties, audit with rejections, sandboxed functions, eval suites,
projections and evolution promotion.

The old richer system fixture also demoed maintenance and procurement chains
and llm/http capability functions; chip-lifecycle does not model those,
so their coverage lives where the capability lives (join-table links: the
worker rig in test_projection_hugegraph; llm/http capabilities: the inline
package below).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from ontogeny.config import Settings
from ontogeny.core import load_package, validate
from ontogeny.demo import prepare_demo
from ontogeny.service import ServiceContext

# A minimal inline package demonstrating the sandbox capabilities the golden
# domain does not use (it reads objects only). Keeping it here pins the
# capability vocabulary: a kind nobody declares is a feature nobody runs.
CAPABILITY_DEMO_PKG = {
    "ontology.yaml": """\
apiVersion: ontogeny/v1
kind: Ontology
metadata:
  name: capability-demo
  display: Capability demo
spec:
  imports: []
""",
    "functions/capability-demo-fn.yaml": """\
apiVersion: ontogeny/v1
kind: Function
metadata:
  name: capability-demo-fn
  display: Capability demo fn
spec:
  runtime: python
  entry: demo_fn.py:run
  parameters:
    q:
      type: string
      required: true
  returns:
    type: string
  capabilities:
  - llm: {}
  - http: {}
""",
}

PRODUCT = {"id": "u-product", "Role": ["product"], "site": "hq"}
FAB = {"id": "u-fab", "Role": ["fab"], "site": "fab-site-a"}
CQE = {"id": "u-cqe", "Role": ["cqe"], "site": "hq"}
OUTSIDER = {"id": "u-outsider", "Role": ["visitor"]}


class TestPackage:
    def test_validates(self, golden_pkg_path):
        pkg = load_package(golden_pkg_path)
        rep = validate(pkg)
        errs = [f"{i.code}:{i.message}" for i in rep.issues if i.severity == "error"]
        assert not errs, errs

    def test_scale_is_domain_level(self, golden_pkg_path):
        pkg = load_package(golden_pkg_path)
        assert len(pkg.objects()) >= 7
        assert len(pkg.links()) >= 6
        assert len(pkg.actions()) >= 8
        assert len(pkg.functions()) >= 3
        assert len(pkg.policies()) >= 2
        assert len(pkg.projections()) == 1
        assert len(pkg.eval_suites()) == 1
        assert pkg.evolution_policy() is not None

    def test_declared_capabilities_stay_inside_the_sandbox_vocabulary(self, golden_pkg_path):
        """Every capability the golden package declares must be a kind the
        sandbox boundary actually offers, and its functions must demonstrate
        the kind they lean on (read-objects)."""
        from ontogeny.core.validator import CAPABILITY_KINDS

        pkg = load_package(golden_pkg_path)
        declared: set[str] = set()
        for fn in pkg.functions():
            for cap in fn.spec.capabilities:
                declared |= set(cap.model_dump(exclude_none=True).keys())
        assert declared and declared <= set(CAPABILITY_KINDS), (
            f"unknown capability kinds declared: {sorted(declared - set(CAPABILITY_KINDS))}"
        )
        assert "read-objects" in declared

    def test_the_whole_capability_vocabulary_stays_demonstrated(self, tmp_path):
        """The vocabulary is the sandbox boundary's: FN-CAP accepts exactly
        {read-objects, llm, http}, and those are the RPCs a child process can
        make. The golden domain reads objects only, so the remaining kinds stay
        demoed by this inline package -- a kind with no function demonstrating
        it is a documented feature nobody has run (which is how the `llm`
        budget bug survived until one was finally invoked)."""
        from ontogeny.core.validator import CAPABILITY_KINDS

        for rel, text in CAPABILITY_DEMO_PKG.items():
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        pkg = load_package(tmp_path)
        declared: set[str] = set()
        for fn in pkg.functions():
            for cap in fn.spec.capabilities:
                declared |= set(cap.model_dump(exclude_none=True).keys())
        assert declared == set(CAPABILITY_KINDS) - {"read-objects"}, (
            f"capability kinds never demoed: {sorted(set(CAPABILITY_KINDS) - declared)}"
        )

    def test_ships_its_own_seed(self, golden_pkg_path):
        seed = golden_pkg_path / "seed" / "01_source.sql"
        assert seed.is_file()
        text = seed.read_text(encoding="utf-8")
        for table in (
            "requirements",
            "design_modules",
            "tapeout_versions",
            "equipment",
            "wafer_lots",
            "process_steps",
            "wafer_tests",
        ):
            assert f"CREATE TABLE {table}" in text

    def test_marked_properties_stay_out_of_the_projection(self, golden_pkg_path):
        pkg = load_package(golden_pkg_path)
        prj = pkg.projections()[0]
        for obj_name, cfg in prj.spec.include.objects.items():
            obj = pkg.find("ObjectType", obj_name)
            marked = {p for p, d in obj.spec.properties.items() if d.marking}
            assert not (marked & set(cfg.properties)), f"{obj_name}: marked property leaked into graph"


@pytest_asyncio.fixture()
async def sc(tmp_path, golden_pkg_path):
    paths = prepare_demo(tmp_path / "demo", package=golden_pkg_path)
    env = paths.as_env()
    ctx = ServiceContext(Settings(db_dsn=env["ONTOGENY_DB_DSN"], env=env), env["ONTOGENY_PACKAGE_ROOT"])
    await ctx.initialize()
    for object_type in ctx.compiled.objects:
        await ctx.sync(object_type)
    yield ctx
    if ctx.engine is not None:
        await ctx.engine.dispose()


async def execute(sc, action, principal, params, target=None, **kw):
    async with sc.sessionmaker() as s:
        rev = await sc.runtime.execute(s, action, principal, params, target, **kw)
        await s.commit()
        return rev


SYSTEM = {"id": "test-runner", "Role": ["product"], "markings": ["internal"]}


async def get(sc, object_type, obj_id):
    """Read through the query service: derived properties are assembled there."""
    async with sc.sessionmaker() as s:
        return await sc.query.get(s, object_type, obj_id, SYSTEM)


class TestSyncCoverage:
    async def test_every_object_type_syncs(self, sc):
        async with sc.sessionmaker() as s:
            for name in sc.compiled.objects:
                if sc.compiled.objects[name].spec.backing.sync.strategy == "extract":
                    continue  # extracted from documents, not seeded in SQL
                _rows, total = await sc.repo.query(s, name, limit=1)
                assert total > 0, f"{name} synced no rows"

    async def test_derived_properties_compute(self, sc):
        tv = await get(sc, "tapeout-version", "TO-A0")
        assert tv["fab_lag_h"] == pytest.approx(936.0)  # taped out 39 days after creation
        tv = await get(sc, "tapeout-version", "TO-A1")
        assert tv["fab_lag_h"] is None  # not taped out yet: nothing to derive from

    async def test_fk_links_traverse(self, sc):
        async with sc.sessionmaker() as s:
            linked = await sc.repo.fk_linked_ids(s, "version-lots", "TO-A0", from_source=True)
        assert "LOT-2417" in linked
        assert "LOT-2418" in linked


class TestPlanToFab:
    async def test_create_and_tapeout_version(self, sc):
        rev = await execute(
            sc,
            "create-tapeout-version",
            PRODUCT,
            {
                "project": "X9",
                "notes": "Trial version for the system-level chain",
            },
        )
        vid = rev.object_id
        assert vid.startswith("TO-")

        tv = await get(sc, "tapeout-version", vid)
        assert tv["status"] == "PLANNED" and tv["project"] == "X9"

        await execute(sc, "tapeout", PRODUCT, {}, vid)
        tv = await get(sc, "tapeout-version", vid)
        assert tv["status"] == "FAB" and tv["taped_out_at"] is not None

        from ontogeny.errors import RuleRejectedError

        with pytest.raises(RuleRejectedError):
            await execute(sc, "tapeout", PRODUCT, {}, vid)

    async def test_create_requires_product_role(self, sc):
        from ontogeny.errors import PolicyDeniedError

        with pytest.raises(PolicyDeniedError):
            await execute(sc, "create-tapeout-version", FAB, {"project": "X9"})

    async def test_tapeout_requires_product_role(self, sc):
        """The Cedar `when` clause gates product to PLANNED versions; fab
        holds no tapeout permit at all -- policy denies before rules matter."""
        from ontogeny.errors import PolicyDeniedError

        with pytest.raises(PolicyDeniedError):
            await execute(sc, "tapeout", FAB, {}, "TO-A1")


class TestFabFloor:
    async def test_complete_process_step_moves_and_stamps(self, sc):
        await execute(sc, "complete-process-step", FAB, {"note": "Etch finished on EQ-07"}, "PS-7132")
        step = await get(sc, "process-step", "PS-7132")
        assert step["status"] == "COMPLETED" and step["completed_at"] is not None

        from ontogeny.errors import RuleRejectedError

        with pytest.raises(RuleRejectedError):
            await execute(sc, "complete-process-step", FAB, {}, "PS-7132")

    async def test_only_fab_may_complete(self, sc):
        from ontogeny.errors import PolicyDeniedError

        with pytest.raises(PolicyDeniedError):
            await execute(sc, "complete-process-step", PRODUCT, {}, "PS-7212")


class TestQuality:
    async def test_record_pass_wafer_test(self, sc):
        rev = await execute(
            sc,
            "record-wafer-test",
            FAB,
            {
                "lot_id": "LOT-2417",
                "tested_qty": 40,
                "defect_qty": 1,
                "result": "PASS",
                "tester": "cp-eng-02",
            },
        )
        wt_id = rev.object_id
        assert wt_id.startswith("WT-")
        wt = await get(sc, "wafer-test", wt_id)
        assert wt["result"] == "PASS" and wt["tested_at"] is not None
        assert wt["lot_id"] == "LOT-2417" and wt["defect_qty"] == 1

    async def test_defects_cannot_exceed_tested(self, sc):
        from ontogeny.errors import RuleRejectedError

        with pytest.raises(RuleRejectedError):
            await execute(
                sc,
                "record-wafer-test",
                FAB,
                {
                    "lot_id": "LOT-2417",
                    "tested_qty": 40,
                    "defect_qty": 41,
                    "result": "FAIL",
                    "tester": "cp-eng-02",
                },
            )

    async def test_only_fab_may_record(self, sc):
        from ontogeny.errors import PolicyDeniedError

        with pytest.raises(PolicyDeniedError):
            await execute(
                sc,
                "record-wafer-test",
                CQE,
                {
                    "lot_id": "LOT-2417",
                    "tested_qty": 1,
                    "defect_qty": 0,
                    "result": "PASS",
                },
            )


class TestFunctions:
    async def test_analyze_yield_loss_reports_candidates(self, sc):
        fn = sc.compiled.functions["analyze-yield-loss"]
        async with sc.sessionmaker() as s:
            out = await sc.sandbox.run(s, fn, {"test_id": "WT-501"})
        assert out["found"] is True
        assert out["lot_id"] == "LOT-2417" and out["lot_status"] == "COMPLETE"
        assert out["loss"] == pytest.approx(0.18)  # 36 defects on 200 tested units
        assert out["recommended_action"] == "HOLD"
        by_class = {c["root_cause_class"]: c["confidence"] for c in out["candidates"]}
        assert by_class == {"PROCESS": 0.82, "DESIGN": 0.55}

    async def test_requirement_impact_walks_the_whole_chain(self, sc):
        fn = sc.compiled.functions["requirement-impact"]
        async with sc.sessionmaker() as s:
            out = await sc.sandbox.run(s, fn, {"requirement_id": "REQ-101"})
        assert out["found"] is True
        assert {m["module_id"] for m in out["modules"]} == {"DSG-201", "DSG-211"}
        assert {v["version_id"] for v in out["versions"]} == {"TO-A0", "TO-A1"}
        assert out["at_risk_lots"] == ["LOT-2419"]
        assert out["at_risk_wafers"] == 25

    async def test_yield_pareto_ranks_the_worst_lot_first(self, sc):
        fn = sc.compiled.functions["yield-pareto"]
        async with sc.sessionmaker() as s:
            out = await sc.sandbox.run(s, fn, {})
        assert out["lots_with_tests"] == 3
        top = out["ranking"][0]
        assert top["lot_id"] == "LOT-2417"  # 18% loss, the biggest bucket
        assert top["loss"] == pytest.approx(0.18)
        assert "Etch@EQ-07" in top["route"]

    async def test_function_capability_is_scoped(self, sc):
        from ontogeny.errors import SandboxError

        fn = sc.compiled.functions["analyze-yield-loss"]
        original = fn.spec.capabilities
        fn.spec.capabilities = []  # strip grants
        try:
            async with sc.sessionmaker() as s:
                with pytest.raises(SandboxError, match="capability denied"):
                    await sc.sandbox.run(s, fn, {"test_id": "WT-501"})
        finally:
            fn.spec.capabilities = original


class TestMaskingAndAudit:
    async def test_internal_marking_is_masked(self, sc):
        async with sc.sessionmaker() as s:
            obj = await sc.query.get(s, "tapeout-version", "TO-A0", OUTSIDER)
        assert obj["mask_cost"] == "__masked__"
        async with sc.sessionmaker() as s:
            obj = await sc.query.get(s, "tapeout-version", "TO-A0", {**OUTSIDER, "markings": ["internal"]})
        assert obj["mask_cost"] == pytest.approx(1850000.0)

    async def test_revision_trail_records_rejections(self, sc):
        from ontogeny.errors import RuleRejectedError

        await execute(sc, "tapeout", PRODUCT, {}, "TO-A1")
        with pytest.raises(RuleRejectedError):
            await execute(sc, "tapeout", PRODUCT, {}, "TO-A1")
        async with sc.sessionmaker() as s:
            from sqlalchemy import select

            from ontogeny.action.models import RevisionRow

            rows = (
                (await s.execute(select(RevisionRow).where(RevisionRow.object_id == "TO-A1").order_by(RevisionRow.id)))
                .scalars()
                .all()
            )
        assert [r.outcome for r in rows] == ["executed", "rejected_rule"]


class TestEvolutionOnDomainPackage:
    async def test_t0_promotion_keeps_package_valid(self, sc):
        """RSI must be able to improve this package without breaking it."""
        from ontogeny.core import validate as v
        from ontogeny.evolve import Promoter, ProposalRow, apply_mutations

        pkg = load_package(sc.package_root)
        mutated = apply_mutations(
            pkg,
            [
                {
                    "mutation": "add-optional-property",
                    "object": "wafer-lot",
                    "prop": "shift-pattern",
                    "type": "string",
                }
            ],
        )
        rep = v(mutated)
        assert rep.ok, [f"{i.code}:{i.message}" for i in rep.issues if i.severity == "error"]
        async with sc.sessionmaker() as s:
            proposal = ProposalRow(
                gap_kind="add-optional-property",
                rationale="t",
                diff=[
                    {
                        "mutation": "add-optional-property",
                        "object": "wafer-lot",
                        "prop": "shift-pattern",
                        "type": "string",
                    }
                ],
            )
            s.add(proposal)
            await s.flush()
            result = await Promoter(sc.settings, sc.registry).promote(
                s, proposal, sc.package_root, eval_report={"passed": True, "suites": {"flow": {"passed": True}}}
            )
            await s.commit()
        assert result["status"] == "promoted"
