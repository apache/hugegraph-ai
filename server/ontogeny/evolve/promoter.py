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
"""Promoter: tier classification, budgets, constitution enforcement, apply.

The constitution (evolution-loop §6) is enforced HERE and in validate():
policy-loosen / marking-change / ownership-change / eval-passbar-change /
destructive-migration are never automatable -- the proposal becomes
``awaiting_human`` and the audit trail says why.
"""
from __future__ import annotations

import datetime as _dt
import shutil
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from ..core import expr as _expr
from ..core.expr import ExprContext
from ..core.loader import OntologyPackage, load_package
from ..core.models import PropertyDef
from ..core.validator import validate
from ..errors import BudgetExceededError, ConstitutionViolationError, DSLValidationError
from ..registry.store import RegistryService
from .models import BudgetRow, ProposalRow

CONSTITUTION_MUTATIONS = {
    "policy-loosen", "marking-change", "ownership-change",
    "eval-passbar-change", "destructive-migration",
}


def _iso_week(d: _dt.datetime) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


class Promoter:
    def __init__(self, settings, registry: RegistryService) -> None:
        self.settings = settings
        self.registry = registry

    # ------------------------------------------------------------ classify

    def classify(self, mutations: list[dict], evolution_policy) -> str:
        kinds = {m.get("mutation") for m in mutations}
        if kinds & CONSTITUTION_MUTATIONS:
            return "t3-human-only"
        tiers = (evolution_policy.spec.tiers if evolution_policy else {}) or {}
        t0_cfg = tiers.get("t0-auto-merge")
        t2_cfg = tiers.get("t2-canary")
        t0 = set(t0_cfg.mutations) if t0_cfg else set()
        t2 = set(t2_cfg.mutations) if t2_cfg else set()
        if kinds and kinds <= t0:
            return "t0-auto-merge"
        if kinds & t2:
            return "t2-canary"
        return "t1-pr"

    # --------------------------------------------------------------- budget

    async def _budget_check_and_use(self, session, namespace: str, cap: int) -> int:
        week = _iso_week(_dt.datetime.now(_dt.timezone.utc))
        row = (await session.execute(
            select(BudgetRow).where(BudgetRow.namespace == namespace, BudgetRow.week == week)
        )).scalar_one_or_none()
        used = row.used if row else 0
        if used + 1 > cap:
            raise BudgetExceededError(
                f"T0 budget exhausted for {namespace!r} in {week}: {used}/{cap}",
                details={"namespace": namespace, "week": week, "used": used, "cap": cap},
            )
        if row is None:
            session.add(BudgetRow(namespace=namespace, week=week, used=1))
        else:
            row.used = used + 1
        return used + 1

    def _t0_cap(self, evolution_policy) -> int:
        tiers = (evolution_policy.spec.tiers if evolution_policy else {}) or {}
        t0 = tiers.get("t0-auto-merge")
        if t0 is not None and t0.budget is not None:
            return int(t0.budget.per_week)
        return 5  # conservative default

    # --------------------------------------------------------------- promote

    async def promote(
        self, session, proposal: ProposalRow, pkg_root: str | Path,
        *, eval_report: dict | None = None, force_tier: str | None = None,
    ) -> dict[str, Any]:
        pkg = load_package(pkg_root)
        evo = pkg.evolution_policy()
        tier = force_tier or self.classify(proposal.diff, evo)
        proposal.tier = tier

        if tier == "t3-human-only":
            proposal.status = "awaiting_human"
            proposal.eval_report = eval_report
            raise ConstitutionViolationError(
                "proposal touches the constitution surface; human review is mandatory (T3)",
                details={"proposal_id": proposal.id, "mutations": [m.get("mutation") for m in proposal.diff]},
            )

        if tier == "t0-auto-merge":
            # Fail closed: an AUTO-merge must present a green eval report.
            # `None` used to pass silently, which made the EvalSuite gate
            # skippable by promoting a fresh proposal before running /eval --
            # the constitution's "validate + eval green + budget" reduced to
            # two of three with no trace.
            if eval_report is None:
                proposal.status = "proposed"
                return {"status": "needs_eval", "tier": tier,
                        "reason": "T0 auto-merge requires a green eval report (run /eval first)"}
            if not eval_report.get("passed", False):
                proposal.status = "rejected"
                return {"status": "rejected", "reason": "eval suite not green"}
            namespace = pkg.manifest.metadata.name
            cap = self._t0_cap(evo)
            used = await self._budget_check_and_use(session, namespace, cap)

            candidate = apply_mutations(load_package(pkg_root), proposal.diff)
            report = validate(candidate)
            if not report.ok:
                proposal.status = "rejected"
                return {"status": "rejected", "reason": "candidate failed validation",
                        "issues": [f"{i.code}: {i.message}" for i in report.issues if i.severity == "error"]}
            # direction F: a byte-identical backup, so a red post-merge eval
            # can be undone without touching git
            backup_dir = Path(str(pkg_root) + ".evolve-backup")
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            shutil.copytree(pkg_root, backup_dir)
            write_package(candidate)  # merge = files on disk (revert = git checkout)
            compiled = await self.registry.publish(session, candidate, created_by=f"evolve:t0:proposal-{proposal.id}")
            proposal.status = "promoted"
            proposal.promoted_by = "evolve:t0"
            proposal.eval_report = eval_report
            # direction E: a signal with competing candidates has a winner now
            # -- the losers are marked superseded instead of dangling forever
            if proposal.signal_id is not None:
                sibs = (await session.execute(
                    select(ProposalRow).where(
                        ProposalRow.signal_id == proposal.signal_id,
                        ProposalRow.id != proposal.id,
                        ProposalRow.status.in_(("proposed", "evaluated")),
                    ))).scalars().all()
                for sib in sibs:
                    sib.status = "superseded"
                    sib.superseded_by = proposal.id
            return {
                "status": "promoted", "tier": tier, "budget_used": used, "budget_cap": cap,
                "content_hash": compiled.content_hash,
                "rollback_dir": str(backup_dir),
                "revert": f"ontogeny publish {pkg_root}  # republish the previous git revision",
            }

        # T1 / T2: machine-authored PR equivalent -- materialize a validated
        # branch directory for human review, never auto-publish. The tier
        # table's "eval-suite-green" requirement is enforced here: a red eval
        # report rejects the proposal outright (no eval report yet = the human
        # runs eval from the console before deciding).
        if eval_report is not None and not eval_report.get("passed", False):
            proposal.status = "rejected"
            return {"status": "rejected", "tier": tier, "reason": "eval suite not green"}
        if tier == "t2-canary":
            # direction B2: a T2 always carries a shadow report -- how the
            # candidate's rules would have re-decided real history
            shadow = await self.shadow_diff(session, pkg_root, proposal.diff)
            base = dict(eval_report) if eval_report else {}
            base["shadow"] = shadow
            eval_report = base
        branch = Path(str(pkg_root) + f".proposal-{proposal.id}")
        if branch.exists():
            shutil.rmtree(branch)
        shutil.copytree(pkg_root, branch)
        manual = False
        try:
            candidate = apply_mutations(load_package(branch), proposal.diff)
            write_package(candidate)
        except DSLValidationError:
            # mutation kinds with no mechanical applier (rule tuning etc.) are
            # applied by a human inside the branch -- that is exactly what T1/T2 mean
            manual = True
            candidate = load_package(branch)
        report = validate(candidate)
        if not report.ok:
            proposal.status = "rejected"
            return {"status": "rejected", "reason": "candidate failed validation",
                    "issues": [f"{i.code}: {i.message}" for i in report.issues if i.severity == "error"]}
        proposal.status = "awaiting_human"
        proposal.eval_report = eval_report
        return {"status": "awaiting_human", "tier": tier, "branch": str(branch),
                "manual_application": manual}

    # ------------------------------------------------------------ shadow (B2)

    async def shadow_diff(self, session, pkg_root: str | Path, diff: list[dict],
                          *, since_days: int = 90) -> dict[str, Any]:
        """Direction B2: the shadow-diff-clean gate, made real.

        Replays the revision history of every action the diff TOUCHES through
        both the live and the candidate rules and diffs the outcome classes. An
        action whose historical human decisions the candidate would overturn
        makes the shadow dirty -- exactly the evidence a reviewer needs before
        approving a T2 canary.
        """
        from ..action.models import RevisionRow

        live_compiled = await self.registry.load_latest(session)
        if live_compiled is None:
            return {"clean": True, "actions": [], "note": "no published snapshot to diff against"}
        from ..registry.compiled import compile_package

        candidate = compile_package(apply_mutations(load_package(pkg_root), diff))
        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=since_days)
        changed = sorted({m["action"] for m in diff
                          if m.get("mutation") == "rule-tighten" and m.get("action")})
        actions: list[dict[str, Any]] = []
        clean = True
        for name in changed:
            live = live_compiled.actions.get(name)
            cand = candidate.actions.get(name)
            if live is None or cand is None:
                continue
            live_rules = [r.expr for r in live.spec.rules]
            cand_rules = [r.expr for r in cand.spec.rules]
            if live_rules == cand_rules:
                continue
            revs = (await session.execute(
                select(RevisionRow).where(
                    RevisionRow.action == name,
                    RevisionRow.outcome == "executed",
                    RevisionRow.created_at >= cutoff,
                ).order_by(RevisionRow.created_at)
            )).scalars().all()
            would_reject: list[dict[str, Any]] = []
            for rev in revs:
                before = rev.before
                if before is None:
                    continue
                ctx = ExprContext(target=before, parameters=rev.params or {},
                                  principal={"id": rev.principal})
                try:
                    live_pass = all(bool(_expr.evaluate(rx, ctx)) for rx in live_rules)
                    cand_pass = all(bool(_expr.evaluate(rx, ctx)) for rx in cand_rules)
                except Exception:  # noqa: BLE001 -- an undecidable row is not evidence
                    continue
                if live_pass and not cand_pass:
                    would_reject.append({"revision": rev.id, "object_id": rev.object_id,
                                         "principal": rev.principal})
            if would_reject:
                clean = False
            actions.append({"action": name, "revisions": len(revs),
                            "would_reject": len(would_reject), "details": would_reject[:20]})
        return {"clean": clean, "actions": actions}

    async def rollback(self, session, pkg_root: str | Path, backup_dir: str | Path) -> dict[str, Any]:
        """Direction F: restore the pre-merge files and republish them. The
        loop undoing its own last merge -- never a human's (backups only exist
        for evolve T0 merges)."""
        backup = Path(backup_dir)
        if not backup.is_dir():
            raise DSLValidationError(f"no evolve backup at {backup_dir!r}")
        for f in backup.rglob("*"):
            if f.is_file():
                dest = Path(pkg_root) / f.relative_to(backup)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
        pkg = load_package(pkg_root)
        compiled = await self.registry.publish(session, pkg, created_by="evolve:rollback")
        shutil.rmtree(backup, ignore_errors=True)
        return {"status": "rolled_back", "content_hash": compiled.content_hash}


class MutationCfg:  # pragma: no cover -- retained for config defaults documentation
    mutations: list[str] = []


def apply_mutations(pkg: OntologyPackage, mutations: list[dict]) -> OntologyPackage:
    """Pure in-memory application of a mutation diff to a loaded package."""
    import copy

    pkg = copy.deepcopy(pkg)
    for m in mutations:
        kind = m.get("mutation")
        if kind == "add-optional-property":
            obj = pkg.find("ObjectType", m["object"])
            if obj is None:
                raise DSLValidationError(f"mutation targets unknown object {m['object']!r}")
            if m["prop"] in obj.spec.properties:
                continue  # idempotent
            obj.spec.properties[m["prop"]] = PropertyDef(
                type=m.get("type", "string"), display=m.get("display") or m["prop"],
                description=m.get("description"), required=False,
            )
            column = m.get("column")
            if column and obj.spec.backing is not None:
                obj.spec.backing.mapping[m["prop"]] = column
        elif kind == "enum-widen":
            obj = pkg.find("ObjectType", m["object"])
            if obj is None:
                raise DSLValidationError(f"enum-widen targets unknown object {m['object']!r}")
            pdef = obj.spec.properties.get(m["prop"])
            if pdef is None:
                raise DSLValidationError(f"enum-widen targets unknown property {m['object']}.{m['prop']}")
            if not pdef.type.startswith("enum["):
                raise DSLValidationError(f"{m['prop']} is not an enum")
            values = [v.strip() for v in pdef.type[5:-1].split(",") if v.strip()]
            if m["value"] not in values:
                values.append(m["value"])
            pdef.type = "enum[" + ", ".join(values) + "]"
        elif kind == "rule-tighten":
            # direction-only by construction: this mutation can only APPEND a
            # rule, and every rule must pass, so any applier-reachable change
            # is a tightening. Editing/removing rules is not expressible here
            # and stays where the constitution puts it (human, T3).
            from ..core.models import Rule

            act = pkg.find("Action", m["action"])
            if act is None:
                raise DSLValidationError(f"rule-tighten targets unknown action {m['action']!r}")
            expr = (m.get("expr") or "").strip()
            if not expr:
                raise DSLValidationError("rule-tighten requires a non-empty expr")
            if any(r.expr.strip() == expr for r in act.spec.rules):
                continue  # idempotent: the same tightening is already in force
            act.spec.rules = [*act.spec.rules, Rule(expr=expr, message=m.get("message"))]
        elif kind == "eval-case-synth":
            # adding cases makes the selection function STRICTER, which the
            # constitution explicitly allows (only lowering the pass bar is
            # forbidden); still not T0: eval assets are owned, human-reviewed
            suite = pkg.find("EvalSuite", m["suite"])
            if suite is None:
                raise DSLValidationError(f"eval-case-synth targets unknown suite {m['suite']!r}")
            case = m.get("case") or {}
            query = case.get("query") or {}
            obj_name = query.get("object")
            if pkg.find("ObjectType", obj_name) is None:
                raise DSLValidationError(f"eval case targets unknown object {obj_name!r}")
            # dedupe: an identical regression already in the suite is a no-op
            for existing in suite.spec.queries:
                if existing.query.get("object") == obj_name and \
                        existing.query.get("filter") == query.get("filter"):
                    break
            else:
                from ..core.models import QueryCase, QueryExpectation

                suite.spec.queries = [*suite.spec.queries, QueryCase(
                    name=case.get("name") or f"synth-{obj_name}",
                    query=query,
                    expect=QueryExpectation(**(case.get("expect") or {})),
                )]
        else:
            raise DSLValidationError(f"unknown mutation {kind!r}")
    return pkg


def write_package(pkg: OntologyPackage) -> None:
    """Persist mutated resources back to their YAML files."""
    for res in pkg.resources:
        key = (res.kind, res.metadata.name)
        path = pkg.files.get(key)
        if path is None:
            subdir = {
                "ObjectType": "objects", "LinkType": "links", "Action": "actions",
                "Function": "functions", "PolicySet": "policies", "Store": "stores",
                "Projection": "projections", "EvalSuite": "evals",
            }.get(res.kind)
            if subdir is None:
                continue
            path = Path(pkg.root) / subdir / f"{res.metadata.name}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
        payload = res.model_dump(mode="json", by_alias=True, exclude_none=True)
        path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


GRADUATION_STREAK = 10  # "ten consecutive clean promotions" (evolution-loop §5)


async def graduation_streak(session, kind: str) -> int:
    """Direction B3: how long the current clean-promotion streak of a mutation
    class is. Walking the newest proposals backwards, every `promoted` entry
    carrying the class extends the streak; anything else breaks it."""
    rows = (await session.execute(
        select(ProposalRow).where(ProposalRow.diff.isnot(None))
        .order_by(ProposalRow.id.desc()).limit(500)
    )).scalars().all()
    streak = 0
    for row in rows:
        kinds = {m.get("mutation") for m in (row.diff or []) if isinstance(m, dict)}
        if kind not in kinds:
            continue
        if row.status == "promoted":
            streak += 1
        else:
            break
    return streak
