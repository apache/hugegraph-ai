#!/usr/bin/env python3

# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Deterministic FMEA-table agent for the Chip Lifecycle demo.

One markdown table row becomes one fmea-note, resolved to the existing design
module named in the ``Module:`` header field.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys


def _fields(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key in ("module", "project", "revision"):
            out[key] = value.strip()
    return out


def _rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            if header and rows:
                break
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if header is None:
            header = cells
            continue
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells, strict=False)))
    return rows


def _int(value: str) -> int | None:
    return int(value) if str(value).strip().isdigit() else None


def _graph(row: dict[str, str], document: dict, schema: dict, fields: dict[str, str]) -> dict | None:
    failure = row.get("Failure mode", "").strip()
    if not failure:
        return None
    labels = {str(v.get("name")): v for v in schema.get("vertexlabels") or []}
    edges = {str(e.get("name")): e for e in schema.get("edgelabels") or []}
    note = labels.get("fmea-note")
    if not note:
        return None
    module_id = fields.get("module", "")
    title = f"{module_id or 'FMEA'} · {failure}"
    note_id = "FM-" + hashlib.sha1(f"{title}|{row.get('FMEA ID', '')}".encode()).hexdigest()[:10]
    severity = _int(row.get("S", ""))
    occurrence = _int(row.get("O", ""))
    detection = _int(row.get("D", ""))
    rpn = severity * occurrence * detection if None not in (severity, occurrence, detection) else None
    props = {
        "title": title,
        "fmea_id": row.get("FMEA ID"),
        "module_id": module_id,
        "failure_mode": failure,
        "cause": row.get("Cause"),
        "effect": row.get("Effect"),
        "severity": severity,
        "occurrence": occurrence,
        "detection": detection,
        "rpn": rpn,
        "recommended_action": row.get("Recommended action"),
        "source_doc": document.get("name"),
        "status": "EXTRACTED",
    }
    allowed = set(note.get("properties") or [])
    note_props = {k: v for k, v in props.items() if k in allowed and v is not None}
    vertices = [{"id": note_id, "label": "fmea-note", "properties": note_props}]
    edge = edges.get("design-fmea-notes")
    module = labels.get("design-module")
    if module and edge and module_id:
        ref_id = "ref-" + re.sub(r"[^a-z0-9]+", "-", module_id.lower())
        vertices.insert(0, {"id": ref_id, "label": "design-module", "properties": {"module_id": module_id}})
        return {
            "vertices": vertices,
            "edges": [
                {
                    "label": "design-fmea-notes",
                    "outV": ref_id,
                    "outVLabel": "design-module",
                    "inV": note_id,
                    "inVLabel": "fmea-note",
                    "properties": {},
                }
            ],
        }
    return {"vertices": vertices, "edges": []}


def main() -> int:
    request = json.load(sys.stdin)
    document = request.get("document") or {}
    schema = request.get("schema") or {}
    text = document.get("text") or ""
    fields = _fields(text)
    chunks = []
    for i, row in enumerate(_rows(text)):
        graph = _graph(row, document, schema, fields)
        if graph is None:
            continue
        chunks.append(
            {
                "doc_id": document.get("id"),
                "index": i,
                "text": " | ".join(f"{k}: {v}" for k, v in row.items() if v),
                "graph": graph,
                "issues": [],
                "status": "final",
            }
        )
    print(json.dumps({"chunks": chunks}, ensure_ascii=False))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
