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

"""Deterministic binder: extractor subgraph -> ontology objects and edges.

No model here, and no I/O beyond lookups. Everything the extractor produced is
treated as *evidence*: values are coerced to the ontology type, identities are
resolved against live rows, and anything ambiguous becomes a review candidate
instead of a silent merge.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..core.models import ExtractCfg, ExtractedJoin
from ..core.types import PropertyType
from ..errors import TypeMismatchError
from .schema import SchemaBundle

_WS = re.compile(r"\s+")


@dataclass
class Evidence:
    doc_id: str
    chunk_index: int
    quote: str

    def as_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "chunk_index": self.chunk_index, "quote": self.quote}


@dataclass
class BoundObject:
    object_type: str
    object_id: str
    props: dict[str, Any]
    evidence: dict[str, Evidence]
    created: bool
    alternatives: dict[str, list[Any]] = field(default_factory=dict)
    #: the document/chunk that supplied the disagreeing value
    alternative_evidence: dict[str, Evidence] = field(default_factory=dict)
    missing_required: list[str] = field(default_factory=list)
    identity_source: str = "pk"
    #: property -> documents that supplied it (provenance / retraction)
    sources: dict[str, set[str]] = field(default_factory=dict)
    docs: set[str] = field(default_factory=set)
    created_by: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "object_type": self.object_type,
            "object_id": self.object_id,
            "props": _jsonable(self.props),
            "evidence": {k: v.as_dict() for k, v in self.evidence.items()},
            "created": self.created,
            "missing_required": self.missing_required,
            "identity_source": self.identity_source,
        }


@dataclass
class BoundLink:
    link: str
    src_id: str
    dst_id: str
    evidence: Evidence
    out_label: str
    in_label: str
    #: one evidence entry per asserting document, so retraction is per-doc
    sources: dict[str, Evidence] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.link, self.src_id, self.dst_id)

    def payload(self) -> dict[str, Any]:
        return {
            "link": self.link,
            "src_id": self.src_id,
            "dst_id": self.dst_id,
            "source_label": self.out_label,
            "target_label": self.in_label,
            "evidence": self.evidence.as_dict(),
        }


@dataclass
class Candidate:
    kind: str  # object | link
    reason: str
    payload: dict[str, Any]
    doc_id: str
    chunk_index: int
    object_type: str | None = None
    link: str | None = None
    object_id: str | None = None


@dataclass
class Reject:
    object_type: str
    code: str
    reason: str
    source_pk: str | None
    row: dict[str, Any]


@dataclass
class BindOutcome:
    objects: dict[tuple[str, str], BoundObject] = field(default_factory=dict)
    links: dict[tuple[str, str, str], BoundLink] = field(default_factory=dict)
    candidates: list[Candidate] = field(default_factory=list)
    rejected: list[Reject] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    #: (object_type, id) of DB rows the corpus pointed at (never created)
    references: set[tuple[str, str]] = field(default_factory=set)


# --------------------------------------------------------------- coercion


def _canon(value: Any) -> Any:
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _canon(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return value


def _jsonable(value: Any) -> Any:
    return _canon(value)


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, str):
        v = value.strip()
        # currency/thousands separators are common in documents and never
        # meaningful in a numeric ontology property
        if re.fullmatch(r"[-+]?[$€£¥]?\s*\d[\d,]*\.?\d*%?", v):
            v = v.replace(",", "").replace(" ", "")
            for ch in "$€£¥":
                v = v.replace(ch, "")
            if v.endswith("%"):
                try:
                    return float(v[:-1]) / 100.0
                except ValueError:
                    return v
            return v
        return v
    return value


def coerce_value(ptype: PropertyType, value: Any, *, prop: str) -> Any:
    """Coerce with the forgiving normalizations real documents need.

    The platform's own coercion is strict (an enum is an exact match); a model
    reading "High" for `enum[LOW, HIGH]` is not evidence of a schema violation,
    so case/whitespace are normalized *before* validation, never after.
    """
    v = _normalize_scalar(value) if ptype.kind in {"integer", "decimal"} else value
    if v is None:
        return None
    if ptype.kind == "enum" and isinstance(v, str):
        folded = _WS.sub(" ", v).strip()
        for allowed in ptype.enum_values:
            if allowed.casefold() == folded.casefold() or allowed.casefold().replace("_", " ") == folded.casefold():
                return allowed
        raise TypeMismatchError(
            f"property {prop}: {v!r} is not one of {list(ptype.enum_values)}",
            details={"property": prop, "value": repr(value)},
        )
    if ptype.kind == "date" and isinstance(v, str):
        v = v.replace("/", "-").strip()
        if "T" in v:
            v = v.split("T", 1)[0]
    if ptype.kind == "timestamp" and isinstance(v, str):
        v = v.strip().replace("/", "-")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            v = v + "T00:00:00+00:00"
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?", v):
            v = v.replace(" ", "T", 1)
    return ptype.coerce(v, prop=prop)


def _quote(text: str, value: Any) -> str:
    needle = str(value).strip()
    if not needle:
        return ""
    idx = text.casefold().find(needle.casefold())
    if idx < 0:
        # fall back to the sentence carrying the value's first token
        token = needle.split()[0] if needle.split() else needle
        idx = text.casefold().find(token.casefold())
    if idx < 0:
        return ""
    start = max(text.rfind(".", 0, idx), text.rfind("\n", 0, idx), text.rfind("。", 0, idx)) + 1
    end_candidates = [p for p in (text.find(".", idx), text.find("\n", idx), text.find("。", idx)) if p >= 0]
    end = min(end_candidates) + 1 if end_candidates else min(len(text), idx + 240)
    return text[start:end].strip()[:400]


def _valid(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


class Binder:
    def __init__(self, compiled, schema: SchemaBundle, repo, session, *, run_id: int) -> None:
        self.compiled = compiled
        self.schema = schema
        self.repo = repo
        self.session = session
        self.run_id = run_id
        self.out = BindOutcome()
        self._by_vid: dict[tuple[str, str], tuple[str, str]] = {}
        self._by_pk: dict[tuple[str, str], BoundObject] = {}
        self._cfgs: dict[str, ExtractCfg] = {}
        for name in schema.labels:
            obj = compiled.objects[name]
            self._cfgs[name] = obj.spec.backing.extract or ExtractCfg()

    # ------------------------------------------------------------- helpers

    def _evidence(self, doc_id: str, chunk: int, text: str, value: Any) -> Evidence:
        return Evidence(doc_id, chunk, _quote(text, value))

    def _candidate(
        self,
        kind: str,
        reason: str,
        payload: dict[str, Any],
        doc_id: str,
        chunk: int,
        object_type: str | None = None,
        link: str | None = None,
        object_id: str | None = None,
    ) -> None:
        self.out.candidates.append(
            Candidate(kind, reason, payload, doc_id, chunk, object_type=object_type, link=link, object_id=object_id)
        )

    def _reject(self, object_type: str, code: str, reason: str, source_pk: str | None, row: dict[str, Any]) -> None:
        self.out.rejected.append(Reject(object_type, code, reason, source_pk, _jsonable(row)))

    def _map_vertex(self, object_type: str, raw: dict[str, Any], doc_id: str, chunk: int, text: str):
        obj = self.compiled.objects[object_type]
        fields = self.schema.fields[object_type]
        props: dict[str, Any] = {}
        evidence: dict[str, Evidence] = {}
        for field_name, prop in fields.items():
            if field_name not in raw:
                continue
            value = raw.get(field_name)
            if not _valid(value):
                continue
            try:
                props[prop] = coerce_value(obj.spec.properties[prop].ptype(), value, prop=prop)
            except TypeMismatchError as exc:
                self._reject(object_type, "TYPE_MISMATCH", exc.message, None, {"field": field_name, "value": value})
            else:
                evidence[prop] = self._evidence(doc_id, chunk, text, value)
        return props, evidence

    def _identity(
        self, object_type: str, props: dict[str, Any], raw: dict[str, Any]
    ) -> tuple[str | None, str, dict[str, Any]]:
        obj = self.compiled.objects[object_type]
        cfg = self._cfgs[object_type]
        pk = obj.spec.primaryKey[0]
        system_pk = bool(cfg.key) and pk not in cfg.key
        key_props = list(cfg.key) if cfg.key else [pk]
        key_values = {p: props.get(p) for p in key_props}
        if system_pk:
            if any(not _valid(v) for v in key_values.values()):
                return None, "key", key_values
            material = json.dumps(_canon(key_values), sort_keys=True, ensure_ascii=False, default=str)
            return f"{object_type}:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}", "key", key_values
        pk_value = props.get(pk)
        if _valid(pk_value):
            return str(pk_value), "pk", key_values
        if cfg.key and all(_valid(v) for v in key_values.values()):
            material = json.dumps(_canon(key_values), sort_keys=True, ensure_ascii=False, default=str)
            return f"{object_type}:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}", "key", key_values
        return None, "pk", key_values

    async def _resolve(self, object_type: str, props: dict[str, Any]) -> list[str]:
        cfg = self._cfgs[object_type]
        obj = self.compiled.objects[object_type]
        pk = obj.spec.primaryKey[0]
        system_pk = bool(cfg.key) and pk not in cfg.key
        match = list(cfg.match) if cfg.match else ([] if system_pk else [pk])
        values = {p: props.get(p) for p in match if _valid(props.get(p))}
        if not values:
            return []
        return await self.repo.find_by_keys(self.session, object_type, values)

    # ---------------------------------------------------------------- bind

    async def bind(self, packets: list[tuple[Any, dict[str, Any]]]) -> BindOutcome:
        """``packets`` are (packet_row, graph); processed in chunk order."""
        for packet, graph in packets:
            doc_id = packet.doc_id
            chunk = packet.chunk_index
            text = packet.text
            await self._bind_vertices(graph, doc_id, chunk, text)
            await self._bind_edges(graph, doc_id, chunk, text)
        self._check_required()
        self.out.objects = self._by_pk
        return self.out

    async def _bind_vertices(self, graph: dict[str, Any], doc_id: str, chunk: int, text: str) -> None:
        for vertex in graph.get("vertices") or []:
            if not isinstance(vertex, dict):
                continue
            label = vertex.get("label")
            if label not in self.schema.labels:
                self.out.gaps.append(f"unknown label {label!r}")
                continue
            object_type = self.schema.labels[label]
            raw_props = vertex.get("properties") or {}
            if not isinstance(raw_props, dict):
                raw_props = {}
            unknown = [k for k in raw_props if k not in self.schema.fields[object_type]]
            for k in unknown:
                self.out.gaps.append(f"{label}.{k}")
            props, evidence = self._map_vertex(object_type, raw_props, doc_id, chunk, text)
            if object_type in self.schema.references:
                await self._bind_reference(object_type, vertex, props, doc_id, chunk)
                continue
            object_id, id_source, _key_values = self._identity(object_type, props, raw_props)
            if object_id is None:
                self._candidate(
                    "object",
                    "NO_IDENTITY",
                    {"object_type": object_type, "props": _jsonable(props), "raw": _jsonable(vertex)},
                    doc_id,
                    chunk,
                    object_type=object_type,
                )
                continue

            created = True
            matched = await self._resolve(object_type, props)
            if len(matched) > 1:
                self._candidate(
                    "object",
                    "AMBIGUOUS_MATCH",
                    {"object_type": object_type, "candidates": matched, "props": _jsonable(props)},
                    doc_id,
                    chunk,
                    object_type=object_type,
                    object_id=object_id,
                )
                continue
            if len(matched) == 1:
                object_id, created, id_source = matched[0], False, "match"

            bound = self._by_pk.get((object_type, object_id))
            if bound is None:
                bound = BoundObject(object_type, object_id, {}, {}, created, identity_source=id_source)
                bound.created_by = doc_id if created else None
                self._by_pk[(object_type, object_id)] = bound
            bound.docs.add(doc_id)
            for prop, value in props.items():
                bound.sources.setdefault(prop, set()).add(doc_id)
                if prop not in bound.props:
                    bound.props[prop] = value
                    bound.evidence[prop] = evidence.get(prop, Evidence(doc_id, chunk, ""))
                elif bound.props[prop] != value:
                    bound.alternatives.setdefault(prop, [])
                    if value not in bound.alternatives[prop]:
                        bound.alternatives[prop].append(value)
                    bound.alternative_evidence[prop] = evidence.get(prop) or Evidence(doc_id, chunk, "")
            for prop, ev in evidence.items():
                bound.evidence.setdefault(prop, ev)
            vid = vertex.get("id")
            if isinstance(vid, (str, int)):
                self._by_vid[(label, str(vid))] = (object_type, object_id)

    async def _bind_reference(
        self, object_type: str, vertex: dict[str, Any], props: dict[str, Any], doc_id: str, chunk: int
    ) -> None:
        """Resolve a DB-backed label to an existing row; never create one."""
        cfg = self._cfgs[object_type]
        obj = self.compiled.objects[object_type]
        pk = obj.spec.primaryKey[0]
        match = list(cfg.match or cfg.key or [pk])
        values = {p: props.get(p) for p in match if _valid(props.get(p))}
        ids = await self.repo.find_by_keys(self.session, object_type, values) if values else []
        label = self.schema.labels[object_type]
        vid = vertex.get("id")
        if len(ids) == 1:
            self._by_vid[(label, str(vid))] = (object_type, ids[0])
            self.out.references.add((object_type, ids[0]))
            return
        self._candidate(
            "object",
            "AMBIGUOUS_REFERENCE" if len(ids) > 1 else "UNRESOLVED_REFERENCE",
            {"object_type": object_type, "candidates": ids, "props": _jsonable(props), "raw": _jsonable(vertex)},
            doc_id,
            chunk,
            object_type=object_type,
        )

    async def _bind_edges(self, graph: dict[str, Any], doc_id: str, chunk: int, text: str) -> None:
        for edge in graph.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            link_name = edge.get("label")
            lnk = self.compiled.links.get(link_name) if isinstance(link_name, str) else None
            if lnk is None or not isinstance(lnk.spec.join, ExtractedJoin):
                self.out.gaps.append(f"unknown link {link_name!r}")
                continue
            out_label = edge.get("outVLabel")
            in_label = edge.get("inVLabel")
            out_vid = edge.get("outV")
            in_vid = edge.get("inV")
            src = self._by_vid.get((out_label, str(out_vid))) if out_label and out_vid is not None else None
            dst = self._by_vid.get((in_label, str(in_vid))) if in_label and in_vid is not None else None
            if src is None or dst is None:
                self._candidate(
                    "link",
                    "UNRESOLVED_ENDPOINT",
                    {
                        "link": link_name,
                        "outV": out_vid,
                        "outVLabel": out_label,
                        "inV": in_vid,
                        "inVLabel": in_label,
                        "evidence": self._evidence(doc_id, chunk, text, out_vid).as_dict(),
                    },
                    doc_id,
                    chunk,
                    link=link_name,
                )
                continue
            if out_label != lnk.spec.source or in_label != lnk.spec.target:
                self._candidate(
                    "link",
                    "WRONG_DIRECTION",
                    {
                        "link": link_name,
                        "source": lnk.spec.source,
                        "target": lnk.spec.target,
                        "outVLabel": out_label,
                        "inVLabel": in_label,
                    },
                    doc_id,
                    chunk,
                    link=link_name,
                )
                continue
            if src[1] == dst[1] and src[0] == dst[0]:
                continue
            # an edge has no scalar to quote; keep the chunk opening so the
            # review UI can highlight where the relation came from
            ev = Evidence(doc_id, chunk, text.strip()[:400])
            key = (link_name, src[1], dst[1])
            existing = self.out.links.get(key)
            if existing is None:
                existing = BoundLink(link_name, src[1], dst[1], ev, out_label, in_label)
                existing.sources[doc_id] = ev
                self.out.links[key] = existing
            else:
                existing.sources.setdefault(doc_id, ev)

    def _check_required(self) -> None:
        for bound in list(self._by_pk.values()):
            if not bound.created:
                continue
            obj = self.compiled.objects[bound.object_type]
            missing = [
                p
                for p, d in obj.spec.properties.items()
                if d.required and p not in obj.spec.primaryKey and not _valid(bound.props.get(p))
            ]
            bound.missing_required = missing
            if missing:
                self._candidate(
                    "object",
                    "MISSING_REQUIRED",
                    {
                        "object_type": bound.object_type,
                        "object_id": bound.object_id,
                        "props": _jsonable(bound.props),
                        "missing": missing,
                        "evidence": {k: v.as_dict() for k, v in bound.evidence.items()},
                    },
                    next(iter(bound.evidence.values())).doc_id if bound.evidence else "",
                    next(iter(bound.evidence.values())).chunk_index if bound.evidence else 0,
                    object_type=bound.object_type,
                    object_id=bound.object_id,
                )
                self._by_pk.pop((bound.object_type, bound.object_id), None)
