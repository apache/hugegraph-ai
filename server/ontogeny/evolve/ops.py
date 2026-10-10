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
"""Service-level evolve operations: the diagnose beat and proposal impact.

These used to live in ``ontogeny.api.app`` -- which forced the scheduled worker
(``api_factory``) to import FROM the web layer, an inverted dependency. They
are platform operations that happen to be exposed by HTTP, not HTTP logic."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:  # pragma: no cover -- import cycle avoidance (hints only)
    from ..service import ServiceContext


def _is_deciding(proposer) -> bool:
    """The LLM-first proposer consumes (gap, compiled); the deterministic
    one consumes (gap). Duck-typed so tests can substitute either."""
    return hasattr(proposer, "client")


def _evolve_impact(compiled, diff: list) -> dict:
    """Direction F: the blast radius of a proposal -- which objects, actions
    and agent plugins the mutation touches, computed from the live compile."""

    def _snake(name: str) -> str:
        return re.sub(r"[^a-z0-9_]+", "_", str(name).strip().lower()).strip("_")

    objects: set[str] = set()
    actions: set[str] = set()
    for m in diff or []:
        if not isinstance(m, dict):
            continue
        if m.get("object"):
            objects.add(str(m["object"]))
        if m.get("action"):
            actions.add(str(m["action"]))
        case = m.get("case") or {}
        qobj = (case.get("query") or {}).get("object")
        if qobj:
            objects.add(str(qobj))
    tools = {f"search_{_snake(o)}" for o in objects} | {f"act_{_snake(a)}" for a in actions}
    agents = []
    for name, plug in (getattr(compiled, "agent_plugins", {}) or {}).items():
        allow = set(getattr(plug.spec.tools, "allow", []) or [])
        if tools & allow:
            agents.append(name)
    return {"objects": sorted(objects), "actions": sorted(actions), "agents": sorted(agents)}


async def run_diagnose(sc: ServiceContext) -> dict:
    """Signals -> gaps -> proposals. One beat of the RSI loop, shared by the
    console route and the scheduled worker (direction F).

    The proposer decides by default: the LLM (when a provider is configured)
    chooses the mutation, the property type and the business metadata inside a
    rule-validated catalog, and the deterministic heuristic answers only when
    the model is absent, fails or steps outside its bounds. The human 'no' is
    memory; competing candidates on one signal are filed and ranked by eval.
    """
    from .diagnoser import diagnose
    from .models import EvolveSignalRow, ProposalRow
    from .proposer import ProposeOutcome

    async with sc.sessionmaker() as s:
        sigs = (await s.execute(select(EvolveSignalRow).order_by(EvolveSignalRow.id.desc()).limit(200))).scalars().all()
        gaps = diagnose(list(sigs), sc.compiled)
        # a signal that already has a live (non-rejected) proposal is being
        # handled -- re-diagnosing would file the same mutation again on
        # every click. A *rejected* proposal may be re-attempted: the world
        # may have changed (or the last attempt was wrong).
        active_signal_ids = set((await s.execute(
            select(ProposalRow.signal_id).where(
                ProposalRow.signal_id.is_not(None),
                ProposalRow.status != "rejected",
            )
        )).scalars().all())
        proposals = []
        decisions = []
        import inspect as _inspect

        # direction E: the human 'no' is memory -- recent rejections ride
        # into the proposer's prompt so the same idea is not re-filed
        # verbatim without addressing why it was refused
        rejected_rows = (await s.execute(
            select(ProposalRow).where(ProposalRow.status == "rejected")
            .order_by(ProposalRow.id.desc()).limit(5)
        )).scalars().all()
        memory = [{"gap_kind": r.gap_kind, "rationale": r.rationale,
                   "rejected_reason": r.rejected_reason, "diff": r.diff}
                  for r in rejected_rows]

        for gap in gaps:
            sid = gap.get("signal_id")
            if sid in active_signal_ids:
                decisions.append({"signal_id": sid, "kind": gap.get("kind"), "outcome": "skipped",
                                  "analysis": None, "rationale": None})
                continue
            outcome = (await sc.proposer.propose_full(gap, sc.compiled, memory=memory)) \
                if _is_deciding(sc.proposer) else None
            if outcome is None:
                # heuristic-only proposer: wrap its answer in the same shape
                result = sc.proposer.propose(gap)
                proposal = await result if _inspect.isawaitable(result) else result
                outcome = ProposeOutcome(proposal=proposal)
            proposal = outcome.proposal
            if proposal is None:
                # no proposal: either an informational signal (rules alone
                # cannot act on it) or the model declining to mutate -- the
                # model's analysis is kept either way (direction A)
                decisions.append({"signal_id": sid, "kind": gap.get("kind"),
                                  "outcome": "informational" if gap.get("informational") else "declined",
                                  "analysis": outcome.analysis, "rationale": None})
                continue
            row = ProposalRow(gap_kind=gap["kind"], diff=proposal["mutations"],
                              rationale=proposal["rationale"], origin=proposal.get("origin", "heuristic"),
                              signal_id=sid, llm_analysis=outcome.analysis)
            s.add(row)
            proposals.append(row)
            decisions.append({"signal_id": sid, "kind": gap.get("kind"),
                              "outcome": proposal.get("origin", "heuristic"),
                              "analysis": outcome.analysis,
                              "rationale": proposal.get("rationale")})
            # the model declined the obvious mutation but offered a better,
            # rule-validated one: file it as a SECOND candidate on the same
            # signal -- eval ranks them, promote supersedes the loser
            alt = outcome.alternative
            if alt is not None:
                alt_row = ProposalRow(gap_kind=gap["kind"], diff=alt["mutations"],
                                      rationale=alt["rationale"], origin="llm",
                                      signal_id=sid, llm_analysis=outcome.analysis)
                s.add(alt_row)
                proposals.append(alt_row)
                decisions.append({"signal_id": sid, "kind": gap.get("kind"),
                                  "outcome": "llm_alternative",
                                  "analysis": outcome.analysis,
                                  "rationale": alt["rationale"]})
        await s.commit()
        await s.flush()
        analysis_by_id = {p.id: p.llm_analysis for p in proposals}
    # who decided this round: the model or the fallback (honest provenance
    # for the console; informational declines are part of the answer)
    stats = getattr(sc.proposer, "stats", None) or {}
    return {"proposals": [{"id": p.id, "gap_kind": p.gap_kind, "diff": p.diff,
                           "rationale": p.rationale, "origin": p.origin,
                           "analysis": analysis_by_id.get(p.id)} for p in proposals],
            "decided_by": stats,
            "decisions": decisions}
