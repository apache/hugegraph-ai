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
"""Semantic validation: the gate every package (human or machine authored)
must pass before publish (dsl-spec §12).

Two tiers: *errors* block publish; *warnings* are informational. The validator
is pure (no DB) so it runs in CI, in the CLI and inside the evolution
promoter before any auto-merge.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..errors import ExpressionError
from . import expr as _expr
from .loader import OntologyPackage
from .models import (
    ActionResource,
    ArchiveObjectEffect,
    CreateObjectEffect,
    FunctionResource,
    LinkTypeResource,
    ModifyLinkedEffect,
    ModifyTargetEffect,
    ObjectTypeResource,
    SetLinkEffect,
    WebhookEffect,
)

ENV_REF_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
#: An environment reference: UPPER_SNAKE. The platform's own convention for
#: "resolved from the deployment, not from data" (${HUGEGRAPH_URL}, ${ERP_DSN}).
_ENV_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]*")

# The capability vocabulary, mirroring the sandbox boundary exactly: these are
# the RPCs a function's child process may make to its parent (``ontogeny.query``,
# ``ontogeny.llm``) plus the one the platform makes on its behalf (``http``). Anything
# else has no implementation behind it, so declaring it would promise a function
# a power the platform cannot grant.
CAPABILITY_KINDS = ("read-objects", "llm", "http")


@dataclass
class Issue:
    code: str
    severity: str  # 'error' | 'warning'
    resource: str  # "kind/name"
    message: str


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def error(self, code: str, resource: str, message: str) -> None:
        self.issues.append(Issue(code, "error", resource, message))

    def warn(self, code: str, resource: str, message: str) -> None:
        self.issues.append(Issue(code, "warning", resource, message))

    def summary(self) -> str:
        errs = sum(1 for i in self.issues if i.severity == "error")
        return f"{errs} error(s), {len(self.issues) - errs} warning(s)"


def effective_owner(obj: ObjectTypeResource, prop: str) -> str:
    """Property-level ownership (data-layer §7).

    Declared owner wins; derived => ontology; otherwise: source when listed in
    mapping, or when mapping is empty (full same-name direct mapping mode);
    else ontology (safe default: sync never overwrites, actions may write).
    """
    pdef = obj.spec.properties.get(prop)
    if pdef is None or pdef.owner:
        return pdef.owner if pdef and pdef.owner else ("ontology" if pdef else "ontology")
    if pdef.derived:
        return "ontology"
    backing = obj.spec.backing
    if backing is None:
        return "ontology"
    if not backing.mapping:
        return "source"
    return "source" if prop in backing.mapping else "ontology"


def _cedar_roles(pkg: OntologyPackage) -> set[str]:
    """Every role referenced by any policy (Role::"x") -- the vocabulary a
    plugin principal's roles are checked against."""
    import re

    roles: set[str] = set()
    for pol in pkg.policies():
        text = pkg.sidecar_text("PolicySet", pol.metadata.name, pol.spec.source)
        roles.update(re.findall(r'Role::"([A-Za-z0-9_-]+)"', text))
    return roles


def tool_vocabulary(pkg: OntologyPackage) -> set[str]:
    """The complete set of tool names the platform compiles from a package.

    Single source of truth shared by the validator (reference integrity) and
    the agent broker (runtime catalog).
    """
    def snake(n: str) -> str:
        import re
        return re.sub(r"[^a-z0-9_]+", "_", n.strip().lower()).strip("_")

    names = {"describe_ontology", "traverse_graph"}
    names.update(f"search_{snake(o.metadata.name)}" for o in pkg.objects())
    names.update(f"call_{snake(f.metadata.name)}" for f in pkg.functions())
    names.update(f"act_{snake(a.metadata.name)}" for a in pkg.actions())
    return names


def validate(pkg: OntologyPackage) -> ValidationReport:
    rep = ValidationReport()
    objects = {o.metadata.name: o for o in pkg.objects()}
    links = {lnk.metadata.name: lnk for lnk in pkg.links()}
    actions = {a.metadata.name: a for a in pkg.actions()}
    policies = {p.metadata.name: p for p in pkg.policies()}
    stores = {s.metadata.name: s for s in pkg.stores()}
    functions = {f.metadata.name: f for f in pkg.functions()}

    # ---- duplicates -------------------------------------------------------
    seen: set[tuple[str, str]] = set()
    for r in pkg.resources:
        key = (r.kind, r.metadata.name)
        if key in seen:
            rep.error("DUP-NAME", f"{r.kind}/{r.metadata.name}", "duplicate resource name")
        seen.add(key)

    # ---- stores -----------------------------------------------------------
    for s in pkg.stores():
        if not ENV_REF_RE.search(s.spec.connection) and "${" in s.spec.connection:
            rep.error("STORE-ENV", f"Store/{s.metadata.name}", "malformed ${VAR} reference in connection")
        if s.spec.access == "read-write" and s.spec.type not in ("postgres", "sqlite"):
            rep.error(
                "STORE-TX", f"Store/{s.metadata.name}",
                f"read-write requires a transactional store, got {s.spec.type}",
            )

    # ---- objects ----------------------------------------------------------
    for obj in pkg.objects():
        res_id = f"ObjectType/{obj.metadata.name}"
        for pk in obj.spec.primaryKey:
            p = obj.spec.properties.get(pk)
            if p is None:
                rep.error("PK-UNKNOWN", res_id, f"primaryKey {pk!r} is not a property")
            elif not p.required:
                rep.error("PK-REQUIRED", res_id, f"primaryKey {pk!r} must be required")
        b = obj.spec.backing
        if b is not None:
            if b.store not in stores:
                rep.error("BACKING-STORE", res_id, f"unknown store {b.store!r}")
            for prop in b.mapping:
                pdef = obj.spec.properties.get(prop)
                if pdef is None:
                    rep.error("MAPPING-PROP", res_id, f"mapping key {prop!r} is not a property")
                elif pdef.derived:
                    rep.error("MAPPING-DERIVED", res_id, f"derived property {prop!r} cannot appear in mapping")
            if b.sync:
                if b.sync.strategy == "watermark" and not b.sync.watermark:
                    rep.error("SYNC-WATERMARK", res_id, "watermark strategy requires watermark.column")
                if b.sync.strategy == "changelog":
                    rep.warn("SYNC-CHANGELOG", res_id, "changelog strategy requires a runtime Kafka source")
        for pname, pdef in obj.spec.properties.items():
            if pdef.derived_kind() == "expr":
                try:
                    _expr.analyze(pdef.derived)
                except ExpressionError as exc:
                    rep.error("EXPR-PARSE", res_id, f"derived expr of {pname}: {exc.message}")
            elif pdef.derived_kind() == "function":
                entry = pdef.derived_entry()
                if not entry or entry.count(":") != 1:
                    rep.error("DERIVED-FN", res_id,
                              f"function-derived {pname}: entry must be 'file.py:function', got {entry!r}")
            if pdef.derived is not None and pdef.owner == "source":
                rep.error("OWNER-DERIVED", res_id, f"derived property {pname} cannot be source-owned")

    # ---- links ------------------------------------------------------------
    for lnk in pkg.links():
        res_id = f"LinkType/{lnk.metadata.name}"
        for side in ("source", "target"):
            name = getattr(lnk.spec, side)
            if name not in objects:
                rep.error("LINK-ENDPOINT", res_id, f"{side} {name!r} is not an ObjectType")
        j = lnk.spec.join  # already a typed union member (pydantic discriminated)
        if j.kind == "foreign-key":
            for k_side, v_side in j.keys.items():
                a_obj, _, a_prop = k_side.partition(".")
                b_obj, _, b_prop = v_side.partition(".")
                for nm, pr, side_label in ((a_obj, a_prop, k_side), (b_obj, b_prop, v_side)):
                    tgt = objects.get(nm)
                    if tgt is None:
                        rep.error("LINK-KEY", res_id, f"join key {side_label!r} references unknown object {nm!r}")
                        continue
                    if pr not in tgt.spec.properties:
                        rep.error("LINK-KEY", res_id, f"join key {side_label!r}: {nm} has no property {pr!r}")
                ta, tb = objects.get(a_obj), objects.get(b_obj)
                if ta and tb:
                    pa, pb = ta.spec.properties.get(a_prop), tb.spec.properties.get(b_prop)
                    if pa and pb and pa.type != pb.type:
                        rep.error(
                            "LINK-KEY-TYPE", res_id,
                            f"join key types differ: {a_prop}:{pa.type} vs {b_prop}:{pb.type}",
                        )
        else:
            if j.store not in stores:
                rep.error("LINK-STORE", res_id, f"join-table references unknown store {j.store!r}")
            for side_name, mapping in j.keys.items():
                if side_name not in ("source", "target"):
                    # an unknown side used to crash validate() outright
                    # (AttributeError), taking the whole publish/import gate
                    # with it instead of producing this report entry.
                    rep.error("LINK-KEY", res_id,
                              f"join-table keys side {side_name!r} must be 'source' or 'target'")
                    continue
                obj_name = getattr(lnk.spec, side_name)
                tgt = objects.get(obj_name)
                if tgt is None:
                    continue
                for prop in mapping:
                    if prop not in tgt.spec.properties:
                        rep.error("LINK-KEY", res_id, f"{side_name} key {prop!r} not a property of {obj_name}")

    # ---- actions ----------------------------------------------------------
    for act in pkg.actions():
        res_id = f"Action/{act.metadata.name}"
        target = objects.get(act.spec.target)
        if target is None:
            rep.error("ACTION-TARGET", res_id, f"target {act.spec.target!r} is not an ObjectType")
            continue
        _validate_action_against(pkg, rep, act, target, objects, links, policies, functions)

    # ---- functions --------------------------------------------------------
    for fn in pkg.functions():
        res_id = f"Function/{fn.metadata.name}"
        for cap in fn.spec.capabilities:
            keys = set(cap.model_dump(exclude_none=True).keys())
            bad = keys - set(CAPABILITY_KINDS)
            if bad:
                rep.error("FN-CAP", res_id, f"unknown capability keys {sorted(bad)}")
        for issue in _validate_function_body(fn):
            rep.error(issue[0], res_id, issue[1])

    # ---- projections ------------------------------------------------------
    #
    # A domain owns exactly one graph, and it is named after the domain: the
    # package's English name, snake-cased. Two domains pointing at one graph
    # would read each other's vertices, and one domain scattered across several
    # graphs has no single answer to "is my graph up to date?" -- so this is an
    # error, not a warning, and the message states the name to use.
    from ..registry.compiled import domain_graph_name

    expected_graph = domain_graph_name(pkg.manifest.metadata.name)
    for prj in pkg.projections():
        res_id = f"Projection/{prj.metadata.name}"
        if prj.spec.graph != expected_graph:
            rep.error(
                "PROJ-GRAPH-NAME", res_id,
                f"graph {prj.spec.graph!r} must be the domain's own name "
                f"{expected_graph!r} (graph and domain are one-to-one)",
            )
        inc = prj.spec.include
        for obj_name, cfg in inc.objects.items():
            obj = objects.get(obj_name)
            if obj is None:
                rep.error("PROJ-OBJECT", res_id, f"included object {obj_name!r} does not exist")
                continue
            for prop in cfg.properties:
                pdef = obj.spec.properties.get(prop)
                if pdef is None:
                    rep.error("PROJ-WHITELIST", res_id, f"{obj_name}.{prop} is not a property")
                elif pdef.marking:
                    rep.error("PROJ-MARKING", res_id, f"{obj_name}.{prop} carries marking {pdef.marking!r}; marked properties must not enter the graph")
        for lnk in inc.links:
            if lnk not in links:
                rep.error("PROJ-LINK", res_id, f"included link {lnk!r} does not exist")
            else:
                lres = links[lnk]
                for side in ("source", "target"):
                    if getattr(lres.spec, side) not in inc.objects:
                        rep.error(
                            "PROJ-LINK-ENDPOINT", res_id,
                            f"link {lnk!r} {side} {getattr(lres.spec, side)!r} is not included in the projection",
                        )

    # ---- eval suites ------------------------------------------------------
    for suite in pkg.eval_suites():
        res_id = f"EvalSuite/{suite.metadata.name}"
        for q in suite.spec.queries:
            obj_name = str(q.query.get("object", ""))
            if obj_name not in objects:
                rep.error("EVAL-REF", res_id, f"query case {q.name!r}: unknown object {obj_name!r}")
        for r in suite.spec.replays:
            if r.action not in actions:
                rep.error("EVAL-REF", res_id, f"replay references unknown action {r.action!r}")

    # ---- evolution policy ---------------------------------------------------
    evo = pkg.evolution_policy()
    if evo is not None:
        t3 = evo.spec.tiers.get("t3-human-only")
        if t3 is None or not t3.mutations:
            rep.warn("EVO-T3", "EvolutionPolicy/default", "t3-human-only mutation list is empty")
    # ---- agent plugins -----------------------------------------------------
    vocab = tool_vocabulary(pkg)
    known_roles = _cedar_roles(pkg)
    for plug in pkg.agent_plugins():
        res_id = f"AgentPlugin/{plug.metadata.name}"
        spec = plug.spec
        pid = (spec.principal.id or "").strip()
        if not pid:
            rep.error("AGENT-PRINCIPAL", res_id, "principal.id must be a non-empty string")
        elif not pid.startswith("agent:"):
            rep.warn("AGENT-PRINCIPAL", res_id,
                     f'principal.id {pid!r} does not follow the "agent:<name>" convention')
        for role in sorted(set(spec.principal.Role) | set(spec.principal.roles)):
            if role not in known_roles:
                rep.error("AGENT-ROLE-UNKNOWN", res_id,
                          f"principal role {role!r} is not referenced by any policy "
                          "(Role::\"...\") -- a typo here silently grants nothing")
        allow, deny = set(spec.tools.allow), set(spec.tools.deny)
        for t in sorted(allow | deny):
            if t not in vocab:
                rep.error("AGENT-TOOL-UNKNOWN", res_id, f"tool {t!r} is not in the compiled catalog")
        for t in sorted(allow & deny):
            rep.error("AGENT-TOOL-CONFLICT", res_id, f"tool {t!r} appears in both allow and deny")
        writes = spec.tools.allow
        if spec.approval.writes == "never" and any(t.startswith("act_") for t in writes):
            rep.warn("AGENT-APPROVAL", res_id,
                     "approval.writes=never but act_* tools are allowed; writes will be refused")
        if spec.approval.writes == "auto":
            autos = set(spec.approval.auto_actions)
            if not autos:
                rep.error("AGENT-APPROVAL", res_id,
                          "approval.writes=auto requires a non-empty auto_actions list")
            for t in sorted(autos):
                if not t.startswith("act_"):
                    rep.error("AGENT-APPROVAL", res_id,
                              f"auto_actions entry {t!r} must be an act_* tool")
                elif t not in allow:
                    rep.error("AGENT-APPROVAL", res_id,
                              f"auto_actions entry {t!r} is not in tools.allow")
        if spec.principal.markings:
            rep.warn("AGENT-MARKING", res_id,
                     f"plugin principal holds markings {spec.principal.markings}: "
                     "data carrying those markings will be VISIBLE to this agent")
        b = spec.budget
        if b.steps <= 0 or b.wall_ms <= 0 or b.writes_per_session < 0:
            rep.error("AGENT-BUDGET", res_id, "budget fields must be positive (writes_per_session >= 0)")
        eng = spec.engine
        if eng.kind == "external-push":
            ep = (eng.endpoint or "").strip()
            if not ep.startswith(("http://", "https://")):
                rep.error("AGENT-ENGINE-ENDPOINT", res_id,
                          "engine.kind=external-push requires an http(s) endpoint")
            # the platform-side drive loop for push engines is not implemented
            # yet: the fields validate and round-trip, but /run refuses the
            # kind. Say so at package-check time, not at first drive.
            rep.warn("AGENT-ENGINE-UNIMPLEMENTED", res_id,
                     "engine.kind=external-push is declared but not implemented "
                     "in this release: the platform will not drive this plugin "
                     "(use external-pull or builtin-llm)")

    return rep


def _validate_function_body(fn: FunctionResource) -> list[tuple[str, str]]:
    """Rules for the body itself: an entry file, or a coherent pipeline.

    The interesting one is capability coverage. A declarative function's steps
    are readable intent, so the validator can refuse a step the declaration does
    not permit *before* anything runs — the same guarantee the sandbox gives at
    call time, delivered at publish time instead.
    """
    out: list[tuple[str, str]] = []
    spec = fn.spec

    if spec.runtime == "python":
        if not spec.entry or ":" not in spec.entry:
            out.append(("FN-ENTRY", "runtime=python needs entry 'file.py:function'"))
        if spec.steps:
            out.append(("FN-BODY", "steps are only meaningful for runtime=declarative"))
        return out

    # ---- declarative ------------------------------------------------------
    if spec.entry:
        out.append(("FN-ENTRY", "runtime=declarative has no file; remove 'entry'"))
    if not spec.steps:
        out.append(("FN-STEPS", "runtime=declarative needs at least one step"))

    declared = {k for cap in spec.capabilities
                for k in cap.model_dump(exclude_none=True).keys()}
    read_ok = {o for cap in spec.capabilities
               for o in (cap.model_dump(exclude_none=True).get("read-objects") or [])}
    http_ok: list[str] = []
    for cap in spec.capabilities:
        cfg = cap.model_dump(exclude_none=True).get("http")
        if isinstance(cfg, dict):
            http_ok += [str(h) for h in (cfg.get("allow") or [])]

    seen: set[str] = set()
    for i, step in enumerate(spec.steps):
        if step.id in seen:
            out.append(("FN-STEP-ID", f"duplicate step id {step.id!r}"))
        seen.add(step.id)
        if step.kind == "read":
            if not step.object:
                out.append(("FN-STEP", f"step {step.id!r}: read needs 'object'"))
            elif step.object not in read_ok:
                out.append(("FN-STEP-CAP",
                            f"step {step.id!r} reads {step.object!r}, which read-objects "
                            f"does not include (declared: {sorted(read_ok)})"))
        elif step.kind == "llm":
            if not step.prompt:
                out.append(("FN-STEP", f"step {step.id!r}: llm needs 'prompt'"))
            if "llm" not in declared:
                out.append(("FN-STEP-CAP",
                            f"step {step.id!r} calls the model but the function does not "
                            "declare the llm capability"))
        elif step.kind == "http":
            if not step.url:
                out.append(("FN-STEP", f"step {step.id!r}: http needs 'url'"))
            if "http" not in declared:
                out.append(("FN-STEP-CAP",
                            f"step {step.id!r} calls an endpoint but the function does not "
                            "declare the http capability"))
            elif not http_ok:
                out.append(("FN-STEP-CAP",
                            f"step {step.id!r}: the http capability allows no hosts; "
                            "add http: {allow: [host]}"))
            elif step.url:
                # a literal host can be checked here; a ${ref} host is checked at
                # call time (the runtime refuses anything not on the list)
                host = re.match(r"https?://([^/]+)", step.url)
                if host:
                    h = host.group(1).split("@")[-1].split(":")[0]
                    if not any(h == a or h.endswith("." + a.lstrip(".")) for a in http_ok):
                        out.append(("FN-STEP-CAP",
                                    f"step {step.id!r}: host {h!r} is not in the http "
                                    f"allowlist {http_ok}"))

    if spec.returns_step and spec.returns_step not in {s.id for s in spec.steps}:
        out.append(("FN-RETURNS", f"returns_step {spec.returns_step!r} is not a step"))

    # References must point at something that exists by the time it is used.
    # Two kinds share the syntax, and the convention is already the platform's
    # (``${HUGEGRAPH_URL}``, ``${ERP_DSN}``): UPPER_SNAKE names are DEPLOYMENT
    # references, resolved from the environment at call time; everything else is
    # a parameter or an earlier step. Without this split an http step could not
    # name an environment-specific host at all, which is the normal case.
    known = set(spec.parameters)
    for step in spec.steps:
        for ref in _step_refs(step):
            if _ENV_NAME_RE.fullmatch(ref) or ref in known:
                continue
            out.append(("FN-REF",
                        f"step {step.id!r} references ${{{ref}}}, which is neither a "
                        f"parameter nor an earlier step (known: {sorted(known)})"))
        known.add(step.id)
    return out


def _step_refs(step) -> list[str]:
    """Every ``${ref}`` a step interpolates, in order of appearance."""
    found: list[str] = []
    for value in (step.prompt, step.system, step.url, step.filter, step.body, step.headers):
        for text in _strings(value):
            found += [m.group(1) for m in re.finditer(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", text)]
    return found


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for k, v in value.items():
            out += _strings(k) + _strings(v)
        return out
    if isinstance(value, list):
        out = []
        for v in value:
            out += _strings(v)
        return out
    return []


def _validate_action_against(
    pkg: OntologyPackage,
    rep: ValidationReport,
    act: ActionResource,
    target: ObjectTypeResource,
    objects: dict[str, ObjectTypeResource],
    links: dict[str, LinkTypeResource],
    policies: dict[str, str],
    functions: dict[str, FunctionResource],
) -> None:
    res_id = f"Action/{act.metadata.name}"
    spec = act.spec

    # policy decidability
    if spec.policy is not None:
        if spec.policy not in policies:
            rep.error("ACTION-POLICY", res_id, f"policy {spec.policy!r} is not a PolicySet")
    elif "default" not in policies:
        rep.error("ACTION-POLICY", res_id, "no policy set and no package default PolicySet 'default'")

    if spec.execution is not None and spec.execution.entry.count(":") != 1:
        rep.error("ACTION-EXEC", res_id, f"execution.entry must be 'file.py:function', got {spec.execution.entry!r}")

    def check_set(mapping: dict[str, str], obj_res: ObjectTypeResource, label: str,
                  *, check_owner: bool = True) -> None:
        for prop, value_expr in mapping.items():
            pdef = obj_res.spec.properties.get(prop)
            if pdef is None:
                rep.error("ACTION-PROP", res_id, f"{label} sets unknown property {prop!r}")
                continue
            if pdef.derived:
                rep.error("ACTION-DERIVED", res_id, f"{label} cannot set derived property {prop!r}")
            if check_owner and effective_owner(obj_res, prop) != "ontology":
                rep.error(
                    "ACTION-OWNER", res_id,
                    f"{label} sets source-owned property {prop!r} (owner must be ontology)",
                )
            _static_expr(rep, res_id, value_expr, spec, target, objects, allow_enum_literal=True)

    for eff in spec.effects:
        # `when` is evaluated at run time (twice: effect gate + outbox gate) but
        # used to escape static analysis entirely, so a typo like
        # `target.prioraty` only surfaced as a runtime 422. Rules get
        # EXPR-PARSE/EXPR-PATH protection; conditions deserve the same.
        when = getattr(eff, "when", None)
        if when is not None:
            _static_expr(rep, res_id, when, spec, target, objects)
        if isinstance(eff, ModifyTargetEffect):
            check_set(eff.set, target, "modify-target")
        elif isinstance(eff, ModifyLinkedEffect):
            lnk = links.get(eff.link)
            if lnk is None:
                rep.error("ACTION-LINK", res_id, f"modify-linked references unknown link {eff.link!r}")
            else:
                other = lnk.spec.target if lnk.spec.source == spec.target else lnk.spec.source
                other_obj = objects.get(other)
                if other_obj is not None:
                    check_set(eff.set, other_obj, f"modify-linked({eff.link})")
        elif isinstance(eff, CreateObjectEffect):
            # Same unknown-prop/derived checks as modify-target (a create that
            # sets a derived property silently drops the value -- no column).
            # Owner is deliberately NOT checked: creating a row seeds it, the
            # same way a sync insert seeds every property; ownership governs
            # later updates, where the modify-target branch enforces it.
            check_set(eff.properties, target, "create-object", check_owner=False)
            for pk in target.spec.primaryKey:
                if pk not in eff.properties:
                    rep.error("ACTION-PK", res_id, f"create-object must set primaryKey {pk!r}")
        elif isinstance(eff, SetLinkEffect):
            lnk = links.get(eff.link)
            if lnk is None:
                rep.error("ACTION-LINK", res_id, f"set-link references unknown link {eff.link!r}")
            elif spec.target not in (lnk.spec.source, lnk.spec.target):
                rep.error("ACTION-LINK-TARGET", res_id, f"set-link link {eff.link!r} is not attached to target")
        elif isinstance(eff, ArchiveObjectEffect):
            pass
        elif isinstance(eff, WebhookEffect):
            # A URL typo used to be invisible: delivery resolves ${VAR} later and
            # a failure is "consumed with prejudice" (logged, not retried), so
            # the action kept succeeding while the outside world never heard
            # anything. Refuse the shape at publish time; whether the HOST is
            # allowed stays a deployment decision (ONTOGENY_WEBHOOK_ALLOWLIST).
            url = (eff.url or "").strip()
            if not url:
                rep.error("ACTION-WEBHOOK-URL", res_id, "webhook effect needs a url")
            elif "${" in url:
                pass  # an environment reference: resolved at delivery
            elif not url.startswith(("http://", "https://")):
                rep.error(
                    "ACTION-WEBHOOK-URL", res_id,
                    f"webhook url {url!r} must be http(s) or a ${{VAR}} reference",
                )

    # rules static analysis
    for rule in spec.rules:
        try:
            paths = _expr.analyze(rule.expr)
        except ExpressionError as exc:
            rep.error("EXPR-PARSE", res_id, f"rule {rule.expr!r}: {exc.message}")
            continue
        _check_paths(rep, res_id, paths, spec, target, objects)


def _static_expr(
    rep: ValidationReport, res_id: str, src: str,
    act_spec, target: ObjectTypeResource, objects: dict[str, ObjectTypeResource],
    *, allow_enum_literal: bool = False,
) -> None:
    if allow_enum_literal:
        bare = _expr.is_bare_identifier(src)
        if bare is not None and bare not in target.spec.properties:
            return  # effect value like `status: OPEN` -- an enum literal, not a reference
    try:
        paths = _expr.analyze(src)
    except ExpressionError as exc:
        rep.error("EXPR-PARSE", res_id, f"expression {src!r}: {exc.message}")
        return
    _check_paths(rep, res_id, paths, act_spec, target, objects)


def _check_paths(
    rep: ValidationReport, res_id: str, paths: set[tuple[str, str]],
    act_spec, target: ObjectTypeResource, objects: dict[str, ObjectTypeResource],
) -> None:
    for root_name, field_name in paths:
        if root_name == "target":
            if field_name not in target.spec.properties:
                rep.error("EXPR-PATH", res_id, f"target.{field_name} is not a property of {target.metadata.name}")
        elif root_name == "parameters":
            if field_name not in act_spec.parameters:
                rep.error("EXPR-PATH", res_id, f"parameters.{field_name} is not a declared parameter")
        elif root_name == "principal":
            pass  # principal attrs come from IdP; cannot be checked statically
