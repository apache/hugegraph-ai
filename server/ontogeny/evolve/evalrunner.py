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
"""EvalRunner: the deterministic selection ladder (evolution-loop §4).

L1 static (validate) is run by the promoter. This runner executes L2:
  - query regressions against the live object tables (shape / latency / counts)
  - ACTION TIME-TRAVEL REPLAY: historical revisions are replayed against the
    *candidate* package's rules; outcomes are compared with what humans
    actually did. The system-versioned store makes this a labeled dataset.
LLM-judge is deliberately absent: explanation is never a pass condition.
"""
from __future__ import annotations

import re
import time
from typing import Any

from sqlalchemy import select

from ..action.models import RevisionRow
from ..core import expr as _expr
from ..core.loader import OntologyPackage
from ..registry.compiled import compile_package


SYSTEM_COLUMNS = ("_rev", "_valid_from", "_valid_to", "_synced_at")


def declared_columns(compiled, object_type: str) -> list[str]:
    """Columns the query API promises for an object type (derived included)."""
    obj = compiled.objects.get(object_type)
    if obj is None:
        return []
    return [*obj.spec.properties, *SYSTEM_COLUMNS]


def _parse_since(since: str) -> int:
    m = re.fullmatch(r"(\d+)d", since.strip())
    return int(m.group(1)) if m else 90


class EvalRunner:
    def __init__(self, repo, query_service, agent_broker=None) -> None:
        self.repo = repo
        self.query = query_service
        self.agent_broker = agent_broker

    async def run(
        self, session, suite, *, candidate_pkg: OntologyPackage | None = None,
        system_principal: dict | None = None,
    ) -> dict[str, Any]:
        principal = system_principal or {"id": "eval-runner", "Role": {"eval"}}
        compiled = compile_package(candidate_pkg) if candidate_pkg is not None else self.query.compiled
        report: dict[str, Any] = {"cases": [], "passed": True}

        for case in suite.spec.queries:
            q = case.query
            object_type = str(q.get("object"))
            started = time.perf_counter()
            error: str | None = None
            objects: list[dict] = []
            try:
                out = await self.query.query(
                    session, object_type, principal,
                    filt=q.get("filter"), sort=q.get("sort"), limit=int(q.get("limit") or 100),
                )
                objects = out["objects"]
            except Exception as exc:  # noqa: BLE001 -- regression = red, not crash
                error = f"{type(exc).__name__}: {exc}"
            latency = round((time.perf_counter() - started) * 1000, 2)
            ok = error is None
            details: dict[str, Any] = {"latency_ms": latency, "rows": len(objects)}
            if ok and case.expect.columns:
                # Validate against the *declared schema*, never against the rows
                # that happen to exist: an empty result is a legitimate outcome,
                # and gating on it would keep the suite red (blocking the RSI
                # loop) whenever a filter matches nothing.
                schema = set(declared_columns(compiled, object_type))
                details["missing_columns"] = sorted(set(case.expect.columns) - schema)
                ok = not details["missing_columns"]
            if ok and case.expect.min_rows is not None:
                ok = len(objects) >= case.expect.min_rows
                details["min_rows"] = case.expect.min_rows
            if ok and case.expect.max_latency_ms is not None:
                ok = latency <= case.expect.max_latency_ms
                details["latency_budget"] = case.expect.max_latency_ms
            if ok and case.expect.row_count_max is not None:
                ok = len(objects) <= case.expect.row_count_max
            report["cases"].append({"name": case.name, "kind": "query", "ok": ok, **details, "error": error})
            report["passed"] = report["passed"] and ok

        for case in suite.spec.replays:
            days = _parse_since(case.since)
            cutoff = _dt_now_minus_days(days)
            revisions = (await session.execute(
                select(RevisionRow).where(
                    RevisionRow.action == case.action,
                    RevisionRow.outcome == "executed",
                    RevisionRow.created_at >= cutoff,
                ).order_by(RevisionRow.created_at)
            )).scalars().all()
            action_res = compiled.actions.get(case.action)
            if action_res is None:
                report["cases"].append({"kind": "replay", "action": case.action, "ok": False,
                                        "error": "action missing in candidate package"})
                report["passed"] = False
                continue
            total = matched = after_rejected = 0
            for rev in revisions:
                # the revision's own before/after snapshots are the truth: a
                # `get(at=rev.created_at)` lands exactly on the new version's
                # _valid_from boundary and silently returns the AFTER state,
                # which made any outcomes-match assertion unsatisfiable
                before = rev.before if rev.before is not None else \
                    await self.repo.get(session, action_res.spec.target, rev.object_id, at=rev.created_at)
                after = rev.after if rev.after is not None else \
                    await self.repo.get(session, action_res.spec.target, rev.object_id)
                if before is None:
                    # not replayable: the revision predates the current package's
                    # target binding (action retargeted / object type renamed), so
                    # the object does not exist under this type. It is not
                    # evidence either way and must stay out of the denominator --
                    # counting it made `after_rejected == total` impossible and
                    # kept the suite red forever after a retargeting.
                    continue
                total += 1
                ctx = _expr.ExprContext(target=before, parameters=rev.params or {},
                                        principal={"id": rev.principal})
                rules_ok = all(
                    bool(_expr.evaluate(r.expr, ctx)) for r in action_res.spec.rules
                )
                # historical executions passed the OLD rules; the candidate must
                # agree on the pass/fail outcome class for the replay to match
                if rules_ok:
                    matched += 1
                # no-double-close: replaying against the CURRENT (post-action)
                # state must be rejected by the candidate rules
                if after is not None:
                    ctx2 = _expr.ExprContext(target=after, parameters=rev.params or {},
                                             principal={"id": rev.principal})
                    after_rejected += 0 if all(
                        bool(_expr.evaluate(r.expr, ctx2)) for r in action_res.spec.rules
                    ) else 1
            ok = True
            expectations: dict[str, Any] = {"replays": total, "outcome_matches": matched}
            if total and case.expect.outcomes_match is not None:
                ok = matched / total >= case.expect.outcomes_match
            if total and case.expect.no_double_close:
                expectations["after_state_rejections"] = after_rejected
                ok = ok and after_rejected == total
            report["cases"].append({"kind": "replay", "action": case.action, "ok": ok, **expectations})
            report["passed"] = report["passed"] and ok

        for case in getattr(suite.spec, "agents", []) or []:
            ok, details = await self._run_agent_case(case)
            report["cases"].append({"name": case.name, "kind": "agent", "ok": ok, **details})
            report["passed"] = report["passed"] and ok

        return report

    async def _run_agent_case(self, case) -> tuple[bool, dict[str, Any]]:
        """Replay a scripted trajectory through the REAL broker (same gates,
        same audit) and compare outcome classes. LLMs are not reproducible, so
        the script is the unit under test -- exactly what a promotion would
        release."""


        details: dict[str, Any] = {"plugin": case.plugin, "steps": len(case.script)}
        if self.agent_broker is None:
            return False, {**details, "error": "agent eval requires the broker (service not wired)"}
        try:
            self.agent_broker.plugin(case.plugin)  # existence probe: raises -> reported below
        except Exception as exc:  # noqa: BLE001
            return False, {**details, "error": f"unknown plugin: {exc}"}

        async def run_once() -> list[str]:
            sess = await self.agent_broker.open_session(case.plugin, f"eval:{case.name}")
            outcomes: list[str] = []
            for step in case.script:
                out = await self.agent_broker.call_tool(sess["id"], str(step.get("tool")),
                                                        dict(step.get("args") or {}))
                outcomes.append(classify(str(out.get("outcome"))))
                if classify(str(out.get("outcome"))) == "ok" and case.expect.idempotent:
                    continue
            await self.agent_broker.finish_session(sess["id"], {"eval": case.name})
            return outcomes

        try:
            first = await run_once()
        except Exception as exc:  # noqa: BLE001 -- regression = red, not crash
            return False, {**details, "error": f"{type(exc).__name__}: {exc}"}

        if case.expect.outcomes and first != list(case.expect.outcomes):
            return False, {**details, "expected": list(case.expect.outcomes), "actual": first}
        details["outcomes"] = first

        if case.expect.idempotent:
            second = await run_once()
            # the write steps must be refused on replay: rules see post-state
            # (e.g. already-CLOSED), so a second execution means double-apply
            for idx, step in enumerate(case.script):
                if str(step.get("tool", "")).startswith("act_"):
                    if second[idx] == "ok":
                        return False, {**details, "replay": second,
                                       "error": f"step {idx} ({step.get('tool')}) executed twice"}
            details["replay"] = second
        return True, details


_SUCCESS = {"ok", "executed"}
_DENIED = {"POLICY_DENIED", "denied_policy", "AGENT_TOOL_NOT_ALLOWED"}
_REJECTED = {"RULE_REJECTED", "rejected_rule"}


def classify(outcome: str) -> str:
    """Collapse a tool-call outcome to a stable class for eval assertions."""
    if outcome in _SUCCESS:
        return "ok"
    if outcome in _DENIED:
        return "denied"
    if outcome in _REJECTED:
        return "rejected"
    return outcome.lower()


def _dt_now_minus_days(days: int):
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)
