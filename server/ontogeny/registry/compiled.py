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
"""CompiledOntology: the immutable in-memory snapshot the hot path reads.

The registry compiles a validated package into this structure keyed by
content hash. Query/action/policy paths NEVER touch YAML after publish --
they read this snapshot (zero IO, safe to cache process-wide).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from dataclasses import dataclass, field

from ..core.loader import OntologyPackage
from ..core.models import (
    ActionResource,
    AgentPluginResource,
    EvalSuiteResource,
    EvolutionPolicyResource,
    FunctionResource,
    LinkTypeResource,
    ObjectTypeResource,
    PolicySetResource,
    ProjectionResource,
    StoreResource,
)
from ..core.validator import effective_owner
from ..core.types import PropertyType


def snake(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.strip().lower()).strip("_")


def domain_graph_name(package_name: str) -> str:
    """The one graph name a domain owns: its own English name, snake-cased.

    The projection layer's addressing rule, in one place because three parties
    must agree on it: the validator (which rejects a package whose Projection
    disagrees), the console (which probes HugeGraph for this name before it
    offers to build anything) and the graph client (constructed with it). A
    domain and a graph are one-to-one, deliberately: two domains sharing a graph
    name, or one domain scattering across several, are both ways to end up
    reading another model's data.
    """
    return snake(package_name)


@dataclass(frozen=True)
class CompiledOntology:
    content_hash: str
    package_name: str
    package_root: str
    objects: dict[str, ObjectTypeResource]
    links: dict[str, LinkTypeResource]
    actions: dict[str, ActionResource]
    functions: dict[str, FunctionResource]
    policies: dict[str, PolicySetResource]
    cedar_texts: dict[str, str]
    projections: dict[str, ProjectionResource]
    eval_suites: dict[str, EvalSuiteResource]
    evolution: EvolutionPolicyResource | None
    stores: dict[str, StoreResource]
    agent_plugins: dict[str, AgentPluginResource] = field(default_factory=dict)
    function_versions: dict[str, str] = field(default_factory=dict)

    # -- naming helpers -----------------------------------------------------

    def table_name(self, object_type: str) -> str:
        return f"ontogeny_obj_{snake(object_type)}"

    def link_table(self, link_name: str) -> str:
        return f"ontogeny_lnk_{snake(link_name)}"

    @staticmethod
    def col(prop: str) -> str:
        return snake(prop)

    # -- lookups ------------------------------------------------------------

    def ptype(self, object_type: str, prop: str) -> PropertyType:
        return self.objects[object_type].spec.properties[prop].ptype()

    def owner(self, object_type: str, prop: str) -> str:
        return effective_owner(self.objects[object_type], prop)

    def action_policy_name(self, action: ActionResource) -> str:
        return action.spec.policy or "default"

    def action_target(self, action_name: str) -> str:
        """The object type an action writes to (for approver-side policy checks)."""
        act = self.actions.get(action_name)
        if act is None:
            from ..errors import NotFoundError
            raise NotFoundError(f"unknown action {action_name!r}")
        return act.spec.target

    def links_of(self, object_type: str) -> list[LinkTypeResource]:
        return [
            lnk for lnk in self.links.values()
            if object_type in (lnk.spec.source, lnk.spec.target)
        ]

    def to_meta(self) -> dict:
        """Snapshot export for /meta/ontology, SDK and MCP consumers.

        Every fact the DSL states about a property is exported -- exporting only
        `type`/`required`/`marking` forced consumers to render the machine name
        and the raw DSL syntax (`decimal(14,2)`, `enum[DRAFT, ...]`) to business
        users, with no way to reach the Chinese display name, the business
        description, who owns the field or whether it is derived.
        """
        return {
            "package": self.package_name,
            "content_hash": self.content_hash,
            "objects": {
                name: {
                    "display": r.metadata.display,
                    "primaryKey": r.spec.primaryKey,
                    "properties": {
                        p: {
                            "type": d.type,
                            "required": d.required,
                            "marking": d.marking,
                            "display": d.display,
                            "description": d.description,
                            "owner": d.owner,
                            # kind/entry/triggers only for the function form: the
                            # raw expression is a DSL string consumers would have
                            # to parse, and they only need "is it derived, by
                            # what, and what else invalidates it". The read-time
                            # expression form is exported verbatim, since there
                            # the expression *is* the definition.
                            "derived": (
                                {
                                    "kind": d.derived_kind(),
                                    "expr": d.derived if d.derived_kind() == "expr" else None,
                                    "entry": d.derived_entry(),
                                    "triggers": d.derived_triggers(),
                                }
                                if d.derived_kind()
                                else None
                            ),
                        }
                        for p, d in r.spec.properties.items()
                    },
                    "links": [lnk.metadata.name for lnk in self.links_of(name)],
                    "actions": [
                        a.metadata.name for a in self.actions.values() if a.spec.target == name
                    ],
                }
                for name, r in self.objects.items()
            },
            # LinkType inventory with its direction. `objects[x].links` only says
            # "x is an endpoint", which forces consumers (SDK, MCP, the builder,
            # the ontology canvas) to guess which end is the source — so the
            # snapshot states it outright.
            "linkTypes": {
                name: {
                    "display": r.metadata.display,
                    "source": r.spec.source,
                    "target": r.spec.target,
                    "cardinality": r.spec.cardinality,
                }
                for name, r in self.links.items()
            },
            "actions": {
                name: {
                    "display": r.metadata.display,
                    "target": r.spec.target,
                    "parameters": {
                        p: {"type": d.type, "required": d.required}
                        for p, d in r.spec.parameters.items()
                    },
                }
                for name, r in self.actions.items()
            },
            "functions": {
                name: {
                    "runtime": r.spec.runtime,
                    "entry": r.spec.entry,
                    "parameters": {
                        p: {"type": d.type, "required": d.required}
                        for p, d in r.spec.parameters.items()
                    },
                    # the content version IS the external contract: a caller
                    # pins it and is told when the logic moves. There is no
                    # publish switch -- it never gated anything, and a flag that
                    # only decorates /meta is a promise the platform does not keep.
                    "version": self.function_versions.get(name),
                    # full capability values (not just key names): the dashboard
                    # constellation links a function to the object types it reads
                    "capabilities": [
                        c.model_dump(exclude_none=True) for c in r.spec.capabilities
                    ],
                }
                for name, r in self.functions.items()
            },
            "projections": {
                name: {"engine": r.spec.engine, "graph": r.spec.graph,
                       "objects": list(r.spec.include.objects), "links": list(r.spec.include.links)}
                for name, r in self.projections.items()
            },
            # the role vocabulary the Cedar policies actually reference: an
            # agent plugin principal may only use these (AGENT-ROLE-UNKNOWN
            # otherwise), so client tooling needs the list to pick from
            "roles": sorted({r for text in self.cedar_texts.values()
                             for r in re.findall(r'Role::"([A-Za-z0-9_-]+)"', text)}),
            "policies": {
                name: {"display": r.metadata.display, "source": r.spec.source,
                       "rules": self.cedar_texts.get(name, "").count("permit(")}
                for name, r in self.policies.items()
            },
            "agentPlugins": {
                name: {
                    "display": r.metadata.display,
                    "transport": r.spec.transport.kind,
                    "engine": {"kind": r.spec.engine.kind, "endpoint": r.spec.engine.endpoint},
                    "principal": r.spec.principal.as_principal(),
                    "tools": {"allow": list(r.spec.tools.allow), "deny": list(r.spec.tools.deny)},
                    "approval": {"writes": r.spec.approval.writes,
                                 "auto_actions": list(r.spec.approval.auto_actions)},
                    "budget": {"steps": r.spec.budget.steps, "wall_ms": r.spec.budget.wall_ms,
                               "writes_per_session": r.spec.budget.writes_per_session},
                }
                for name, r in self.agent_plugins.items()
            },
        }


def _read_cedar(pkg: OntologyPackage) -> dict[str, str]:
    return {
        p.metadata.name: pkg.sidecar_text("PolicySet", p.metadata.name, p.spec.source)
        for p in pkg.policies()
    }


def _content_hash(pkg: OntologyPackage) -> str:
    payload = json.dumps(
        [
            [r.kind, r.metadata.name, json.dumps(r.model_dump(mode="json", by_alias=True), sort_keys=True)]
            for r in sorted(pkg.resources, key=lambda r: (r.kind, r.metadata.name))
        ],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _function_versions(pkg: OntologyPackage) -> dict[str, str]:
    """Content version per function: sha256 of its body (first 12 hex chars).

    Published functions can be pinned against this at invoke time, so an external
    caller notices the logic changed under it. For a code function the body is
    its source file; for a declarative one there IS no file — the body is the
    spec — so the spec is hashed instead. Without that second branch a
    declarative function would hash the empty string and every prompt edit would
    keep the same version, silently defeating the pinning it promises.
    """
    versions: dict[str, str] = {}
    root_is_real = bool(str(pkg.root)) and Path(str(pkg.root), "ontology.yaml").is_file()
    for fn in pkg.functions():
        if fn.spec.runtime == "declarative":
            body = json.dumps(
                fn.spec.model_dump(mode="json", exclude_none=True),
                sort_keys=True, ensure_ascii=False,
            )
            versions[fn.metadata.name] = hashlib.sha256(body.encode()).hexdigest()[:12]
            continue
        file, _, _func = fn.spec.entry.partition(":")
        text = pkg.sidecar_text("Function", fn.metadata.name, file) if file else ""
        if not text and not root_is_real:
            continue  # snapshot rebuilt from the DB: no sources, no version claim
        versions[fn.metadata.name] = hashlib.sha256(text.encode()).hexdigest()[:12]
    return versions


def compile_package(pkg: OntologyPackage) -> CompiledOntology:
    return CompiledOntology(
        content_hash=_content_hash(pkg),
        package_name=pkg.manifest.metadata.name,
        package_root=str(pkg.root),
        objects={o.metadata.name: o for o in pkg.objects()},
        links={lnk.metadata.name: lnk for lnk in pkg.links()},
        actions={a.metadata.name: a for a in pkg.actions()},
        functions={f.metadata.name: f for f in pkg.functions()},
        policies={p.metadata.name: p for p in pkg.policies()},
        cedar_texts=_read_cedar(pkg),
        projections={p.metadata.name: p for p in pkg.projections()},
        eval_suites={e.metadata.name: e for e in pkg.eval_suites()},
        evolution=pkg.evolution_policy(),
        stores={s.metadata.name: s for s in pkg.stores()},
        agent_plugins={a.metadata.name: a for a in pkg.agent_plugins()},
        function_versions=_function_versions(pkg),
    )
