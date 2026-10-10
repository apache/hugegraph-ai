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
"""Roles and permissions, expressed IN the platform's own policy plane.

The obvious way to build "admin manages roles and permissions" is a roles table
with a permission table next to it — and that would be a second authorization
system, consulted nowhere by the engine, drifting from the Cedar policies that
actually decide every request. So this module does the opposite: it *reads* the
effective grants out of the compiled Cedar and *writes* grants back as Cedar.

    role × action  --compile-->  permit(principal in Role::"R",
                                          action == Action::"A", resource);

Each role gets one **managed** policy set, ``role-<name>.cedar``, regenerated
whole on every save. Hand-written policy sets are never touched: the matrix
shows what they grant, marks it as theirs, and refuses to pretend it can revoke
it (Cedar is additive — a permit cannot be un-granted by another permit).

The practical consequences are the point: a permission an admin toggles is
enforced by the same engine, audited in the same revision stream, versioned by
the same content hash and hot-reloaded by the same publish path as any other
policy. There is exactly one place where authorization is decided.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: Prefix of the policy sets this module owns and regenerates.
MANAGED_PREFIX = "role-"

_ROLE_RE = re.compile(r'Role::"([^"]+)"')
_ACTION_RE = re.compile(r'Action::"([^"]+)"')
_PERMIT_RE = re.compile(r"permit\s*\((.*?)\)\s*(when|unless)?", re.S)


def managed_policy_name(role: str) -> str:
    """The DSL resource name of a role's managed policy set.

    Resource names must be kebab-case, while the role vocabulary allows
    underscores (``maintenance_supervisor``), so the slug maps ``_`` to ``-``.
    That mapping is not injective in theory (``a_b`` and ``a-b`` collide), which
    is why ``slug_conflicts`` exists and the save endpoint refuses an ambiguous
    pair rather than letting one role silently overwrite the other's grants.
    """
    return f"{MANAGED_PREFIX}{role.lower().replace('_', '-')}"


def slug_conflicts(roles: list[str]) -> list[tuple[str, str]]:
    """Role pairs whose managed policy names would collide."""
    seen: dict[str, str] = {}
    out: list[tuple[str, str]] = []
    for role in sorted(roles):
        slug = managed_policy_name(role)
        if slug in seen and seen[slug] != role:
            out.append((seen[slug], role))
        seen.setdefault(slug, role)
    return out


def is_managed(name: str) -> bool:
    return name.startswith(MANAGED_PREFIX)


@dataclass
class Grant:
    """One permit, reduced to the facts the matrix needs."""
    policy: str            # the PolicySet that carries it
    roles: list[str]       # [] means "any authenticated principal"
    actions: list[str]     # [] means "any action"
    conditional: bool      # carries a when/unless clause
    managed: bool          # owned by the role manager (safe to rewrite)


def parse_grants(cedar_texts: dict[str, str]) -> list[Grant]:
    """Every permit in the compiled package, reduced to (roles, actions).

    A regex rather than a Cedar parser on purpose: the matrix only needs to know
    *whether* a role may do an action and *who* says so. Anything the regex
    cannot read stays out of the matrix, and the policy set is still visible in
    full on the Action page's policy tab — so an unusual policy is never hidden,
    only never claimed as manageable.
    """
    out: list[Grant] = []
    for policy, text in sorted(cedar_texts.items()):
        for match in _PERMIT_RE.finditer(text or ""):
            body, condition = match.group(1), match.group(2)
            out.append(Grant(
                policy=policy,
                roles=sorted(set(_ROLE_RE.findall(body))),
                actions=sorted(set(_ACTION_RE.findall(body))),
                conditional=bool(condition),
                managed=is_managed(policy),
            ))
    return out


def compile_role_policy(role: str, actions: list[str], *, site: str | None = None) -> str:
    """The managed Cedar source for one role.

    Deterministic (sorted actions, fixed header) so re-saving an unchanged
    matrix produces a byte-identical file and the content hash does not churn.
    """
    lines = [
        "// 由「角色与权限」页面生成，请勿手工编辑：该文件每次保存都会整体重写。",
        f"// role: {role}" + (f"  site: {site}" if site else ""),
        "",
    ]
    for action in sorted(set(actions)):
        if site:
            # `has site` first: Cedar attribute access must be guarded, and the
            # hand-written policies in this repo follow the same shape
            lines.append(
                f'permit(principal in Role::"{role}", action == Action::"{action}", resource)\n'
                f'when {{ principal has site && principal.site == "{site}" }};'
            )
        else:
            lines.append(
                f'permit(principal in Role::"{role}", action == Action::"{action}", resource);'
            )
    if not actions:
        # An explicit, readable "no grants" file: deleting the permits is the
        # revocation, and a comment explains why the file is otherwise empty.
        lines.append("// 该角色当前没有任何授权（Cedar 未命中 permit 即拒绝）。")
    lines.append("")
    return "\n".join(lines)


def effective_matrix(
    grants: list[Grant], roles: list[str], actions: list[str],
) -> dict[str, dict[str, dict[str, Any]]]:
    """role -> action -> {granted, source, managed, conditional, scope}.

    ``source`` is the policy set that grants it, or ``"*"`` when a permit names
    no role at all (the package default grants it to every principal).
    """
    matrix: dict[str, dict[str, dict[str, Any]]] = {
        role: {action: {"granted": False} for action in actions} for role in roles
    }
    for grant in grants:
        targets = grant.roles or ["*"]
        for role in targets:
            bucket = matrix.setdefault(role, {a: {"granted": False} for a in actions})
            for action in (grant.actions or actions):
                cell = bucket.setdefault(action, {"granted": False})
                # a managed grant wins the label (it is the one an admin owns);
                # otherwise the first hand-written grant is reported
                if cell.get("granted") and cell.get("managed"):
                    continue
                cell.update({
                    "granted": True,
                    "source": grant.policy,
                    "managed": grant.managed,
                    "conditional": grant.conditional,
                    "anyPrincipal": not grant.roles,
                })
    return matrix


def role_catalogue(
    grants: list[Grant], *, user_roles: list[str], declared_roles: list[str],
) -> list[dict[str, Any]]:
    """Every role the deployment knows about, from all three of its sources.

    A role can exist because a policy names it, because a user carries it, or
    because the platform declares the vocabulary (``meta.roles``). The matrix
    must show all three — a role that only exists on a user is exactly the one an
    admin is looking for when nothing works yet.
    """
    seen: dict[str, dict[str, Any]] = {}
    for name in declared_roles:
        seen[name] = {"name": name, "sources": ["vocabulary"]}
    for grant in grants:
        for name in grant.roles:
            entry = seen.setdefault(name, {"name": name, "sources": []})
            if "policy" not in entry["sources"]:
                entry["sources"].append("policy")
    for name in user_roles:
        entry = seen.setdefault(name, {"name": name, "sources": []})
        if "user" not in entry["sources"]:
            entry["sources"].append("user")
    for name, entry in seen.items():
        entry["managedPolicy"] = managed_policy_name(name)
        entry["hasManagedPolicy"] = any(
            g.managed and name in g.roles for g in grants)
    return [seen[k] for k in sorted(seen)]
