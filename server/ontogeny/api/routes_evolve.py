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
"""The RSI loop's console surface (admin-gated at the router)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..evolve.models import EvolveSignalRow, ProposalRow
from ..evolve.ops import _evolve_impact, run_diagnose
from ..evolve.promoter import apply_mutations
from ..core.loader import load_package
from ..service import ServiceContext
from .deps import get_sc
from .schemas import GraduationBody, RejectBody


def register(evolve_r: APIRouter, sc: ServiceContext) -> None:
    # ---- evolve (RSI loop) -------------------------------------------------


    @evolve_r.get("/signals")
    async def signals(limit: int = 100, sc: ServiceContext = Depends(get_sc)):
        async with sc.sessionmaker() as s:
            rows = (await s.execute(
                select(EvolveSignalRow).order_by(EvolveSignalRow.id.desc()).limit(limit)
            )).scalars().all()
        return {"signals": [{"id": x.id, "kind": x.kind, "evidence": x.evidence} for x in rows]}

    @evolve_r.delete("/signals/{signal_id}")
    async def delete_signal(signal_id: int, sc: ServiceContext = Depends(get_sc)):
        async with sc.sessionmaker() as s:
            row = (await s.execute(select(EvolveSignalRow).where(EvolveSignalRow.id == signal_id))).scalar_one_or_none()
            if row is None:
                raise HTTPException(404, "signal not found")
            await s.delete(row)
            await s.commit()
        return {"deleted": signal_id}

    @evolve_r.post("/cycle")
    async def evolve_cycle(sc: ServiceContext = Depends(get_sc)):
        """One scheduled beat: aggregate signals, then diagnose (direction F).
        Promotion is NEVER automatic from here -- the ladder keeps its gates."""
        async with sc.sessionmaker() as s:
            evo = getattr(sc.compiled, "evolution", None)
            obs = getattr(getattr(evo, "spec", None), "observability", None) if evo else None
            created = await sc.telemetry.aggregate_signals(
                s, thresholds=getattr(obs, "thresholds", None) or None)
            await s.commit()
        diagnosed = await run_diagnose(sc)
        return {"signals_created": created, **diagnosed}

    @evolve_r.post("/aggregate")
    async def aggregate_signals(sc: ServiceContext = Depends(get_sc)):
        # aggregate_signals runs every detector (telemetry + quarantine) and is
        # idempotent within the window: an unchanged world yields zero new rows
        async with sc.sessionmaker() as s:
            # per-domain sensitivity from EvolutionPolicy.observability.thresholds
            evo = getattr(sc.compiled, "evolution", None)
            thresholds = getattr(getattr(evo, "spec", None), "observability", None) if evo else None
            created = await sc.telemetry.aggregate_signals(
                s, thresholds=getattr(thresholds, "thresholds", None) or None)
            await s.commit()
        return {"created": created}

    @evolve_r.post("/diagnose")
    async def diagnose_signals(sc: ServiceContext = Depends(get_sc)):
        """Signals -> gaps -> proposals (see run_diagnose)."""
        return await run_diagnose(sc)

    @evolve_r.get("/proposals")
    async def list_proposals(status: str | None = None, sc: ServiceContext = Depends(get_sc)):
        async with sc.sessionmaker() as s:
            stmt = select(ProposalRow).order_by(ProposalRow.id.desc()).limit(100)
            if status:
                stmt = stmt.where(ProposalRow.status == status)
            rows = (await s.execute(stmt)).scalars().all()
        return {"proposals": [{"id": p.id, "status": p.status, "tier": p.tier, "gap_kind": p.gap_kind,
                               "origin": p.origin, "llm_analysis": p.llm_analysis,
                               "superseded_by": p.superseded_by,
                               "impact": _evolve_impact(sc.compiled, p.diff)} for p in rows]}

    @evolve_r.get("/proposals/{proposal_id}")
    async def get_proposal(proposal_id: int, sc: ServiceContext = Depends(get_sc)):
        async with sc.sessionmaker() as s:
            p = (await s.execute(select(ProposalRow).where(ProposalRow.id == proposal_id))).scalar_one_or_none()
        if p is None:
            raise HTTPException(404, "proposal not found")
        return {"id": p.id, "status": p.status, "tier": p.tier, "origin": p.origin, "diff": p.diff,
                "rationale": p.rationale, "eval_report": p.eval_report,
                "llm_analysis": p.llm_analysis, "rejected_reason": p.rejected_reason,
                "superseded_by": p.superseded_by, "signal_id": p.signal_id,
                "impact": _evolve_impact(sc.compiled, p.diff)}

    @evolve_r.delete("/proposals/{proposal_id}")
    async def delete_proposal(proposal_id: int, sc: ServiceContext = Depends(get_sc)):
        async with sc.sessionmaker() as s:
            row = (await s.execute(select(ProposalRow).where(ProposalRow.id == proposal_id))).scalar_one_or_none()
            if row is None:
                raise HTTPException(404, "proposal not found")
            await s.delete(row)
            await s.commit()
        return {"deleted": proposal_id}

    @evolve_r.post("/proposals/{proposal_id}/reject")
    async def reject_proposal(proposal_id: int, body: RejectBody,
                              sc: ServiceContext = Depends(get_sc)):
        """The human 'no' is a first-class outcome AND the loop's memory: the
        reason is fed back into the proposer's prompt on later rounds, so the
        same rejected mutation is not re-filed verbatim (direction E)."""
        async with sc.sessionmaker() as s:
            row = (await s.execute(select(ProposalRow).where(ProposalRow.id == proposal_id))).scalar_one_or_none()
            if row is None:
                raise HTTPException(404, "proposal not found")
            row.status = "rejected"
            row.rejected_reason = (body.reason or "").strip() or None
            await s.commit()
        return {"id": proposal_id, "status": "rejected"}




    @evolve_r.get("/graduation")
    async def graduation_status(sc: ServiceContext = Depends(get_sc)):
        """Direction B3: how close each mutation class is to earning more
        autonomy (T1/T2 -> T0). Earning it stays a T3 human decision."""
        from ..evolve.promoter import GRADUATION_STREAK, graduation_streak
        from ..evolve.proposer import MUTATION_CATALOG

        evo = getattr(sc.compiled, "evolution", None)
        tiers = getattr(getattr(evo, "spec", None), "tiers", {}) or {}
        t0 = set(getattr(tiers.get("t0-auto-merge"), "mutations", []) or [])
        async with sc.sessionmaker() as s:
            classes = []
            for kind in MUTATION_CATALOG:
                if kind in t0:
                    continue  # already trusted at T0: nothing to graduate
                streak = await graduation_streak(s, kind)
                classes.append({"mutation": kind, "streak": streak,
                                "threshold": GRADUATION_STREAK,
                                "eligible": streak >= GRADUATION_STREAK})
        return {"classes": classes,
                "rule": getattr(getattr(getattr(evo, "spec", None), "graduation", None), "rule", None)}

    @evolve_r.post("/graduation/request")
    async def graduation_request(body: GraduationBody, sc: ServiceContext = Depends(get_sc)):
        """File the T3 ticket: promote a mutation class toward T0. The request
        is created for human execution only -- EvolutionPolicy is a constitution
        file the loop never edits itself."""
        from ..evolve.promoter import GRADUATION_STREAK, graduation_streak
        from ..evolve.proposer import MUTATION_CATALOG

        if body.mutation not in MUTATION_CATALOG:
            raise HTTPException(400, f"unknown mutation class {body.mutation!r}")
        evo = getattr(sc.compiled, "evolution", None)
        tiers = getattr(getattr(evo, "spec", None), "tiers", {}) or {}
        t0 = set(getattr(tiers.get("t0-auto-merge"), "mutations", []) or [])
        if body.mutation in t0:
            raise HTTPException(400, f"{body.mutation!r} is already T0")
        async with sc.sessionmaker() as s:
            streak = await graduation_streak(s, body.mutation)
            if streak < GRADUATION_STREAK:
                raise HTTPException(429, f"streak {streak}/{GRADUATION_STREAK} not enough to graduate")
            row = ProposalRow(gap_kind="graduation-request",
                              diff=[{"mutation": "tier-change", "mutation_class": body.mutation,
                                     "to": "t0-auto-merge"}],
                              rationale=(f"mutation class {body.mutation!r} has {streak} consecutive "
                                         f"clean promotions; request to graduate to T0 (human decision)"),
                              origin="human", status="awaiting_human")
            s.add(row)
            await s.commit()
            await s.flush()
            return {"id": row.id, "status": row.status, "streak": streak}

    @evolve_r.post("/proposals/{proposal_id}/eval")
    async def eval_proposal(proposal_id: int, sc: ServiceContext = Depends(get_sc)):
        async with sc.sessionmaker() as s:
            p = (await s.execute(select(ProposalRow).where(ProposalRow.id == proposal_id))).scalar_one_or_none()
            if p is None:
                raise HTTPException(404, "proposal not found")
            # B1: the ladder must judge the CANDIDATE, not the live schema --
            # apply the diff to an in-memory copy and let the runner see the
            # candidate's declared columns and (crucially) its action rules
            # during time-travel replay. A diff no applier can express (manual
            # T1/T2 kinds) still evaluates against live, honestly labelled.
            candidate = None
            candidate_error = None
            if sc.package_root is not None:
                try:
                    candidate = apply_mutations(load_package(Path(sc.package_root)), p.diff)
                except Exception as exc:  # noqa: BLE001 -- unappliable diff is a report, not a crash
                    candidate_error = f"{type(exc).__name__}: {exc}"
            reports = {}
            passed = True
            for suite in sc.compiled.eval_suites.values():
                report = await sc.eval_runner.run(s, suite, candidate_pkg=candidate)
                if candidate is not None:
                    report["candidate"] = True
                # carry the suite's declared identity into the report: the UI
                # shows WHAT each suite is, not just its kebab-case name
                reports[suite.metadata.name] = {
                    "display": suite.metadata.display,
                    "description": suite.metadata.description,
                    **report,
                }
                passed = passed and report["passed"]
            p.eval_report = {"passed": passed, "candidate_evaluated": candidate is not None,
                             "candidate_error": candidate_error, "suites": reports}
            p.status = "evaluated"
            await s.commit()
        return {"passed": passed, "candidate_evaluated": candidate is not None}

    @evolve_r.post("/proposals/{proposal_id}/promote")
    async def promote_proposal(proposal_id: int, sc: ServiceContext = Depends(get_sc)):
        # One implementation for HTTP and CLI (ontogeny evolve promote): the
        # hot-swap, post-merge re-eval and auto-rollback used to live only in
        # this route, so the CLI promoted without any of them.
        return await sc.evolve_promote(proposal_id)
