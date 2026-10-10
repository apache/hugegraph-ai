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
"""Domain example, system level: package integrity plus the full
plan -> release -> produce -> inspect execution chain, and every cross-cutting
capability the golden package must keep demonstrating: masking, derived
properties, audit with rejections, sandboxed functions, eval suites,
projections and evolution promotion.

The old richer system fixture also demoed maintenance and procurement chains
and llm/http capability functions; product-manufacturing does not model those,
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

PLANNER = {"id": "u-planner", "Role": ["planner"], "site": "plant-north"}
OPERATOR = {"id": "u-op", "Role": ["operator"], "site": "plant-north"}
INSPECTOR = {"id": "u-qi", "Role": ["quality"], "site": "plant-north"}
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
        for table in ("products", "materials", "boms", "work_centers",
                      "production_orders", "operations", "quality_inspections"):
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


SYSTEM = {"id": "test-runner", "Role": ["planner"], "markings": ["internal"]}


async def get(sc, object_type, obj_id):
    """Read through the query service: derived properties are assembled there."""
    async with sc.sessionmaker() as s:
        return await sc.query.get(s, object_type, obj_id, SYSTEM)


class TestSyncCoverage:
    async def test_every_object_type_syncs(self, sc):
        async with sc.sessionmaker() as s:
            for name in sc.compiled.objects:
                rows, total = await sc.repo.query(s, name, limit=1)
                assert total > 0, f"{name} synced no rows"

    async def test_derived_properties_compute(self, sc):
        po = await get(sc, "production-order", "PO-1001")
        assert po["release_lag_h"] == pytest.approx(24.0)  # released one day after creation
        po = await get(sc, "production-order", "PO-1002")
        assert po["release_lag_h"] is None  # not released yet: nothing to derive from

    async def test_fk_links_traverse(self, sc):
        async with sc.sessionmaker() as s:
            linked = await sc.repo.fk_linked_ids(s, "production-order-product", "P-100", from_source=True)
        assert "PO-1001" in linked
        assert "PO-1004" in linked


class TestPlanToRelease:
    async def test_create_and_release_production_order(self, sc):
        rev = await execute(sc, "create-production-order", PLANNER, {
            "product_id": "P-100", "qty": 10, "priority": "NORMAL",
        })
        pid = rev.object_id
        assert pid.startswith("PO-")

        po = await get(sc, "production-order", pid)
        assert po["status"] == "PLANNED" and po["qty"] == 10

        await execute(sc, "release-production-order", PLANNER, {}, pid)
        po = await get(sc, "production-order", pid)
        assert po["status"] == "RELEASED" and po["released_at"] is not None

        from ontogeny.errors import RuleRejectedError

        with pytest.raises(RuleRejectedError):
            await execute(sc, "release-production-order", PLANNER, {}, pid)

    async def test_create_requires_planner_role(self, sc):
        from ontogeny.errors import PolicyDeniedError

        with pytest.raises(PolicyDeniedError):
            await execute(sc, "create-production-order", OPERATOR,
                          {"product_id": "P-100", "qty": 1})

    async def test_release_requires_planner_role(self, sc):
        """The Cedar `when` clause gates planners to PLANNED orders; operators
        hold no release permit at all -- policy denies before rules matter."""
        from ontogeny.errors import PolicyDeniedError

        with pytest.raises(PolicyDeniedError):
            await execute(sc, "release-production-order", OPERATOR, {}, "PO-1002")


class TestShopFloor:
    async def test_complete_operation_moves_and_stamps(self, sc):
        await execute(sc, "complete-operation", OPERATOR,
                      {"note": "Plate cutting finished"}, "OP-2001")
        op = await get(sc, "operation", "OP-2001")
        assert op["status"] == "COMPLETED" and op["completed_at"] is not None

        from ontogeny.errors import RuleRejectedError

        with pytest.raises(RuleRejectedError):
            await execute(sc, "complete-operation", OPERATOR, {}, "OP-2001")

    async def test_only_operators_may_complete(self, sc):
        from ontogeny.errors import PolicyDeniedError

        with pytest.raises(PolicyDeniedError):
            await execute(sc, "complete-operation", PLANNER, {}, "OP-2002")


class TestQuality:
    async def test_record_pass_inspection(self, sc):
        rev = await execute(sc, "record-inspection", INSPECTOR, {
            "order_id": "PO-1003", "inspected_qty": 40, "defect_qty": 1,
            "result": "PASS", "inspector": "qa-eng-02",
        })
        qi_id = rev.object_id
        assert qi_id.startswith("QI-")
        qi = await get(sc, "quality-inspection", qi_id)
        assert qi["result"] == "PASS" and qi["inspected_at"] is not None
        assert qi["order_id"] == "PO-1003" and qi["defect_qty"] == 1

    async def test_defects_cannot_exceed_inspected(self, sc):
        from ontogeny.errors import RuleRejectedError

        with pytest.raises(RuleRejectedError):
            await execute(sc, "record-inspection", INSPECTOR, {
                "order_id": "PO-1003", "inspected_qty": 40, "defect_qty": 41,
                "result": "FAIL", "inspector": "qa-eng-02",
            })

    async def test_only_quality_may_record(self, sc):
        from ontogeny.errors import PolicyDeniedError

        with pytest.raises(PolicyDeniedError):
            await execute(sc, "record-inspection", OPERATOR, {
                "order_id": "PO-1003", "inspected_qty": 1, "defect_qty": 0,
                "result": "PASS",
            })


class TestFunctions:
    async def test_material_availability_reports_shortage(self, sc):
        fn = sc.compiled.functions["material-availability"]
        async with sc.sessionmaker() as s:
            out = await sc.sandbox.run(s, fn, {"product_id": "P-100", "qty": 5})
        assert out["bom_lines"] == 3
        assert out["ready"] is False
        short = {x["material_id"]: x for x in out["shortage"]}
        assert set(short) == {"M-104"}  # bearings: 21 required incl. scrap, 9 on hand
        assert short["M-104"]["required"] == 21
        assert short["M-104"]["on_hand"] == 9
        assert short["M-104"]["gap"] == 12

    async def test_order_yield_summarises_quality_and_routing(self, sc):
        fn = sc.compiled.functions["order-yield"]
        async with sc.sessionmaker() as s:
            out = await sc.sandbox.run(s, fn, {"order_id": "PO-1004"})
        assert out["ok"] is True
        assert out["inspected_qty"] == 10 and out["defect_qty"] == 0
        assert out["pass_rate"] == pytest.approx(1.0)
        assert out["operations_total"] == 2 and out["operations_completed"] == 2
        assert out["routing_complete"] is True

    async def test_capacity_check(self, sc):
        fn = sc.compiled.functions["capacity-check"]
        async with sc.sessionmaker() as s:
            out = await sc.sandbox.run(s, fn, {"work_center_id": "WC-01", "qty": 10})
        assert out["daily_capacity"] == 800  # 400 per shift x 2 shifts
        assert out["committed_qty"] == 170   # open orders: 20 + 50 + 100
        assert out["ok"] is True

    async def test_function_capability_is_scoped(self, sc):
        from ontogeny.errors import SandboxError

        fn = sc.compiled.functions["material-availability"]
        original = fn.spec.capabilities
        fn.spec.capabilities = []  # strip grants
        try:
            async with sc.sessionmaker() as s:
                with pytest.raises(SandboxError, match="capability denied"):
                    await sc.sandbox.run(s, fn, {"product_id": "P-100", "qty": 1})
        finally:
            fn.spec.capabilities = original


class TestMaskingAndAudit:
    async def test_internal_marking_is_masked(self, sc):
        async with sc.sessionmaker() as s:
            obj = await sc.query.get(s, "material", "M-101", OUTSIDER)
        assert obj["unit_cost"] == "__masked__"
        async with sc.sessionmaker() as s:
            obj = await sc.query.get(s, "material", "M-101", {**OUTSIDER, "markings": ["internal"]})
        assert obj["unit_cost"] == pytest.approx(210.0)

    async def test_revision_trail_records_rejections(self, sc):
        from ontogeny.errors import RuleRejectedError

        await execute(sc, "release-production-order", PLANNER, {}, "PO-1002")
        with pytest.raises(RuleRejectedError):
            await execute(sc, "release-production-order", PLANNER, {}, "PO-1002")
        async with sc.sessionmaker() as s:
            from sqlalchemy import select

            from ontogeny.action.models import RevisionRow

            rows = (await s.execute(
                select(RevisionRow).where(RevisionRow.object_id == "PO-1002").order_by(RevisionRow.id)
            )).scalars().all()
        assert [r.outcome for r in rows] == ["executed", "rejected_rule"]


class TestEvolutionOnDomainPackage:
    async def test_t0_promotion_keeps_package_valid(self, sc):
        """RSI must be able to improve this package without breaking it."""
        from ontogeny.core import validate as v
        from ontogeny.evolve import Promoter, ProposalRow, apply_mutations

        pkg = load_package(sc.package_root)
        mutated = apply_mutations(pkg, [{
            "mutation": "add-optional-property", "object": "production-order",
            "prop": "shift-pattern", "type": "string",
        }])
        rep = v(mutated)
        assert rep.ok, [f"{i.code}:{i.message}" for i in rep.issues if i.severity == "error"]
        async with sc.sessionmaker() as s:
            proposal = ProposalRow(gap_kind="add-optional-property", rationale="t",
                                   diff=[{"mutation": "add-optional-property",
                                          "object": "production-order", "prop": "shift-pattern",
                                          "type": "string"}])
            s.add(proposal)
            await s.flush()
            result = await Promoter(sc.settings, sc.registry).promote(
                s, proposal, sc.package_root, eval_report={"passed": True})
            await s.commit()
        assert result["status"] == "promoted"
