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

"""RSI loop: telemetry -> signals -> gaps -> proposals -> eval (replay) ->
tiered promotion with budget + governance baseline enforcement."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from ontogeny.action import ActionRuntime
from ontogeny.config import Settings
from ontogeny.core import load_package
from ontogeny.db import init_schema, make_engine, make_sessionmaker
from ontogeny.engine import QueryService
from ontogeny.errors import BaselineViolationError, BudgetExceededError
from ontogeny.evolve import EvolveSignalRow, Promoter, ProposalRow, apply_mutations
from ontogeny.evolve.diagnoser import diagnose, enum_widen_gap
from ontogeny.evolve.evalrunner import EvalRunner
from ontogeny.evolve.proposer import DecidingProposer, HeuristicProposer
from ontogeny.policy import PolicyEngine
from ontogeny.registry import RegistryService
from ontogeny.stores import ObjectRepository, SyncEngine
from ontogeny.stores.sources import make_source
from ontogeny.telemetry import TelemetryService

FAB = {"id": "u-fab", "Role": {"fab"}, "site": "fab-site-a"}

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
    "fmea-note",
)


@pytest_asyncio.fixture()
async def env(golden_pkg_path, tmp_path):
    # writable copy of the golden package (promoter writes branches/files)
    pkg_root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, pkg_root)

    src = tmp_path / "erp.db"
    # the package owns its source data: execute its own seed SQL (same path the
    # demo bootstrap uses), so tests always agree with the shipped example
    from ontogeny.demo.bootstrap import seed_from_package

    seed_from_package(golden_pkg_path, src, force=True)

    settings = Settings(
        dev_auth=True,
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}", "FAB_WEBHOOK": "https://fab-portal.example.test/hook"},
    )
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    maker = make_sessionmaker(engine)
    registry = RegistryService()
    pkg = load_package(pkg_root)
    async with maker() as s:
        compiled = await registry.publish(s, pkg)
        await s.commit()
    repo = ObjectRepository(compiled)
    sync = SyncEngine(
        compiled, settings, repo, lambda st: make_source(st, settings.resolve_env_ref(st.spec.connection))
    )
    async with maker() as s:
        await repo.ensure(s)
        for t in OBJECT_TYPES:
            await sync.sync(s, t)
        await s.commit()
    policy = PolicyEngine(compiled)
    runtime = ActionRuntime(compiled, repo, policy, settings)
    query = QueryService(compiled, repo, policy)
    telemetry = TelemetryService(compiled)
    runner = EvalRunner(repo, query)
    promoter = Promoter(settings, registry)
    yield {
        "maker": maker,
        "compiled": compiled,
        "repo": repo,
        "runtime": runtime,
        "query": query,
        "telemetry": telemetry,
        "runner": runner,
        "promoter": promoter,
        "pkg_root": str(pkg_root),
        "registry": registry,
    }
    await engine.dispose()


class TestTelemetry:
    async def test_signals_from_telemetry(self, env):
        tel = env["telemetry"]
        async with env["maker"]() as s:
            for _ in range(8):
                await tel.record_query(
                    s,
                    "wafer-lot",
                    {"id": "x"},
                    filt={"field": "shift", "op": "eq", "value": "DAY"},
                    latency_ms=3.0,
                    n_results=0,
                )
            await tel.record_query(s, "wafer-lot", {"id": "x"}, None, 3.0, 5)
            created = await tel.aggregate_signals(s)
            await s.commit()
            sigs = (await s.execute(select(EvolveSignalRow))).scalars().all()
        kinds = {x["kind"] for x in created}
        assert "empty_query_rate" in kinds
        assert "unmapped_filter_field" in kinds
        assert any(s.kind == "unmapped_filter_field" and s.evidence["field"] == "shift" for s in sigs)

    async def test_aggregate_is_idempotent_within_window(self, env):
        """The window is rolling, so without dedup every run re-detects the same
        finding and the feed fills with identical rows (observed: 7 copies of
        one empty-query finding after a few clicks)."""
        tel = env["telemetry"]
        async with env["maker"]() as s:
            for _ in range(6):
                await tel.record_query(
                    s,
                    "wafer-lot",
                    {"id": "x"},
                    filt={"field": "shift", "op": "eq", "value": "DAY"},
                    latency_ms=2.0,
                    n_results=3,
                )
            await s.commit()
            first = await tel.aggregate_signals(s)
            await s.commit()
            second = await tel.aggregate_signals(s)
            await s.commit()
        assert {x["kind"] for x in first} >= {"unmapped_filter_field"}
        assert second == []


class TestDiagnoseAndPropose:
    async def test_gap_and_proposal(self, env):
        tel = env["telemetry"]
        async with env["maker"]() as s:
            for _ in range(6):
                await tel.record_query(
                    s,
                    "wafer-lot",
                    {"id": "x"},
                    filt={"field": "shift", "op": "eq", "value": "DAY"},
                    latency_ms=2.0,
                    n_results=3,
                )
            await tel.aggregate_signals(s)
            await s.commit()
            sigs = (await s.execute(select(EvolveSignalRow))).scalars().all()
        gaps = diagnose(list(sigs), env["compiled"])
        actionable = [g for g in gaps if not g.get("informational")]
        assert actionable and actionable[0]["kind"] == "add-optional-property"
        assert actionable[0]["prop"] == "shift"

        proposal = HeuristicProposer().propose(actionable[0])
        assert proposal["mutations"] == [
            {"mutation": "add-optional-property", "object": "wafer-lot", "prop": "shift", "type": "string"}
        ]

    def test_enum_widen_gap(self, env):
        gap = enum_widen_gap("wafer-lot", "status", "BLOCKED", env["compiled"])
        assert gap and gap["kind"] == "enum-widen" and gap["value"] == "BLOCKED"
        assert enum_widen_gap("wafer-lot", "qty_wafers", "x", env["compiled"]) is None


class TestEvalRunner:
    async def _complete_running_step(self, session, rt):
        """Execute one real completion (PS-7132) for the suite to replay.

        The shipped suite's replay case is complete-process-step: without a
        real executed revision there is nothing to time-travel over, and the
        RUNNING step PS-7132 is the seeded decision the candidate must agree
        with (and reject on replay against the post-state).
        """
        return await rt.execute(session, "complete-process-step", FAB, {"note": "Etch finished on EQ-07"}, "PS-7132")

    async def test_replay_matches_history_and_guards_double_completion(self, env):
        rt = env["runtime"]
        async with env["maker"]() as s:
            await self._complete_running_step(s, rt)
            await s.commit()
        suite = env["compiled"].eval_suites["lifecycle-flow-suite"]
        async with env["maker"]() as s:
            report = await env["runner"].run(s, suite)
        replay_cases = [c for c in report["cases"] if c["kind"] == "replay"]
        assert replay_cases and replay_cases[0]["ok"] is True
        assert replay_cases[0]["replays"] >= 1
        assert replay_cases[0]["after_state_rejections"] >= 1
        # overall suite green (queries included)
        assert report["passed"] is True

    async def test_replay_sees_derived_properties_on_both_revision_states(self, env):
        from ontogeny.core.models import PropertyDef, Rule

        compiled = env["compiled"]
        compiled.objects["process-step"].spec.properties["blocked"] = PropertyDef(
            type="boolean", derived="target.status != 'RUNNING'"
        )
        compiled.actions["complete-process-step"].spec.rules = [Rule(expr="target.blocked != true")]
        async with env["maker"]() as s:
            revision = await self._complete_running_step(s, env["runtime"])
            await s.commit()
            assert revision.before["blocked"] is False
            assert revision.after["blocked"] is True
        async with env["maker"]() as s:
            report = await env["runner"].run(s, compiled.eval_suites["lifecycle-flow-suite"])
        replay = next(c for c in report["cases"] if c["kind"] == "replay")
        assert replay["replays"] == 1
        assert replay["outcome_matches"] == 1
        assert replay["after_state_rejections"] == 1
        assert replay["ok"] is True

    async def test_replay_ignores_unreplayable_revisions(self, env):
        """Revisions left over from an earlier package binding (the action since
        retargeted, so the object does not exist under the current target type)
        are not evidence: they must stay out of the replay denominator. Counting
        them made `after_rejected == total` impossible and the suite red
        forever after any retargeting."""
        import datetime as _dt

        from ontogeny.action.models import RevisionRow

        rt = env["runtime"]
        async with env["maker"]() as s:
            await self._complete_running_step(s, rt)
            s.add(
                RevisionRow(
                    action="complete-process-step",
                    object_type="process-step",
                    object_id="GHOST",
                    outcome="executed",
                    principal="u-fab",
                    params={},
                    created_at=_dt.datetime.now(_dt.UTC),
                )
            )
            await s.commit()
        suite = env["compiled"].eval_suites["lifecycle-flow-suite"]
        async with env["maker"]() as s:
            report = await env["runner"].run(s, suite)
        replay = next(c for c in report["cases"] if c["kind"] == "replay")
        assert replay["replays"] == 1  # the ghost is excluded, not counted
        assert replay["ok"] is True and report["passed"] is True

    async def test_replay_catches_bad_candidate(self, env):
        """A candidate that drops the not-already-completed guard must fail eval."""
        import copy

        rt = env["runtime"]
        async with env["maker"]() as s:
            await self._complete_running_step(s, rt)
            await s.commit()
        pkg = load_package(env["pkg_root"])
        bad = copy.deepcopy(pkg)
        bad.find("Action", "complete-process-step").spec.rules = []  # guard removed
        suite = env["compiled"].eval_suites["lifecycle-flow-suite"]
        async with env["maker"]() as s:
            report = await env["runner"].run(s, suite, candidate_pkg=bad)
        replay = next(c for c in report["cases"] if c["kind"] == "replay")
        # rules always pass -> after-state replay also passes -> double-completion no longer caught
        assert replay["after_state_rejections"] == 0
        assert replay["ok"] is False and report["passed"] is False


class TestPromoter:
    async def _proposal(self, session, mutations, gap_kind="add-optional-property", rationale="test"):
        row = ProposalRow(gap_kind=gap_kind, diff=mutations, rationale=rationale)
        session.add(row)
        await session.flush()
        return row

    async def test_baseline_violation_never_automates(self, env):
        async with env["maker"]() as s:
            proposal = await self._proposal(s, [{"mutation": "policy-loosen", "target": "complete-process-step"}])
            with pytest.raises(BaselineViolationError):
                await env["promoter"].promote(s, proposal, env["pkg_root"])
            await s.commit()
            assert proposal.status == "awaiting_human"

    async def test_t0_promotes_within_budget(self, env):
        mutations = [{"mutation": "add-optional-property", "object": "wafer-lot", "prop": "expedite", "type": "string"}]
        async with env["maker"]() as s:
            proposal = await self._proposal(s, mutations)
            result = await env["promoter"].promote(
                s,
                proposal,
                env["pkg_root"],
                eval_report={"passed": True, "suites": {"flow": {"passed": True}}},
            )
            await s.commit()
        assert result["status"] == "promoted" and result["tier"] == "t0-auto-merge"
        assert result["budget_used"] == 1
        # the mutated package is live in the registry
        async with env["maker"]() as s:
            compiled = await env["registry"].load_latest(s)
        assert "expedite" in compiled.objects["wafer-lot"].spec.properties

    async def test_t0_budget_exhaustion(self, env):
        mutations = [{"mutation": "add-optional-property", "object": "wafer-lot", "prop": "extra-1", "type": "string"}]
        async with env["maker"]() as s:
            # drain the weekly budget (cap is 10 in the example policy)
            for i in range(10):
                p = await self._proposal(
                    s,
                    [
                        {
                            "mutation": "add-optional-property",
                            "object": "wafer-lot",
                            "prop": f"x-{i}",
                            "type": "string",
                        }
                    ],
                )
                await env["promoter"].promote(
                    s,
                    p,
                    env["pkg_root"],
                    eval_report={"passed": True, "suites": {"flow": {"passed": True}}},
                )
            p11 = await self._proposal(s, mutations)
            with pytest.raises(BudgetExceededError):
                await env["promoter"].promote(
                    s,
                    p11,
                    env["pkg_root"],
                    eval_report={"passed": True, "suites": {"flow": {"passed": True}}},
                )
            await s.commit()

    async def test_t0_blocked_when_eval_red(self, env):
        async with env["maker"]() as s:
            proposal = await self._proposal(
                s, [{"mutation": "add-optional-property", "object": "wafer-lot", "prop": "y", "type": "string"}]
            )
            result = await env["promoter"].promote(s, proposal, env["pkg_root"], eval_report={"passed": False})
            await s.commit()
        assert result["status"] == "rejected"

    async def test_t1_creates_validated_branch(self, env):
        # rule-change is a T2 mutation; unknown kind falls to T1 -> both are human gates
        async with env["maker"]() as s:
            proposal = await self._proposal(
                s, [{"mutation": "adjust-rule-threshold", "action": "complete-process-step"}], gap_kind="rule-drift"
            )
            result = await env["promoter"].promote(s, proposal, env["pkg_root"])
            await s.commit()
        assert result["status"] == "awaiting_human"
        assert result["tier"] == "t1-pr"
        branch_pkg = load_package(result["branch"])
        from ontogeny.core import validate as v

        assert v(branch_pkg).ok

    async def test_enum_widen_apply(self, env):
        pkg = load_package(env["pkg_root"])
        mutated = apply_mutations(
            pkg, [{"mutation": "enum-widen", "object": "wafer-lot", "prop": "status", "value": "BLOCKED"}]
        )
        assert "BLOCKED" in mutated.find("ObjectType", "wafer-lot").spec.properties["status"].type
        # idempotent
        again = apply_mutations(
            mutated, [{"mutation": "enum-widen", "object": "wafer-lot", "prop": "status", "value": "BLOCKED"}]
        )
        assert again.find("ObjectType", "wafer-lot").spec.properties["status"].type.count("BLOCKED") == 1


class _FakeLLM:
    """Deterministic stand-in for the ontogeny.llm ChatClient contract."""

    model = "fake"

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        return {"content": self.content}

    async def health(self):
        return {"ok": True}

    def scoped(self, model):
        return self


class _BoomLLM(_FakeLLM):
    async def chat(self, messages, **kw):
        self.calls += 1
        raise RuntimeError("model unreachable")


class TestDecidingProposer:
    """The LLM decides inside a rule-bounded catalog; rules validate and
    fall back. This is the 'controlled' in 'LLM-controlled decisions'."""

    async def test_llm_decides_type_and_business_metadata(self, env):
        llm = _FakeLLM(
            json.dumps(
                {
                    "act": True,
                    "analysis": "lots are filtered by fab shift but the field is not modeled",
                    "mutations": [
                        {
                            "mutation": "add-optional-property",
                            "object": "wafer-lot",
                            "prop": "shift",
                            "type": "enum[DAY, NIGHT]",
                            "display": "Shift",
                            "description": "Fab shift this lot belongs to",
                        }
                    ],
                    "rationale": "filter field shift recurs and is semantically a shift enum",
                }
            )
        )
        prop = DecidingProposer(llm)
        gap = {
            "kind": "add-optional-property",
            "object": "wafer-lot",
            "prop": "shift",
            "signal_id": 1,
            "rationale": "filter field 'shift' used 6x",
        }
        out = await prop.propose(gap, env["compiled"])
        assert out["origin"] == "llm"
        m = out["mutations"][0]
        # the heuristic would have hardcoded type=string and display=prop: the
        # model's actual decisions survive
        assert m["type"] == "enum[DAY, NIGHT]"
        assert m["display"] == "Shift"
        assert m["description"] == "Fab shift this lot belongs to"
        assert prop.stats["llm_decided"] == 1

    async def test_llm_declines_informational_signal(self, env):
        """empty_query_rate is informational: judgment says no mutation, and
        'no' is a valid answer, not a failure."""
        llm = _FakeLLM(
            json.dumps(
                {"act": False, "analysis": "empty results are a usage problem", "mutations": [], "rationale": ""}
            )
        )
        prop = DecidingProposer(llm)
        gap = {
            "kind": "empty_query_rate",
            "evidence": {"object_type": "wafer-lot", "rate": 0.5},
            "signal_id": 2,
            "informational": True,
        }
        assert await prop.propose(gap, env["compiled"]) is None
        assert prop.stats["llm_declined"] == 1

    async def test_llm_decline_of_concrete_gap_falls_back(self, env):
        """A rules-classified schema defect (unmapped field) cannot be vetoed by
        the model — its decision space there is HOW, not WHETHER. The decline
        is counted, and the deterministic heuristic answers for the gap."""
        llm = _FakeLLM(json.dumps({"act": False, "analysis": "not urgent", "mutations": [], "rationale": ""}))
        prop = DecidingProposer(llm)
        gap = {"kind": "add-optional-property", "object": "wafer-lot", "prop": "shift", "signal_id": 21}
        out = await prop.propose(gap, env["compiled"])
        assert out["origin"] == "heuristic" and out["mutations"][0]["prop"] == "shift"
        assert prop.stats["llm_declined"] == 1

    async def test_llm_failure_falls_back_to_heuristic(self, env):
        prop = DecidingProposer(_BoomLLM(""))
        gap = {
            "kind": "add-optional-property",
            "object": "wafer-lot",
            "prop": "shift",
            "signal_id": 3,
            "rationale": "used 6x",
        }
        out = await prop.propose(gap, env["compiled"])
        assert out["origin"] == "heuristic" and out["mutations"][0]["type"] == "string"
        assert prop.stats["fallback"] == 1

    async def test_llm_decision_outside_catalog_is_rejected(self, env):
        # inventing a mutation kind the applier cannot apply
        llm = _FakeLLM(
            json.dumps(
                {
                    "act": True,
                    "mutations": [{"mutation": "drop-object", "object": "wafer-lot"}],
                    "rationale": "x",
                }
            )
        )
        prop = DecidingProposer(llm)
        gap = {"kind": "add-optional-property", "object": "wafer-lot", "prop": "shift", "signal_id": 4}
        out = await prop.propose(gap, env["compiled"])
        assert out["origin"] == "heuristic"
        assert prop.stats["llm_rejected"] == 1

    async def test_llm_hallucinating_an_existing_prop_falls_back(self, env):
        """The model names a property that already exists; the rule layer
        rejects the decision, and the heuristic template answers for the gap's
        REAL field (the unmapped one the signal was about)."""
        llm = _FakeLLM(
            json.dumps(
                {
                    "act": True,
                    "mutations": [
                        {
                            "mutation": "add-optional-property",
                            "object": "wafer-lot",
                            "prop": "status",
                            "type": "string",
                        }
                    ],
                    "rationale": "x",
                }
            )
        )
        prop = DecidingProposer(llm)
        gap = {"kind": "add-optional-property", "object": "wafer-lot", "prop": "shift", "signal_id": 5}
        out = await prop.propose(gap, env["compiled"])
        assert out["origin"] == "heuristic"
        assert out["mutations"][0]["prop"] == "shift"  # the signal's field, not the hallucination
        assert prop.stats["llm_rejected"] == 1

    async def test_llm_type_must_parse_in_the_dsl(self, env):
        llm = _FakeLLM(
            json.dumps(
                {
                    "act": True,
                    "mutations": [
                        {
                            "mutation": "add-optional-property",
                            "object": "wafer-lot",
                            "prop": "shift",
                            "type": "not a type!",
                        }
                    ],
                    "rationale": "x",
                }
            )
        )
        prop = DecidingProposer(llm)
        gap = {"kind": "add-optional-property", "object": "wafer-lot", "prop": "shift", "signal_id": 6}
        out = await prop.propose(gap, env["compiled"])
        assert out["origin"] == "heuristic"  # invalid type -> rule layer -> fallback

    async def test_llm_enum_widen_validated_against_live_enum(self, env):
        ok = _FakeLLM(
            json.dumps(
                {
                    "act": True,
                    "mutations": [
                        {"mutation": "enum-widen", "object": "wafer-lot", "prop": "status", "value": "BLOCKED"}
                    ],
                    "rationale": "the source system produced a new status",
                }
            )
        )
        dup = _FakeLLM(
            json.dumps(
                {
                    "act": True,
                    "mutations": [
                        {"mutation": "enum-widen", "object": "wafer-lot", "prop": "status", "value": "ON_HOLD"}
                    ],
                    "rationale": "x",
                }
            )
        )
        gap = {"kind": "enum-widen", "object": "wafer-lot", "prop": "status", "signal_id": 7}
        good = await DecidingProposer(ok).propose(gap, env["compiled"])
        assert good["origin"] == "llm" and good["mutations"][0]["value"] == "BLOCKED"
        assert await DecidingProposer(dup).propose(gap, env["compiled"]) is None  # member exists

    async def test_none_client_is_pure_heuristic(self, env):
        prop = DecidingProposer(None)
        gap = {"kind": "add-optional-property", "object": "wafer-lot", "prop": "shift", "signal_id": 8}
        out = await prop.propose(gap, env["compiled"])
        assert out["origin"] == "heuristic"

    async def test_llm_metadata_promotes_all_the_way(self, env):
        """The model's display/description survive promotion and land in the
        package (they surface in every table header via the meta export)."""
        from ontogeny.core import load_package
        from ontogeny.evolve.promoter import apply_mutations

        llm = _FakeLLM(
            json.dumps(
                {
                    "act": True,
                    "mutations": [
                        {
                            "mutation": "add-optional-property",
                            "object": "wafer-lot",
                            "prop": "shift",
                            "type": "enum[DAY, NIGHT]",
                            "display": "Shift",
                            "description": "Fab shift this lot belongs to",
                        }
                    ],
                    "rationale": "shift recurs as a filter; semantically a shift enum",
                }
            )
        )
        prop = DecidingProposer(llm)
        out = await prop.propose(
            {"kind": "add-optional-property", "object": "wafer-lot", "prop": "shift", "signal_id": 9},
            env["compiled"],
        )
        mutated = apply_mutations(load_package(env["pkg_root"]), out["mutations"])
        pdef = mutated.find("ObjectType", "wafer-lot").spec.properties["shift"]
        assert pdef.display == "Shift"
        assert pdef.description == "Fab shift this lot belongs to"


class TestDirectionAKeepTheReasoning:
    """Direction A: the model's reasoning survives even when it DECLINES, and
    a rule-validated alternative rides along as a second candidate."""

    async def test_decline_keeps_analysis_and_validated_alternative(self, env):
        llm = _FakeLLM(
            json.dumps(
                {
                    "act": False,
                    "analysis": "urgency 与已有 priority 枚举语义重叠，加自由文本列是冗余",
                    "mutations": [],
                    "rationale": "urgency duplicates priority",
                    "alternative": {
                        "mutation": "enum-widen",
                        "object": "requirement",
                        "prop": "priority",
                        "value": "CRITICAL",
                    },
                }
            )
        )
        prop = DecidingProposer(llm)
        gap = {
            "kind": "add-optional-property",
            "object": "wafer-lot",
            "prop": "urgency",
            "signal_id": 7,
            "rationale": "filter field 'urgency' used 6x",
        }
        out = await prop.propose_full(gap, env["compiled"])
        # a concrete gap still gets the heuristic answer...
        assert out.proposal is not None and out.proposal["origin"] == "heuristic"
        # ...but the model's judgement is kept, not dropped on the floor
        assert out.declined and out.analysis
        assert out.alternative is not None
        assert out.alternative["origin"] == "llm"
        assert out.alternative["mutations"][0]["mutation"] == "enum-widen"
        assert out.alternative["mutations"][0]["value"] == "CRITICAL"

    async def test_alternative_outside_the_catalog_is_dropped(self, env):
        llm = _FakeLLM(
            json.dumps(
                {
                    "act": False,
                    "analysis": "no",
                    "mutations": [],
                    "rationale": "no",
                    "alternative": {
                        "mutation": "add-optional-property",
                        "object": "no-such-object",
                        "prop": "x",
                        "type": "string",
                    },
                }
            )
        )
        prop = DecidingProposer(llm)
        gap = {
            "kind": "add-optional-property",
            "object": "wafer-lot",
            "prop": "urgency",
            "signal_id": 8,
            "rationale": "r",
        }
        out = await prop.propose_full(gap, env["compiled"])
        assert out.alternative is None  # unknown object: outside the model's authority
        assert out.proposal is not None  # the heuristic answer still stands

    async def test_legacy_propose_door_unchanged(self, env):
        llm = _FakeLLM(json.dumps({"act": False, "analysis": "a", "mutations": [], "rationale": ""}))
        prop = DecidingProposer(llm)
        gap = {"kind": "empty_query_rate", "evidence": {}, "signal_id": 9, "informational": True}
        assert await prop.propose(gap, env["compiled"]) is None

    async def test_eval_runs_against_the_candidate(self, client):
        """B1: the eval route applies the diff to an in-memory copy, so the
        ladder judges the candidate's declared columns and action rules --
        not whichever schema happens to be live."""
        c, sc = client
        async with sc.sessionmaker() as s:
            row = ProposalRow(
                gap_kind="add-optional-property",
                diff=[
                    {
                        "mutation": "add-optional-property",
                        "object": "wafer-lot",
                        "prop": "urgency",
                        "type": "string",
                    }
                ],
                rationale="urgency recurs as a filter",
                origin="heuristic",
            )
            s.add(row)
            await s.commit()
            pid = row.id
        r = await c.post(f"/api/v1/evolve/proposals/{pid}/eval")
        assert r.status_code == 200
        assert r.json()["candidate_evaluated"] is True
        detail = (await c.get(f"/api/v1/evolve/proposals/{pid}")).json()
        assert detail["eval_report"]["candidate_evaluated"] is True
        # prove the candidate actually reached the runner: a probe case that
        # asserts a column ONLY the candidate declares is green on the
        # candidate and red against the live schema
        import copy as _copy

        from ontogeny.core.loader import load_package
        from ontogeny.evolve.evalrunner import EvalRunner
        from ontogeny.evolve.promoter import apply_mutations

        suite = sc.compiled.eval_suites.get("lifecycle-flow-suite")
        assert suite is not None
        probe = _copy.deepcopy(suite)
        case = _copy.deepcopy(probe.spec.queries[0])
        case.name = "urgency-declared-on-candidate"
        case.expect.columns = ["urgency"]
        case.expect.min_rows = None
        probe.spec.queries = [case]
        cand = apply_mutations(load_package(sc.package_root), row.diff)
        runner = EvalRunner(sc.repo, sc.query)
        async with sc.sessionmaker() as s:
            on_candidate = (await runner.run(s, probe, candidate_pkg=cand))["passed"]
            on_live = (await runner.run(s, probe))["passed"]
        assert on_candidate is True
        assert on_live is False

    async def test_eval_includes_new_candidate_regression_case(self, client):
        c, sc = client
        async with sc.sessionmaker() as s:
            row = ProposalRow(
                gap_kind="eval-case-synth",
                diff=[
                    {
                        "mutation": "eval-case-synth",
                        "suite": "lifecycle-flow-suite",
                        "case": {
                            "name": "candidate-must-fail",
                            "query": {"object": "wafer-lot", "filter": {"status": "NEVER_PRESENT"}},
                            "expect": {"columns": ["not_a_declared_column"]},
                        },
                    }
                ],
                rationale="candidate regression coverage",
            )
            s.add(row)
            await s.commit()
            pid = row.id
        response = await c.post(f"/api/v1/evolve/proposals/{pid}/eval")
        assert response.status_code == 200
        assert response.json() == {"passed": False, "candidate_evaluated": True}
        detail = (await c.get(f"/api/v1/evolve/proposals/{pid}")).json()
        cases = detail["eval_report"]["suites"]["lifecycle-flow-suite"]["cases"]
        case = next(case for case in cases if case.get("name") == "candidate-must-fail")
        assert case["ok"] is False
        assert case["missing_columns"] == ["not_a_declared_column"]
        assert all(
            case.name != "candidate-must-fail" for case in sc.compiled.eval_suites["lifecycle-flow-suite"].spec.queries
        )


class TestRuleTightenAndCaseSynth:
    """Direction C: the loop can now TIGHTEN (rules) and make the selection
    function STRICTER (eval cases) -- both bounded by construction and gated
    by the time-travel replay."""

    async def test_rule_tighten_appends_and_is_idempotent(self, env):
        from ontogeny.evolve.promoter import apply_mutations

        pkg = load_package(env["pkg_root"])
        before = len(pkg.find("Action", "complete-process-step").spec.rules)
        diff = [
            {
                "mutation": "rule-tighten",
                "action": "complete-process-step",
                "expr": "target.seq < 10000",
                "message": "单步序号过大",
            }
        ]
        once = apply_mutations(load_package(env["pkg_root"]), diff)
        assert len(once.find("Action", "complete-process-step").spec.rules) == before + 1
        twice = apply_mutations(once, diff)
        assert len(twice.find("Action", "complete-process-step").spec.rules) == before + 1

    async def test_rule_tighten_validated_against_live_catalog(self, env):
        from ontogeny.evolve.proposer import validate_llm_decision

        compiled = env["compiled"]
        ok = validate_llm_decision(
            {
                "mutations": [
                    {"mutation": "rule-tighten", "action": "complete-process-step", "expr": "target.seq < 10000"}
                ],
                "rationale": "cap step sequence",
            },
            None,
            compiled,
        )
        assert ok is not None and ok["mutations"][0]["action"] == "complete-process-step"
        # malformed expression -> dropped
        bad_expr = validate_llm_decision(
            {
                "mutations": [
                    {"mutation": "rule-tighten", "action": "complete-process-step", "expr": "target.seq >< 10000"}
                ],
                "rationale": "x",
            },
            None,
            compiled,
        )
        assert bad_expr is None
        unknown_root = validate_llm_decision(
            {
                "mutations": [
                    {"mutation": "rule-tighten", "action": "complete-process-step", "expr": "resource.seq < 10000"}
                ],
                "rationale": "x",
            },
            None,
            compiled,
        )
        assert bad_expr is None
        # unknown action -> dropped; duplicate expr -> dropped
        assert (
            validate_llm_decision(
                {
                    "mutations": [{"mutation": "rule-tighten", "action": "no-such-action", "expr": "true"}],
                    "rationale": "x",
                },
                None,
                compiled,
            )
            is None
        )
        assert unknown_root is None  # 'resource' is not a rule-context root
        dup = validate_llm_decision(
            {
                "mutations": [
                    {
                        "mutation": "rule-tighten",
                        "action": "complete-process-step",
                        "expr": "target.status != 'COMPLETED'",
                    }
                ],
                "rationale": "x",
            },
            None,
            compiled,
        )
        assert dup is None  # the shipped guard already says exactly this

    async def test_rule_tighten_classified_t2_and_gated_by_replay(self, env):
        """The decisive C test: a tighten that would have REJECTED a decision a
        human actually made turns the replay red (outcomes-match 1.0), and the
        T2 promote path refuses to proceed on a red eval report."""
        rt = env["runtime"]
        async with env["maker"]() as s:
            await TestEvalRunner._complete_running_step(self, s, rt)
            await s.commit()
        suite = env["compiled"].eval_suites["lifecycle-flow-suite"]

        async with env["maker"]() as s:
            green = await env["runner"].run(
                s,
                suite,
                candidate_pkg=apply_mutations(
                    load_package(env["pkg_root"]),
                    [
                        {
                            "mutation": "rule-tighten",
                            "action": "complete-process-step",
                            "expr": "target.status != 'CANCELLED'",
                        }
                    ],
                ),
            )
        async with env["maker"]() as s:
            red = await env["runner"].run(
                s,
                suite,
                candidate_pkg=apply_mutations(
                    load_package(env["pkg_root"]),
                    [{"mutation": "rule-tighten", "action": "complete-process-step", "expr": "target.seq > 0"}],
                ),
            )  # seq is always > 0, passes -- benign
        # a tighten that fights history: only QUEUED steps may be completed --
        # the human completed a RUNNING one, so the candidate rejects history
        async with env["maker"]() as s:
            red = await env["runner"].run(
                s,
                suite,
                candidate_pkg=apply_mutations(
                    load_package(env["pkg_root"]),
                    [
                        {
                            "mutation": "rule-tighten",
                            "action": "complete-process-step",
                            "expr": "target.status == 'QUEUED'",
                        }
                    ],
                ),
            )
        assert green["passed"] is True
        assert red["passed"] is False

        # and the promoter refuses a T2 promote on a red report
        prom = Promoter(Settings(dev_auth=True, env={"ERP_DSN": "sqlite+aiosqlite:///:memory:"}), env["registry"])
        async with env["maker"]() as s:
            row = ProposalRow(
                gap_kind="rule-tighten",
                diff=[
                    {
                        "mutation": "rule-tighten",
                        "action": "complete-process-step",
                        "expr": "target.status == 'QUEUED'",
                    }
                ],
                rationale="fights history",
            )
            s.add(row)
            await s.flush()
            out = await prom.promote(
                s, row, env["pkg_root"], eval_report={"passed": False, "suites": {"flow": {"passed": True}}}
            )
        assert out["status"] == "rejected" and "eval" in out["reason"]

    async def test_eval_case_synth_appends_and_dedupes(self, env):
        from ontogeny.evolve.promoter import apply_mutations

        diff = [
            {
                "mutation": "eval-case-synth",
                "suite": "lifecycle-flow-suite",
                "case": {
                    "name": "hot-filter-urgency",
                    "query": {"object": "wafer-lot", "filter": {"urgency": "HIGH"}, "limit": 50},
                    "expect": {"columns": ["lot_id"]},
                },
            }
        ]

        def suite_len(pkg):
            return len(pkg.find("EvalSuite", "lifecycle-flow-suite").spec.queries)

        before = suite_len(load_package(env["pkg_root"]))
        once = apply_mutations(load_package(env["pkg_root"]), diff)
        assert suite_len(once) == before + 1
        twice = apply_mutations(once, diff)
        assert suite_len(twice) == before + 1  # dedupe on object+filter

    async def test_eval_case_synth_validated_against_live_suite(self, env):
        from ontogeny.evolve.proposer import validate_llm_decision

        compiled = env["compiled"]
        ok = validate_llm_decision(
            {
                "mutations": [
                    {
                        "mutation": "eval-case-synth",
                        "suite": "lifecycle-flow-suite",
                        "case": {"name": "c", "query": {"object": "customer", "filter": {"region": "EU"}}},
                    }
                ],
                "rationale": "hot customer filter",
            },
            None,
            compiled,
        )
        assert ok is not None
        # unknown suite / unknown object / duplicate case -> dropped
        assert (
            validate_llm_decision(
                {
                    "mutations": [
                        {
                            "mutation": "eval-case-synth",
                            "suite": "no-such-suite",
                            "case": {"query": {"object": "customer"}},
                        }
                    ],
                    "rationale": "x",
                },
                None,
                compiled,
            )
            is None
        )
        assert (
            validate_llm_decision(
                {
                    "mutations": [
                        {
                            "mutation": "eval-case-synth",
                            "suite": "lifecycle-flow-suite",
                            "case": {"query": {"object": "no-such-object"}},
                        }
                    ],
                    "rationale": "x",
                },
                None,
                compiled,
            )
            is None
        )
        dup = validate_llm_decision(
            {
                "mutations": [
                    {
                        "mutation": "eval-case-synth",
                        "suite": "lifecycle-flow-suite",
                        "case": {"query": {"object": "wafer-lot", "filter": {"status": "RUNNING"}}},
                    }
                ],
                "rationale": "x",
            },
            None,
            compiled,
        )
        assert dup is None  # running-lots-exist already covers this exact filter


class TestDirectionD:
    """Direction D: per-domain sensitivity, new fitness signals (approval
    friction, slow queries, hot queries) and object-clustered diagnosis."""

    async def test_thresholds_are_configurable(self, env):
        tel = env["telemetry"]
        async with env["maker"]() as s:
            for _ in range(2):
                await tel.record_query(s, "wafer-lot", {"id": "u"}, {"urgency": "HIGH"}, 1.0, 3)
            await s.commit()
        async with env["maker"]() as s:
            sigs_default = await tel.aggregate_signals(s)
            assert not any(x["kind"] == "unmapped_filter_field" for x in sigs_default)  # default min is 5
        async with env["maker"]() as s:
            sigs = await tel.aggregate_signals(s, thresholds={"unmapped_filter_min": 2})
            assert any(x["kind"] == "unmapped_filter_field" for x in sigs)

    async def test_approval_reject_rate_signal(self, env):
        from ontogeny.agent.models import AgentApprovalRow

        tel = env["telemetry"]
        async with env["maker"]() as s:
            for _ in range(3):
                s.add(
                    AgentApprovalRow(
                        session_id=1,
                        plugin="fab-copilot",
                        tool="act_x",
                        action="x",
                        parameters={},
                        status="rejected",
                    )
                )
            s.add(
                AgentApprovalRow(
                    session_id=1, plugin="fab-copilot", tool="act_x", action="x", parameters={}, status="executed"
                )
            )
            await s.commit()
        async with env["maker"]() as s:
            sigs = await tel.aggregate_signals(s, thresholds={"approval_reject_min": 3})
            hit = [x for x in sigs if x["kind"] == "approval_reject_rate"]
            assert hit and hit[0]["evidence"]["plugin"] == "fab-copilot"

    async def test_slow_query_p95_signal(self, env):
        tel = env["telemetry"]
        async with env["maker"]() as s:
            for _ in range(3):
                await tel.record_query(s, "wafer-test", {"id": "u"}, {"result": "PASS"}, 5000.0, 3)
            await s.commit()
        async with env["maker"]() as s:
            sigs = await tel.aggregate_signals(s)
            assert any(x["kind"] == "slow_query_p95" and x["evidence"]["object_type"] == "wafer-test" for x in sigs)

    async def test_hot_query_becomes_an_eval_case_gap(self, env):
        tel = env["telemetry"]
        async with env["maker"]() as s:
            for _ in range(3):
                await tel.record_query(s, "equipment", {"id": "u"}, {"status": "ACTIVE"}, 2.0, 4)
            await s.commit()
        async with env["maker"]() as s:
            await tel.aggregate_signals(s)
            await s.commit()
        from ontogeny.evolve.diagnoser import diagnose

        async with env["maker"]() as s:
            sigs = (await s.execute(select(EvolveSignalRow).where(EvolveSignalRow.kind == "hot_query"))).scalars().all()
        gaps = diagnose(list(sigs), env["compiled"])
        synth = [g for g in gaps if g["kind"] == "eval-case-synth"]
        assert synth and synth[0]["case"]["query"]["filter"] == {"status": "ACTIVE"}
        assert synth[0]["case"]["expect"].get("columns")

    async def test_informational_signals_cluster_by_object(self, env):
        from ontogeny.evolve.diagnoser import diagnose

        sigs = [
            EvolveSignalRow(
                kind="empty_query_rate", evidence={"object_type": "requirement", "rate": 0.5, "samples": 10}
            ),
            EvolveSignalRow(
                kind="slow_query_p95", evidence={"object_type": "requirement", "p95_ms": 3000, "samples": 5}
            ),
            EvolveSignalRow(
                kind="unmapped_filter_field", evidence={"object_type": "requirement", "field": "channel", "count": 9}
            ),
        ]
        for i, srow in enumerate(sigs):
            srow.id = i + 1
        gaps = diagnose(sigs, env["compiled"])
        clusters = [g for g in gaps if g["kind"] == "cluster"]
        assert clusters and clusters[0]["object"] == "requirement"
        assert len(clusters[0]["context"]) == 2  # the two informational signals
        # the concrete gap about the same object carries the cluster as context
        unmapped = [g for g in gaps if g.get("prop") == "channel"]
        assert unmapped and unmapped[0].get("context")


class TestDirectionE:
    """Direction E: the human 'no' becomes the loop's memory, and competing
    candidates on one signal resolve into one winner + superseded losers."""

    async def test_reject_api_records_reason(self, client):
        c, sc = client
        async with sc.sessionmaker() as s:
            row = ProposalRow(
                gap_kind="add-optional-property",
                diff=[
                    {
                        "mutation": "add-optional-property",
                        "object": "wafer-lot",
                        "prop": "urgency",
                        "type": "string",
                    }
                ],
                rationale="r",
            )
            s.add(row)
            await s.commit()
            pid = row.id
        r = await c.post(f"/api/v1/evolve/proposals/{pid}/reject", json={"reason": "urgency 与 priority 语义重叠"})
        assert r.status_code == 200
        detail = (await c.get(f"/api/v1/evolve/proposals/{pid}")).json()
        assert detail["status"] == "rejected"
        assert "priority" in (detail["rejected_reason"] or "")

    async def test_rejected_memory_reaches_the_prompt(self, env):
        class _Capture(_FakeLLM):
            last_messages: list | None = None

            async def chat(self, messages, **kw):
                type(self).last_messages = messages
                return {
                    "content": json.dumps(
                        {
                            "act": True,
                            "mutations": [
                                {
                                    "mutation": "enum-widen",
                                    "object": "requirement",
                                    "prop": "priority",
                                    "value": "URGENT",
                                }
                            ],
                            "rationale": "memory-aware alternative",
                        }
                    )
                }

        llm = _Capture("{}")
        prop = DecidingProposer(llm)
        gap = {
            "kind": "add-optional-property",
            "object": "wafer-lot",
            "prop": "urgency",
            "signal_id": 11,
            "rationale": "r",
        }
        memory = [
            {
                "gap_kind": "add-optional-property",
                "rationale": "add urgency",
                "rejected_reason": "urgency 与 priority 语义重叠",
                "diff": [],
            }
        ]
        out = await prop.propose_full(gap, env["compiled"], memory=memory)
        assert out.proposal is not None
        user_text = llm.last_messages[-1]["content"]
        assert "urgency 与 priority 语义重叠" in user_text  # the memory rode along
        assert out.proposal["mutations"][0]["mutation"] == "enum-widen"

    async def test_promote_supersedes_sibling_candidates(self, env):
        prom = Promoter(Settings(dev_auth=True, env={"ERP_DSN": "sqlite+aiosqlite:///:memory:"}), env["registry"])
        diff = [{"mutation": "add-optional-property", "object": "wafer-lot", "prop": "urgency", "type": "string"}]
        async with env["maker"]() as s:
            winner = ProposalRow(
                gap_kind="add-optional-property",
                signal_id=77,
                diff=diff,
                rationale="heuristic answer",
                origin="heuristic",
            )
            sibling = ProposalRow(
                gap_kind="add-optional-property",
                signal_id=77,
                diff=[
                    {
                        "mutation": "add-optional-property",
                        "object": "wafer-lot",
                        "prop": "urgency2",
                        "type": "string",
                    }
                ],
                rationale="llm alternative",
                origin="llm",
            )
            s.add_all([winner, sibling])
            await s.flush()
            out = await prom.promote(
                s,
                winner,
                env["pkg_root"],
                eval_report={"passed": True, "suites": {"flow": {"passed": True}}},
            )
            await s.flush()
            await s.refresh(sibling)
        assert out["status"] == "promoted"
        assert sibling.status == "superseded"
        assert sibling.superseded_by == winner.id


class TestDirectionB2B3:
    """B2: T2 proposals carry a real shadow diff. B3: earned autonomy is
    measured (streak) and its graduation request is a human-only ticket."""

    async def test_shadow_diff_report(self, env):
        prom = env["promoter"]
        rt = env["runtime"]
        async with env["maker"]() as s:
            await TestEvalRunner._complete_running_step(self, s, rt)
            await s.commit()
        async with env["maker"]() as s:
            dirty = await prom.shadow_diff(
                s,
                env["pkg_root"],
                [
                    {
                        "mutation": "rule-tighten",
                        "action": "complete-process-step",
                        "expr": "target.status == 'QUEUED'",
                    }
                ],
            )
        async with env["maker"]() as s:
            clean = await prom.shadow_diff(
                s,
                env["pkg_root"],
                [
                    {
                        "mutation": "rule-tighten",
                        "action": "complete-process-step",
                        "expr": "target.status != 'CANCELLED'",
                    }
                ],
            )
        assert dirty["clean"] is False
        act = dirty["actions"][0]
        assert act["would_reject"] == 1 and act["revisions"] == 1
        assert clean["clean"] is True and clean["actions"][0]["would_reject"] == 0

    async def test_t2_promote_attaches_shadow_report(self, env):
        prom = env["promoter"]
        async with env["maker"]() as s:
            row = ProposalRow(
                gap_kind="rule-tighten",
                diff=[
                    {
                        "mutation": "rule-tighten",
                        "action": "complete-process-step",
                        "expr": "target.status != 'CANCELLED'",
                    }
                ],
                rationale="tighten",
                signal_id=99,
            )
            s.add(row)
            await s.flush()
            out = await prom.promote(
                s,
                row,
                env["pkg_root"],
                eval_report={"passed": True, "suites": {"flow": {"passed": True}}},
            )
        assert out["status"] == "awaiting_human" and out["tier"] == "t2-canary"
        assert row.eval_report["shadow"]["clean"] is True

    async def test_graduation_streak_and_t3_ticket(self, client):
        c, sc = client
        # 10 consecutive clean promotions of the rule-tighten class
        async with sc.sessionmaker() as s:
            for i in range(10):
                s.add(
                    ProposalRow(
                        gap_kind="rule-tighten",
                        diff=[
                            {
                                "mutation": "rule-tighten",
                                "action": "complete-process-step",
                                "expr": f"target.seq < {1000 + i}",
                            }
                        ],
                        rationale="clean",
                        status="promoted",
                    )
                )
            # a rejected one OLDER than the streak must not break it
            s.add(
                ProposalRow(
                    gap_kind="other",
                    diff=[{"mutation": "enum-widen", "object": "requirement", "prop": "status", "value": "X"}],
                    rationale="old",
                    status="rejected",
                )
            )
            await s.commit()
        classes = (await c.get("/api/v1/evolve/graduation")).json()["classes"]
        by = {x["mutation"]: x for x in classes}
        assert "rule-tighten" in by and "add-optional-property" not in by  # already T0
        assert by["rule-tighten"]["streak"] == 10 and by["rule-tighten"]["eligible"] is True
        # not enough streak -> refused
        r = await c.post("/api/v1/evolve/graduation/request", json={"mutation": "eval-case-synth"})
        assert r.status_code == 429
        # enough streak -> the T3 ticket is filed as awaiting_human
        r = await c.post("/api/v1/evolve/graduation/request", json={"mutation": "rule-tighten"})
        assert r.status_code == 200
        detail = (await c.get(f"/api/v1/evolve/proposals/{r.json()['id']}")).json()
        assert detail["status"] == "awaiting_human"
        assert detail["diff"][0]["mutation"] == "tier-change"


class TestDirectionF:
    """F: the loop runs on a schedule (cycle endpoint), every proposal carries
    its blast radius, and a red post-merge eval can be undone."""

    async def test_cycle_runs_aggregate_and_diagnose(self, client):
        c, sc = client
        tel = sc.telemetry
        async with sc.sessionmaker() as s:
            for _ in range(6):
                await tel.record_query(s, "wafer-lot", {"id": "u"}, {"urgency": "HIGH"}, 1.0, 0)
            await s.commit()
        r = await c.post("/api/v1/evolve/cycle")
        assert r.status_code == 200
        body = r.json()
        assert any(x["kind"] == "unmapped_filter_field" for x in body["signals_created"])
        assert body["proposals"] and body["decisions"]

    async def test_proposals_carry_impact(self, client):
        c, sc = client
        async with sc.sessionmaker() as s:
            row = ProposalRow(
                gap_kind="add-optional-property",
                diff=[
                    {
                        "mutation": "add-optional-property",
                        "object": "wafer-lot",
                        "prop": "urgency",
                        "type": "string",
                    }
                ],
                rationale="r",
            )
            s.add(row)
            await s.commit()
            pid = row.id
        rows = (await c.get("/api/v1/evolve/proposals")).json()["proposals"]
        mine = next(x for x in rows if x["id"] == pid)
        assert mine["impact"]["objects"] == ["wafer-lot"]
        # the fab-copilot plugin reads this object through its catalog
        assert "fab-copilot" in mine["impact"]["agents"]

    async def test_t0_promote_backs_up_and_rollback_restores(self, env):
        prom = env["promoter"]
        diff = [{"mutation": "add-optional-property", "object": "wafer-lot", "prop": "urgency", "type": "string"}]
        async with env["maker"]() as s:
            row = ProposalRow(gap_kind="add-optional-property", signal_id=101, diff=diff, rationale="r")
            s.add(row)
            await s.flush()
            out = await prom.promote(
                s,
                row,
                env["pkg_root"],
                eval_report={"passed": True, "suites": {"flow": {"passed": True}}},
            )
        assert out["status"] == "promoted"
        backup = Path(out["rollback_dir"])
        assert backup.is_dir()
        # the mutated schema is on disk...
        assert "urgency" in load_package(env["pkg_root"]).find("ObjectType", "wafer-lot").spec.properties
        # ...and rollback restores the pre-merge package + republishes it
        async with env["maker"]() as s:
            rb = await prom.rollback(s, env["pkg_root"], backup)
        assert rb["status"] == "rolled_back"
        assert "urgency" not in load_package(env["pkg_root"]).find("ObjectType", "wafer-lot").spec.properties
