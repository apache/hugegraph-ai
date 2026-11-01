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

"""Reference external document agent (deterministic, no model, no network).

It implements the same stdin/stdout JSON protocol a real agent would: read one
request, return chunks with a graph. This fallback understands the simple
key/value memo format used by the examples, so the pipeline runs in CI without
a model. Replace it with your own agent -- the contract is in
``extensions/doc-extract-agent``.

    ONTOGENY_DOC_AGENT_CMD="python tools/doc_agent_reference.py"
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys


def _text(document: dict) -> str:
    text = document.get("text") or ""
    if text:
        return text
    raw = document.get("content_b64")
    if not raw:
        return ""
    data = base64.b64decode(raw)
    name = str(document.get("name") or "")
    if name.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            return ""
        import io

        return "\n\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages)
    if name.lower().endswith(".docx"):
        try:
            import docx  # type: ignore
        except ImportError:
            return ""
        import io

        document_obj = docx.Document(io.BytesIO(data))  # type: ignore[attr-defined]
        return "\n\n".join(p.text for p in document_obj.paragraphs if p.text.strip())
    return data.decode("utf-8", "replace")


def _fields(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key in ("supplier", "product", "effective date", "risk level", "summary", "body"):
            out[key] = value.strip()
    return out


def _title(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _labels(schema: dict) -> tuple[dict, dict | None]:
    labels = schema.get("vertexlabels") or []
    if not labels:
        return {}, None
    note = next((v for v in labels if "note" in str(v.get("name", "")).lower()), labels[-1])
    ref = next((v for v in labels if v is not note), None)
    return note, ref


def _graph(schema: dict, fields: dict[str, str], title: str = "", text: str = "") -> tuple[dict, str]:
    note, ref = _labels(schema)
    product = fields.get("product") or fields.get("supplier")
    date = fields.get("effective date")
    if not note or not product:
        return {"vertices": [], "edges": []}, ""
    note_props = {}
    note_title = fields.get("title") or title or f"{product} note"
    mapping = {
        "title": note_title,
        "supplier_name": fields.get("supplier"),
        "product_name": fields.get("product"),
        "effective_date": date,
        "risk_level": fields.get("risk level"),
        "summary": fields.get("summary"),
        "body": fields.get("body") or text.strip(),
    }
    for prop, value in mapping.items():
        if prop in (note.get("properties") or []) and value:
            note_props[prop] = value
    note_id = "note-" + hashlib.sha1(f"{product}|{date or ''}|{note_title}".encode()).hexdigest()[:10]
    vertices = [{"id": note_id, "label": note["name"], "properties": note_props}]
    edges = []
    ref_props = {}
    if ref:
        for prop in ref.get("properties") or []:
            if prop in ("name", "supplier_name", "product_name"):
                ref_props[prop] = product
            elif prop in ("supplier_id", "product_id", "id"):
                ref_props[prop] = "ref-" + re.sub(r"[^a-z0-9]+", "-", product.lower())
        ref_id = "ref-" + re.sub(r"[^a-z0-9]+", "-", product.lower())
        vertices.insert(0, {"id": ref_id, "label": ref["name"], "properties": ref_props})
        edge_labels = schema.get("edgelabels") or []
        if edge_labels:
            edges.append(
                {
                    "label": edge_labels[0]["name"],
                    "outV": ref_id,
                    "outVLabel": ref["name"],
                    "inV": note_id,
                    "inVLabel": note["name"],
                    "properties": {},
                }
            )
    return {"vertices": vertices, "edges": edges}, note_id


def main() -> int:
    request = json.load(sys.stdin)
    document = request.get("document") or {}
    text = _text(document)
    graph, _ = _graph(request.get("schema") or {}, _fields(text), _title(text), text)
    print(
        json.dumps(
            {
                "chunks": [
                    {
                        "doc_id": document.get("id"),
                        "index": 0,
                        "text": text,
                        "graph": graph,
                        "issues": [],
                        "status": "final",
                    }
                ]
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
