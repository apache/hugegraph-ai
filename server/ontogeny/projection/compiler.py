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
"""Projection schema compiler: DSL -> HugeGraph schema (ARCHITECTURE §7.2).

Derived, final-consistent, rebuildable: the graph is an index, never a source
of truth. Only whitelisted properties enter; marked properties are rejected by
validate() before we ever get here.
"""
from __future__ import annotations

from typing import Any

_TYPE_MAP = {
    "string": "TEXT", "enum": "TEXT", "integer": "INT", "decimal": "DOUBLE",
    "boolean": "BOOLEAN", "date": "DATE", "timestamp": "DATE",
}


def compile_projection(compiled, projection) -> dict[str, Any]:
    include = projection.spec.include
    propertykeys: dict[str, str] = {}

    def need(name: str, dsl_type: str) -> None:
        if name not in propertykeys:
            propertykeys[name] = _TYPE_MAP.get(dsl_type, "TEXT")

    vertexlabels: list[dict[str, Any]] = []
    for object_type, cfg in include.objects.items():
        obj = compiled.objects[object_type]
        pk = obj.spec.primaryKey[0]
        props = [pk]
        for prop in cfg.properties:
            pdef = obj.spec.properties[prop]
            need(prop, pdef.ptype().kind)
            props.append(prop)
        need(pk, obj.spec.properties[pk].ptype().kind)
        vertexlabels.append({
            "label": object_type,
            "primary_keys": [pk],
            "properties": sorted(set(props)),
            "id_strategy": "PRIMARY_KEY",
        })

    edgelabels: list[dict[str, Any]] = []
    for link_name in include.links:
        lnk = compiled.links[link_name]
        # A projection edge carries no whitelisted properties, so there is no
        # sort key to tell parallel edges apart -- HugeGraph rejects MULTIPLE
        # with "must contain sortKeys", leaving SINGLE as the only legal (and
        # the wanted) frequency: repeated join rows for one pair collapse.
        edgelabels.append({
            "name": link_name,
            "source_label": lnk.spec.source,
            "target_label": lnk.spec.target,
            "frequency": "SINGLE",
            "properties": [],
        })

    indexes = [
        {"label": ix.object, "property": ix.property}
        for ix in projection.spec.indexes
    ]
    return {
        "graph": projection.spec.graph,
        "propertykeys": [{"name": n, "data_type": t} for n, t in sorted(propertykeys.items())],
        "vertexlabels": vertexlabels,
        "edgelabels": edgelabels,
        "indexes": indexes,
    }
