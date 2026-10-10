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
"""Proposers: gap -> DSL mutation diff.

Two implementations sharing one contract:

- ``HeuristicProposer`` -- deterministic template mutations (tests, offline,
  zero-LLM mode). Sync.
- ``DecidingProposer`` -- the LLM *decides* by default: which mutation (if any),
  the property type, and the business metadata; a rule layer then *validates*
  the decision against the mutation catalog and the live schema, and falls back
  to the heuristic proposer when the LLM is absent, fails, or proposes something
  the schema cannot accept. Async.

The constitutional split (evolution-loop §4/§6) is preserved exactly: the LLM's
decision space is bounded by

  1. a closed mutation catalog (add-optional-property | enum-widen -- whatever
     ``apply_mutations`` can mechanically apply and the tier table can price);
  2. post-hoc schema validation (object exists, prop new / enum-widen targets a
     real enum, type parses under the DSL's own type system);
  3. the unchanged selection ladder: deterministic eval, tier classification,
     budgets, constitution surface. The LLM cannot escalate itself.

Unexplainable decisions never enter evaluation: a proposal without a rationale
is discarded. Provenance is kept (``origin``: llm | heuristic) so every promoted
change says who decided.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..core.types import PropertyType

MUTATION_CATALOG = ("add-optional-property", "enum-widen", "rule-tighten", "eval-case-synth")


class Proposer(Protocol):
    def propose(self, gap: dict[str, Any]) -> dict[str, Any] | None: ...


@dataclass
class ProposeOutcome:
    """Everything one round of deciding produced -- the proposal, and just as
    important, the model's reasoning when it did NOT propose (direction A:
    the decline analysis is the most valuable part and must not evaporate)."""

    proposal: dict[str, Any] | None = None
    analysis: str | None = None
    declined: bool = False
    #: the model declined the obvious mutation but offered a better one (e.g.
    #: "widen the priority enum instead of adding a free-text urgency column")
    alternative: dict[str, Any] | None = None
    decline_reason: str | None = None


class HeuristicProposer:
    """Deterministic mutations for well-understood gap kinds."""

    def propose(self, gap: dict[str, Any]) -> dict[str, Any] | None:
        if gap.get("informational"):
            return None
        kind = gap.get("kind")
        if kind == "add-optional-property" and gap.get("object") and gap.get("prop"):
            return {
                "mutations": [{
                    "mutation": "add-optional-property",
                    "object": gap["object"],
                    "prop": gap["prop"],
                    "type": gap.get("type", "string"),
                }],
                "rationale": gap.get("rationale") or f"add {gap.get('prop')} to {gap.get('object')}",
                "origin": "heuristic",
            }
        if kind == "enum-widen" and all(gap.get(k) for k in ("object", "prop", "value")):
            return {
                "mutations": [{
                    "mutation": "enum-widen",
                    "object": gap["object"],
                    "prop": gap["prop"],
                    "value": gap["value"],
                }],
                "rationale": gap.get("rationale") or "widen enum domain",
                "origin": "heuristic",
            }
        return None


def validate_llm_decision(decision: dict[str, Any], gap: dict[str, Any], compiled) -> dict[str, Any] | None:
    """Rule layer over an LLM decision. Returns a clean proposal dict, or None
    with a reason when the decision steps outside its bounded space.

    This is the "可控" in "可控的决策": the catalog, the schema and the type
    system are checked *after* the model answers, never assumed.
    """
    if not isinstance(decision, dict):
        return None
    mutations = decision.get("mutations")
    rationale = decision.get("rationale")
    if not isinstance(mutations, list) or not mutations or not isinstance(rationale, str) or not rationale.strip():
        return None
    clean: list[dict[str, Any]] = []
    for m in mutations:
        if not isinstance(m, dict):
            return None
        kind = m.get("mutation")
        if kind not in MUTATION_CATALOG:
            return None
        if kind == "add-optional-property":
            obj = compiled.objects.get(m.get("object")) if compiled is not None else None
            if obj is None:
                return None  # unknown target object: outside the model's authority
            prop, ptype = m.get("prop"), m.get("type") or "string"
            if not isinstance(prop, str) or not prop or prop.startswith("_"):
                return None
            if prop in obj.spec.properties:
                return None  # already modelled: nothing to add
            try:
                PropertyType.parse(str(ptype))
            except ValueError:
                return None  # not a DSL type: the store could not honour it
            entry: dict[str, Any] = {"mutation": kind, "object": m["object"], "prop": prop, "type": str(ptype)}
            # business metadata is the LLM's most valuable contribution: the
            # human-facing name and meaning shown in every table header
            if isinstance(m.get("display"), str) and m["display"].strip():
                entry["display"] = m["display"].strip()
            if isinstance(m.get("description"), str) and m["description"].strip():
                entry["description"] = m["description"].strip()
            clean.append(entry)
        elif kind == "enum-widen":
            obj = compiled.objects.get(m.get("object")) if compiled is not None else None
            if obj is None:
                return None
            prop, value = m.get("prop"), m.get("value")
            pdef = obj.spec.properties.get(prop) if isinstance(prop, str) else None
            if pdef is None or not pdef.type.startswith("enum[") or not isinstance(value, str) or not value.strip():
                return None
            if value in [v.strip() for v in pdef.type[5:-1].split(",")]:
                return None  # already a member
            clean.append({"mutation": kind, "object": m["object"], "prop": prop, "value": value.strip()})
        elif kind == "rule-tighten":
            # tighten-only by construction: the applier can only APPEND a rule
            act = compiled.actions.get(m.get("action")) if compiled is not None else None
            if act is None:
                return None  # unknown action: outside the model's authority
            expr = m.get("expr")
            if not isinstance(expr, str) or not expr.strip():
                return None
            from ..core import expr as _expr

            try:
                # an empty context verifies BOTH syntax and roots (target /
                # parameters / user / principal): an expression rooted in a
                # name the rule context does not carry can never evaluate
                _expr.evaluate(expr.strip(), _expr.ExprContext())
            except Exception:  # noqa: BLE001 -- malformed/unknown-root: fail closed
                return None
            if any(r.expr.strip() == expr.strip() for r in act.spec.rules):
                return None  # the same tightening is already in force
            entry = {"mutation": kind, "action": m["action"], "expr": expr.strip()}
            if isinstance(m.get("message"), str) and m["message"].strip():
                entry["message"] = m["message"].strip()
            clean.append(entry)
        elif kind == "eval-case-synth":
            suite = compiled.eval_suites.get(m.get("suite")) if compiled is not None else None
            if suite is None:
                return None
            case = m.get("case")
            query = case.get("query") if isinstance(case, dict) else None
            if not isinstance(query, dict) or query.get("object") not in (compiled.objects if compiled else {}):
                return None
            expect = case.get("expect")
            if expect is not None and not isinstance(expect, dict):
                return None
            for existing in suite.spec.queries:
                if existing.query.get("object") == query.get("object") and \
                        existing.query.get("filter") == query.get("filter"):
                    return None  # an identical regression is already on file
            clean.append({"mutation": kind, "suite": m["suite"],
                          "case": {"name": case.get("name") or f"synth-{query['object']}",
                                   "query": query, "expect": expect or {}}})
    if not clean:
        return None
    return {"mutations": clean, "rationale": rationale.strip(), "origin": "llm",
            "analysis": (decision.get("analysis") or "").strip() or None}


class DecidingProposer:
    """LLM-first proposer with a hard rule layer and explicit fallback.

    ``client`` follows the ontogeny.llm ChatClient contract. When it is None (no
    provider extension), when the call fails, or when the model's answer does
    not survive validation, structured gaps fall back to the deterministic
    heuristic -- the loop never blocks on the model, and informational signals
    (which rules alone cannot act on) simply produce no proposal, as before.
    """

    def __init__(self, client=None, fallback: Proposer | None = None) -> None:
        self.client = client
        self.fallback = fallback or HeuristicProposer()
        #: counters surfaced by the API so the console can say honestly what
        #: decided each round: the model, or the fallback
        self.stats = {"llm_decided": 0, "llm_declined": 0, "llm_rejected": 0, "fallback": 0}

    def _prompt(self, gap: dict[str, Any], compiled, memory: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
        target = gap.get("object")
        schema: dict[str, Any] = {}
        if compiled is not None and isinstance(target, str):
            obj = compiled.objects.get(target)
            if obj is not None:
                schema = {p: d.type for p, d in obj.spec.properties.items()}
        gap_view = {k: v for k, v in gap.items() if k != "informational"}
        system = (
            "你是运行本体（operational ontology）的自进化提案器。给你一个适应度信号产生的缺口和目标对象的现有 schema，"
            "由你决定是否值得动手以及动手的具体方案。\n"
            "你只能从封闭的变异目录中选择：\n"
            '  {"mutation": "add-optional-property", "object": "...", "prop": "...", "type": "string|integer|decimal(14,2)|boolean|timestamp|enum[A, B]", "display": "中文名", "description": "一句话业务含义"}\n'
            '  {"mutation": "enum-widen", "object": "...", "prop": "已有枚举属性", "value": "新成员"}\n'
            '  {"mutation": "rule-tighten", "action": "已有动作", "expr": "新规则表达式（只能追加收紧，不能放宽）", "message": "拒绝时的提示"}\n'
            '  {"mutation": "eval-case-synth", "suite": "已有 EvalSuite", "case": {"name": "用例名", "query": {"object": "...", "filter": {...}, "limit": 50}, "expect": {"columns": ["主键"]}}}\n'
            "硬约束（违反即被丢弃）：\n"
            "1) add-optional-property 的 prop 必须是对象尚未建模的新字段；type 必须是合法 DSL 类型；\n"
            "2) enum-widen 的 prop 必须是已存在的枚举属性，value 不得与现有成员重复；\n"
            "3) rule-tighten 的 action 必须已存在；expr 必须是合法规则表达式且与现有规则不同（只能收紧）；\n"
            "4) eval-case-synth 的 suite 必须已存在；query.object 必须已建模；不得与套件中现有用例重复；\n"
            "5) 信息型信号（空结果率/规则拒绝/工具错误）多数时候不值得改 schema——判断确实无需变异时必须 act=false；\n"
            "6) display/description/rationale 用中文写给人看；rationale 一句话说明证据到方案的推理。\n"
            "当你否决（act=false）但确信存在更好的替代变异时，把它放进 alternative 字段（同样受上述目录与硬约束管辖，"
            "规则层会校验；不合法的 alternative 会被丢弃）。\n"
            "只输出严格 JSON：{\"act\": true|false, \"analysis\": \"对信号的分析（中文）\", "
            "\"mutations\": [ ...最多一条... ], \"rationale\": \"...\", \"alternative\": { ...可选... }}"
        )
        user = (f"缺口信号：{gap_view!r}\n目标对象现有属性：{schema!r}\n")
        if memory:
            user += (f"\n历史记忆（此前同类提案被拒，避免重蹈覆辙）：{memory!r}\n")
        user += "请决策。act=false 时 mutations 留空数组。"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    async def propose(self, gap: dict[str, Any], compiled) -> dict[str, Any] | None:
        """Backwards-compatible door: the proposal only."""
        return (await self.propose_full(gap, compiled)).proposal

    async def propose_full(self, gap: dict[str, Any], compiled,
                           memory: list[dict[str, Any]] | None = None) -> ProposeOutcome:
        from ..llm import extract_json

        if self.client is None:
            self.stats["fallback"] += 1
            return ProposeOutcome(proposal=self.fallback.propose(gap))
        try:
            out = await self.client.chat(self._prompt(gap, compiled, memory))
            decision = extract_json(str(out.get("content", "")))
        except Exception:  # noqa: BLE001 -- the model being wrong/late is a normal state
            self.stats["fallback"] += 1
            return ProposeOutcome(proposal=self.fallback.propose(gap),
                                   decline_reason="llm_unavailable")
        if not isinstance(decision, dict):
            self.stats["fallback"] += 1
            return ProposeOutcome(proposal=self.fallback.propose(gap),
                                   decline_reason="llm_unparsable")
        analysis = (decision.get("analysis") or "").strip() or None
        if decision.get("act") is False:
            # the model declined. For INFORMATIONAL signals that veto stands —
            # fuzzy findings are exactly where judgment applies. For a gap the
            # rules have already classified as a concrete schema defect
            # (unmapped filter field, enum overflow) a decline cannot be the
            # last word: the heuristic fallback answers, and the decline is
            # still counted so the model's reluctance is on the record. When
            # the decline carries a validated alternative mutation, it rides
            # along as a second candidate (direction A: the model's judgement
            # is kept, not dropped on the floor).
            self.stats["llm_declined"] += 1
            alternative = None
            alt_raw = decision.get("alternative")
            if isinstance(alt_raw, dict) and alt_raw:
                candidate = validate_llm_decision(
                    {"mutations": [alt_raw], "rationale": decision.get("rationale") or analysis or "alternative"},
                    gap, compiled)
                if candidate is not None:
                    alternative = candidate
            if gap.get("informational"):
                return ProposeOutcome(analysis=analysis, declined=True,
                                       alternative=alternative, decline_reason="model_declined")
            return ProposeOutcome(proposal=self.fallback.propose(gap), analysis=analysis,
                                   declined=True, alternative=alternative,
                                   decline_reason="model_declined_concrete_gap")
        proposal = validate_llm_decision(decision, gap, compiled)
        if proposal is None:
            # the decision stepped outside its bounded space: fall back, and
            # count it -- a model that keeps being rejected is visible in /evolve
            self.stats["llm_rejected"] += 1
            return ProposeOutcome(proposal=self.fallback.propose(gap), analysis=analysis,
                                   decline_reason="decision_rejected_by_rules")
        self.stats["llm_decided"] += 1
        return ProposeOutcome(proposal=proposal, analysis=analysis)
