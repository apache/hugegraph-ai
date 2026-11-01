#!/usr/bin/env python3
"""Demo router for the document cases in this repository.

Dispatches on the schema, so one ONTOGENY_DOC_AGENT_CMD can serve:
  fmea-note + design-module  -> Chip Lifecycle module FMEA agent
  everything else            -> generic memo reference agent

The protocol stays standard ``ontogeny-doc-agent/v1``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


reference = _load("ontogeny_demo_reference", ROOT / "tools" / "doc_agent_reference.py")
module_fmea = _load(
    "ontogeny_demo_fmea_module",
    ROOT / "domains" / "chip-lifecycle" / "tools" / "doc_agent_fmea_module.py",
)


def _fmea_chunks(agent, text: str, document: dict, schema: dict) -> list[dict]:
    """One chunk per markdown table row, using the given FMEA agent's binding."""
    fields = agent._fields(text)
    chunks = []
    for i, row in enumerate(agent._rows(text)):
        graph = agent._graph(row, document, schema, fields)
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
    return chunks


def main() -> int:
    request = json.load(sys.stdin)
    document = request.get("document") or {}
    schema = request.get("schema") or {}
    text = reference._text(document)
    labels = {str(v.get("name")) for v in schema.get("vertexlabels") or []}

    if "fmea-note" in labels and "design-module" in labels:
        chunks = _fmea_chunks(module_fmea, text, document, schema)
    else:
        graph, _note_id = reference._graph(schema, reference._fields(text), reference._title(text), text)
        chunks = [
            {
                "doc_id": document.get("id"),
                "index": 0,
                "text": text,
                "graph": graph,
                "issues": [],
                "status": "final",
            }
        ]
    print(json.dumps({"chunks": chunks}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
