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
"""Team-convention lint (dsl-spec §12). Advisory: can be waived per-resource."""
from __future__ import annotations


from .loader import OntologyPackage
from .validator import ValidationReport


def _derived_depth(pkg: OntologyPackage) -> dict[str, int]:
    """Deepest expression-derived chain per object, measured PER PROPERTY.

    The chain rule is about properties reading other derived properties
    (``target.<derived prop>`` inside a derived expression). The old
    object-name-keyed memo could only ever return 1: recursing into the same
    object immediately hit the `seen` guard, so OO-004 never fired on real
    chains (dsl-spec §12's "depth > 2" was a dead rule).
    """
    from . import expr as _expr

    objects = {o.metadata.name: o for o in pkg.objects()}
    depth: dict[tuple[str, str], int] = {}

    def prop_depth(obj_name: str, prop: str, seen: frozenset[tuple[str, str]]) -> int:
        key = (obj_name, prop)
        if key in depth:
            return depth[key]
        obj = objects.get(obj_name)
        pdef = obj.spec.properties.get(prop) if obj is not None else None
        if pdef is None or pdef.derived_kind() != "expr":
            return 0
        if key in seen:
            return 0  # cycle guard (validator flags structural errors already)
        best = 0
        try:
            refs = _expr.analyze(pdef.derived)
        except _expr.ExpressionError:
            refs = set()  # EXPR-PARSE already reports the broken expression
        for root, field in refs:
            if root != "target" or field == prop:
                continue
            other = obj.spec.properties.get(field)
            if other is not None and other.derived_kind() == "expr":
                best = max(best, 1 + prop_depth(obj_name, field, seen | {key}))
        depth[key] = best
        return best

    out: dict[str, int] = {}
    for name, obj in objects.items():
        out[name] = max(
            (1 + prop_depth(name, pname, frozenset())
             for pname, pdef in obj.spec.properties.items() if pdef.derived_kind() == "expr"),
            default=0,
        )
    return out


def lint(pkg: OntologyPackage) -> ValidationReport:
    rep = ValidationReport()
    for r in pkg.resources:
        rid = f"{r.kind}/{r.metadata.name}"
        if not r.metadata.display:
            rep.warn("OO-002", rid, "display name missing")
        if not r.metadata.description:
            rep.warn("OO-003", rid, "description missing (business meaning should be documented)")

    depth = _derived_depth(pkg)
    for name, d in depth.items():
        if d > 2:
            rep.warn("OO-004", f"ObjectType/{name}", f"derived property chain depth {d} > 2")

    for act in pkg.actions():
        has_webhook = any(getattr(e, "kind", None) == "webhook" for e in act.spec.effects)
        if has_webhook and act.spec.audit.fields is None:
            rep.warn(
                "OO-005", f"Action/{act.metadata.name}",
                "webhook effect present but audit.fields not narrowed explicitly",
            )
    return rep
