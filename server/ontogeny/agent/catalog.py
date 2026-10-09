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
"""The tool catalog: what an agent session may see and call.

Single source of truth for the tool vocabulary. The validator uses
``tool_vocabulary`` (in ontogeny.core.validator) at package-check time; this module
builds the *runtime* catalog from the compiled snapshot and computes the
effective toolset of a plugin:

    effective = catalog ∩ principal_policy ∩ plugin.allow − plugin.deny

The intersection is the whole security model (invariant I1): a plugin can
only narrow, never widen. ``principal_policy`` is evaluated by the same Cedar
engine humans go through -- for read tools we probe cheaply at catalog time;
for write tools the definitive check still happens inside the Action runtime
("policy at the last meter"), so catalog filtering is an UX/safety prefilter,
never the only gate.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ..core.models import AgentPluginResource
from ..registry.compiled import CompiledOntology


@dataclass(frozen=True)
class ToolDef:
    name: str
    kind: str            # meta | search | call | traverse | act
    target: str | None   # object type / action / function name
    description: str
    writes: bool         # act_* only
    input_schema: dict[str, Any]

    def to_meta(self) -> dict[str, Any]:
        return {
            "name": self.name, "kind": self.kind, "target": self.target,
            "description": self.description, "writes": self.writes,
            "input_schema": self.input_schema,
        }


def _snake(name: str) -> str:
    """Same normalization as CompiledOntology.snake (kebab -> snake), so the
    validator's tool_vocabulary and this catalog can never disagree."""
    import re
    return re.sub(r"[^a-z0-9_]+", "_", name.strip().lower()).strip("_")


_FILTER_DSL_DOC = (
    "filter DSL: a leaf is {field, op, value} with op one of "
    "eq ne lt le gt ge in contains isnull; shorthand {a: 1} == a eq 1; "
    "leaves combine as {and: [...]} / {or: [...]} / {not: {...}}"
)


def build_catalog(compiled: CompiledOntology) -> dict[str, ToolDef]:
    """Every tool the ontology compiles, regardless of plugin."""
    tools: dict[str, ToolDef] = {
        "describe_ontology": ToolDef(
            "describe_ontology", "meta", None,
            "Ontology snapshot: object types, actions, functions, projections.",
            False, {"type": "object", "properties": {}, "additionalProperties": False},
        ),
        "traverse_graph": ToolDef(
            "traverse_graph", "traverse", None,
            "Multi-hop traversal over links (path: [{link, direction}, ...]).",
            False, {
                "type": "object",
                "properties": {
                    "start_type": {"type": "string"},
                    "start_ids": {"type": "array", "items": {"type": "string"}},
                    "path": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"link": {"type": "string"}, "direction": {"enum": ["out", "in"]}},
                        "required": ["link", "direction"],
                    }},
                },
                "required": ["start_type", "start_ids", "path"],
            },
        ),
    }
    for name, obj in compiled.objects.items():
        tools[f"search_{_snake(name)}"] = ToolDef(
            f"search_{_snake(name)}", "search", name,
            f"Search {name} objects ({_FILTER_DSL_DOC}).",
            False, {
                "type": "object",
                "properties": {
                    "filter": {"type": "object", "description": _FILTER_DSL_DOC},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
                },
            },
        )
    for name, fn in compiled.functions.items():
        params = {
            p: {"type": d.type, **({"default": d.default} if d.default is not None else {})}
            for p, d in fn.spec.parameters.items()
        }
        required = sorted(p for p, d in fn.spec.parameters.items() if d.required)
        tools[f"call_{_snake(name)}"] = ToolDef(
            f"call_{_snake(name)}", "call", name,
            f"Invoke the {name} function (sandboxed, capability-scoped).",
            False, {
                "type": "object",
                "properties": {"parameters": {"type": "object", "properties": params,
                                              "required": required}},
                "required": ["parameters"],
            },
        )
    for name, act in compiled.actions.items():
        params = {
            p: {"type": d.type, **({"default": d.default} if d.default is not None else {})}
            for p, d in act.spec.parameters.items()
        }
        required = sorted(p for p, d in act.spec.parameters.items() if d.required)
        tools[f"act_{_snake(name)}"] = ToolDef(
            f"act_{_snake(name)}", "act", name,
            f"Execute the {name} action (goes through rules, policy, audit).",
            True, {
                "type": "object",
                "properties": {
                    "parameters": {"type": "object", "properties": params, "required": required},
                    "target_id": {"type": "string"},
                    "expected_revision": {"type": "integer"},
                },
                "required": ["parameters"],
            },
        )
    return tools


def catalog_hash(tools: dict[str, ToolDef]) -> str:
    payload = json.dumps({n: t.to_meta() for n, t in sorted(tools.items())},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def effective_tools(compiled: CompiledOntology, plugin: AgentPluginResource) -> dict[str, ToolDef]:
    """catalog ∩ plugin.allow − plugin.deny (empty allow = all reads, no writes).

    Default posture when ``allow`` is omitted is deliberately conservative:
    describe + search + traverse + call, and NO act_* -- a plugin must list
    every write tool it wants explicitly.
    """
    catalog = build_catalog(compiled)
    allow, deny = set(plugin.spec.tools.allow), set(plugin.spec.tools.deny)
    if not allow:
        allow = {n for n, t in catalog.items() if not t.writes}
    names = (allow & set(catalog)) - deny
    return {n: catalog[n] for n in sorted(names)}
