# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Ontology -> extraction schema.

This is the contract the agent sees, and the reason the extractor never invents
its own schema: labels are ObjectType names, properties are the ontology's own
property names (optionally renamed by ``backing.mapping``), and the id strategy
tells the extractor whether a primary key is available in the text.

The output is a neutral graph-extraction contract (vertex labels, edge labels
and typed property keys) that any external agent can consume. It is never
created on a graph server -- it is a request/response contract, not DDL.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from ..core.models import ExtractCfg, ExtractedJoin, ObjectTypeResource

_TYPE_MAP: dict[str, str] = {
    "string": "TEXT",
    "enum": "TEXT",
    "media": "TEXT",
    "document": "TEXT",
    "geo-point": "TEXT",
    "geo-shape": "TEXT",
    "integer": "LONG",
    "decimal": "DOUBLE",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "timestamp": "DATE",
}

#: types an extraction prompt cannot reliably produce; excluded from the
#: schema so the model is never asked for them
_UNSUPPORTED = {"struct", "vector"}


@dataclass
class SchemaBundle:
    schema: dict[str, Any]
    #: extraction field name -> ontology property, per object type
    fields: dict[str, dict[str, str]] = field(default_factory=dict)
    #: ontology property -> extraction field, per object type
    reverse: dict[str, dict[str, str]] = field(default_factory=dict)
    #: label -> object type (currently identical, kept explicit for the binder)
    labels: dict[str, str] = field(default_factory=dict)
    #: link label -> LinkType name
    link_labels: dict[str, str] = field(default_factory=dict)
    #: object types that are referenced (resolved to existing rows), never created
    references: set[str] = field(default_factory=set)

    @property
    def hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.schema, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()


def _describe(obj: ObjectTypeResource, prop: str) -> str:
    d = obj.spec.properties[prop]
    bits: list[str] = []
    if d.display:
        bits.append(str(d.display))
    if d.description:
        bits.append(str(d.description))
    t = d.ptype()
    if t.kind == "enum":
        bits.append("one of: " + ", ".join(t.enum_values))
    if t.kind in ("date", "timestamp"):
        bits.append("ISO-8601 date/time")
    if t.kind == "decimal":
        bits.append("decimal number")
    if d.required:
        bits.append("required")
    return "; ".join(bits)


def _compile_object(
    obj: ObjectTypeResource,
    cfg: ExtractCfg,
    object_id: int,
    selected: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, str], list[str]]:
    props = obj.spec.properties
    if selected is not None:
        unknown = sorted(selected - set(props))
        if unknown:
            raise ValueError(f"{obj.metadata.name}: unknown extraction properties {unknown}")
    pk = obj.spec.primaryKey[0]
    mapping = obj.spec.backing.mapping if obj.spec.backing is not None else {}
    # a declared key that does not contain the primary key means the PK is
    # system-generated (a UUID/slug): the corpus must NOT invent it, and the
    # binder derives it from the key instead
    system_pk = bool(cfg.key) and pk not in cfg.key
    # identity/match fields are needed even when the user only selected one
    # output property: without them the binder cannot key the row
    mandatory = {pk, *cfg.key, *cfg.match}
    included: list[str] = []
    for name, d in props.items():
        if name == pk and system_pk:
            continue
        if d.derived is not None:
            continue
        if selected is not None and name not in selected and name not in mandatory:
            continue
        # identity/match fields are needed even when the system of record owns
        # them: they are read for resolution, never written back
        if (
            d.owner == "source"
            and not cfg.include_source
            and name != pk
            and name not in cfg.key
            and name not in cfg.match
            and (selected is None or name not in selected)
        ):
            continue
        kind = d.ptype().kind
        if kind in _UNSUPPORTED:
            continue
        included.append(name)
    if pk not in included and not system_pk:
        included.insert(0, pk)
    if not included:
        raise ValueError(f"{obj.metadata.name}: no extractable properties; check owner/derived declarations")

    fields: dict[str, str] = {}
    reverse: dict[str, str] = {}
    for name in included:
        fname = str(mapping.get(name, name))
        # field names must be unique: a rename colliding with a real property
        # would make the extractor unable to tell them apart
        if fname in fields and fields[fname] != name:
            raise ValueError(f"{obj.metadata.name}: extraction field {fname!r} is used by two properties")
        fields[fname] = name
        reverse[name] = fname

    if system_pk:
        first_key = cfg.key[0]
        if first_key not in reverse:
            raise ValueError(f"{obj.metadata.name}: extract.key {first_key!r} is not an extractable property")
        primary_keys = [reverse[first_key]]
        id_strategy = "CUSTOMIZE_STRING"
    else:
        primary_keys = [reverse[pk]]
        id_strategy = "PRIMARY_KEY"
    label = {
        "id": object_id,
        "name": obj.metadata.name,
        "id_strategy": id_strategy,
        "primary_keys": primary_keys,
        "properties": [reverse[name] for name in included],
        "nullable_keys": [reverse[name] for name in included if name != pk and not props[name].required],
        "description": " | ".join(x for x in (obj.metadata.description, obj.metadata.display) if x)
        or obj.metadata.name,
    }
    # a CUSTOMIZE_STRING label must still carry a non-empty primary_keys for the
    # schema-shape check; the extractor ignores it under that strategy
    return label, fields, reverse, included


def _compile_reference(
    obj: ObjectTypeResource, cfg: ExtractCfg, object_id: int
) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    """A DB-backed type the corpus may *point at* (resolve, never create)."""
    props = obj.spec.properties
    pk = obj.spec.primaryKey[0]
    wanted = [pk]
    for name in [*cfg.match, *cfg.key]:
        if name not in wanted and name in props and props[name].derived is None:
            wanted.append(name)
    mapping = obj.spec.backing.mapping if obj.spec.backing is not None else {}
    fields: dict[str, str] = {}
    reverse: dict[str, str] = {}
    for name in wanted:
        fname = str(mapping.get(name, name))
        if fname in fields and fields[fname] != name:
            raise ValueError(f"{obj.metadata.name}: extraction field {fname!r} is used by two properties")
        fields[fname] = name
        reverse[name] = fname
    # a reference is identified by its natural key (usually name), not by a
    # system id: the model cannot know supplier_id from a memo
    natural = (cfg.match or cfg.key or [pk])[0]
    label = {
        "id": object_id,
        "name": obj.metadata.name,
        "id_strategy": "CUSTOMIZE_STRING",
        "primary_keys": [reverse.get(natural, reverse[pk])],
        "properties": [reverse[name] for name in wanted],
        "nullable_keys": [reverse[name] for name in wanted],
        "description": (
            f"reference to an existing {obj.metadata.name}; do NOT invent one -- "
            "emit it only when the text names an existing record"
        ),
    }
    return label, fields, reverse


def compile_extraction_schema(
    compiled,
    object_types: list[str],
    *,
    reference_types: list[str] | None = None,
    include_links: bool = True,
    properties: dict[str, list[str]] | None = None,
    links: list[str] | None = None,
) -> SchemaBundle:
    names = sorted(dict.fromkeys(object_types))
    refs = sorted(set(reference_types or ()) - set(names))
    if properties is not None:
        unknown = sorted(set(properties) - set(names))
        if unknown:
            raise ValueError(f"scope selects unknown object types {unknown}")
    selected_links = set(links) if links is not None else None
    if selected_links is not None:
        unknown_links = sorted(
            name
            for name in selected_links
            if name not in compiled.links or not isinstance(compiled.links[name].spec.join, ExtractedJoin)
        )
        if unknown_links:
            raise ValueError(f"scope selects unknown/un-extractable links {unknown_links}")
    labels: dict[str, Any] = {}
    fields: dict[str, dict[str, str]] = {}
    reverse: dict[str, dict[str, str]] = {}
    label_map: dict[str, str] = {}
    all_names = names + refs

    for index, name in enumerate(all_names, start=1):
        obj = compiled.objects.get(name)
        if obj is None:
            raise ValueError(f"unknown object type {name!r}")
        if obj.spec.backing is None:
            raise ValueError(f"{name!r} has no backing; it cannot be document-extracted")
        cfg = obj.spec.backing.extract or ExtractCfg()
        if name in refs:
            label, f, r = _compile_reference(obj, cfg, index)
        else:
            selected = set(properties[name]) if properties is not None and name in properties else None
            label, f, r, _included = _compile_object(obj, cfg, index, selected)
        labels[name] = label
        fields[name] = f
        reverse[name] = r
        label_map[name] = name

    propertykeys: dict[str, dict[str, Any]] = {}
    for name in all_names:
        obj = compiled.objects[name]
        for field_name, prop_name in fields[name].items():
            d = obj.spec.properties[prop_name]
            t = d.ptype()
            inner = t.inner if t.kind == "array" else None
            data_type = _TYPE_MAP.get(inner.kind if inner is not None else t.kind)
            if data_type is None:
                continue
            existing = propertykeys.get(field_name)
            entry = {
                "name": field_name,
                "data_type": data_type,
                "cardinality": "LIST" if t.kind == "array" else "SINGLE",
                "description": _describe(obj, prop_name),
            }
            if existing is not None and (
                existing["data_type"] != data_type or existing["cardinality"] != entry["cardinality"]
            ):
                raise ValueError(
                    f"property {field_name!r} is declared with conflicting types across document-backed objects; "
                    "use backing.mapping to give each extraction field a distinct name"
                )
            propertykeys[field_name] = entry

    edgelabels: list[dict[str, Any]] = []
    link_labels: dict[str, str] = {}
    if include_links:
        for index, (link_name, lnk) in enumerate(sorted(compiled.links.items()), start=1):
            if selected_links is not None and link_name not in selected_links:
                continue
            if not isinstance(lnk.spec.join, ExtractedJoin):
                continue
            if lnk.spec.source not in labels or lnk.spec.target not in labels:
                if selected_links is None:
                    # legacy callers compile only the document object types and
                    # let the engine supply references separately
                    continue
                raise ValueError(
                    f"scope link {link_name!r} needs endpoints {lnk.spec.source!r}->{lnk.spec.target!r}; "
                    "select the object type or add the reference endpoint"
                )
            edgelabels.append(
                {
                    "id": index,
                    "name": link_name,
                    "source_label": lnk.spec.source,
                    "target_label": lnk.spec.target,
                    "properties": [],
                }
            )
            link_labels[link_name] = link_name

    schema = {
        "vertexlabels": [labels[n] for n in all_names],
        "edgelabels": edgelabels,
        "propertykeys": [propertykeys[k] for k in sorted(propertykeys)],
    }
    return SchemaBundle(
        schema=schema,
        fields=fields,
        reverse=reverse,
        labels=label_map,
        link_labels=link_labels,
        references=set(refs),
    )
