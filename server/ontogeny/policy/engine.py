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
"""Cedar-subset policy engine (default driver).

Parses the ``permit(...) when { ... }`` statements used by PolicySet files:

    permit(principal, action == Action::"close-work-order", resource);
    permit(principal in Role::"maintenance_supervisor",
           action == Action::"close-work-order", resource)
    when { resource.status != "CLOSED" && principal has site && resource.site == principal.site };

Evaluation is deterministic and default-deny. Conditions are translated to the
platform mini-expr (``&&``->``and``) so there is exactly ONE expression
semantics in the system. If the ``cedarpy`` binding is installed it is
preferred; this pure-Python driver is the portable fallback and CI reference.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..errors import ExpressionError, PolicyDeniedError
from ..core import expr as _expr

_PERMIT_RE = re.compile(
    r"permit\s*\(\s*(?P<principal>[^,]+?)\s*,\s*action\s*==\s*Action::\"(?P<action>[^\"]+)\"\s*,\s*(?P<resource>[^)]*?)s*\)\s*(?:when\s*\{(?P<when>.*?)\}\s*)?;",
    re.DOTALL,
)


@dataclass(frozen=True)
class PermitRule:
    role: str | None  # None = any authenticated principal
    action: str
    when: str | None  # mini-expr after translation


@dataclass(frozen=True)
class PolicyDecision:
    allow: bool
    rule: PermitRule | None = None
    reason: str = ""


def translate_when(cond: str) -> str:
    """Cedar condition -> mini-expr: ``&&``/``||`` to and/or, ``resource`` to
    ``target`` (the platform's single expression semantics)."""
    out = re.sub(r"\bresource\b", "target", cond)
    return out.replace("&&", " and ").replace("||", " or ")


def parse_policy_set(text: str) -> list[PermitRule]:
    rules: list[PermitRule] = []
    for m in _PERMIT_RE.finditer(text):
        principal = m.group("principal").strip()
        role: str | None = None
        rm = re.fullmatch(r'principal in (?:Role|Group)::"([^"]+)"', principal)
        if rm:
            role = rm.group(1)
        elif principal != "principal":
            continue  # unsupported principal clause -> rule skipped (fail closed)
        when = m.group("when")
        rules.append(PermitRule(role=role, action=m.group("action"), when=translate_when(when.strip()) if when else None))
    return rules


class PolicyEngine:
    """Decides principal x action x resource against the package's policy sets."""

    def __init__(self, compiled) -> None:
        self.compiled = compiled
        self._sets: dict[str, list[PermitRule]] = {}
        for name, text in compiled.cedar_texts.items():
            self._sets[name] = parse_policy_set(text)
        if "default" not in self._sets:
            self._sets["default"] = []  # absent default = default-deny

    # ------------------------------------------------------------------ core

    def rules_for(self, action_name: str) -> list[tuple[str, PermitRule]]:
        """Every permit that names this action, across the whole policy store.

        A Cedar policy store is a *set* of policies and any permit grants. This
        engine used to consult only the single set an action names in
        ``spec.policy`` (falling back to ``default``) — a per-action shortcut
        that silently ignores a permit written in any other set. That is exactly
        the case the role manager needs: it generates one policy set per role
        (``role-<name>``), which no action declares, so under the old rule those
        grants were written to disk, compiled, published… and never consulted.

        Unioning is a no-op for packages whose sets do not share an action (the
        example package: no action appears in two sets), and it makes the store
        behave the way Cedar is documented to behave. The action's own set is
        still listed first so a decision's "permit by <set>" reason keeps naming
        the policy its author wrote.
        """
        preferred = "default"
        act = self.compiled.actions.get(action_name)
        if act is not None and act.spec.policy:
            preferred = act.spec.policy
        ordered = [preferred, *(n for n in self._sets if n != preferred)]
        return [
            (name, rule)
            for name in ordered
            for rule in self._sets.get(name, [])
            if rule.action == action_name
        ]

    def decide(self, principal: dict, action_name: str, resource: dict | None) -> PolicyDecision:
        roles = set(principal.get("Role") or principal.get("roles") or [])
        for policy_name, rule in self.rules_for(action_name):
            if rule.role is not None and rule.role not in roles:
                continue
            if rule.when is None:
                return PolicyDecision(True, rule, f"permit by {policy_name} (unconditional)")
            try:
                ok = bool(_expr.evaluate(rule.when, _expr.ExprContext(
                    target=resource or {}, parameters={}, principal=principal,
                )))
            except ExpressionError:
                continue  # malformed condition -> fail closed for this rule
            if ok:
                return PolicyDecision(True, rule, f"permit by {policy_name} (when-clause)")
        return PolicyDecision(False, None, "default deny")

    def authorize(self, principal: dict, action_name: str, resources: list[dict]) -> list[PolicyDecision]:
        return [self.decide(principal, action_name, r) for r in resources]

    def require(self, principal: dict, action_name: str, resource: dict | None) -> PolicyDecision:
        decision = self.decide(principal, action_name, resource)
        if not decision.allow:
            raise PolicyDeniedError(
                f"policy denied {action_name!r} for principal {principal.get('id')!r}: {decision.reason}",
                details={"action": action_name, "principal": principal.get("id")},
            )
        return decision

    # --------------------------------------------------------------- masking

    def mask(self, object_type: str, props: dict, principal: dict) -> dict:
        """Replace marked properties with a sentinel unless the principal holds
        the marking claim (``markings`` set from the IdP token / dev header).

        Applied on READER surfaces — the REST/MCP read path and the graph
        preview. Function bodies are not readers: see the note in
        ``ontogeny.functions.declarative`` for why a function sees real values.
        """
        obj = self.compiled.objects.get(object_type)
        if obj is None:
            return props
        claims = set(principal.get("markings") or ())
        out = dict(props)
        for prop, pdef in obj.spec.properties.items():
            if pdef.marking and pdef.marking not in claims and props.get(prop) is not None:
                out[prop] = "__masked__"
        return out
