# doc-extract-agent — external document extraction

ontogeny does not call a model for document extraction. It sends the
ontology-compiled schema and one document to an **external agent**, and the agent
returns the chunks it used plus the graph it extracted. The platform then binds
that graph deterministically (types, identity, ownership, references) and parks
anything ambiguous in the review queue.

## Configure

```bash
# command transport: request JSON on stdin, response JSON on stdout
export ONTOGENY_DOC_AGENT_CMD="python tools/doc_agent_reference.py"

# or HTTP transport: POST the same JSON body
export ONTOGENY_DOC_AGENT_URL="http://agent:9000/extract"
export ONTOGENY_DOC_AGENT_TOKEN="..."   # optional Bearer token
export ONTOGENY_DOC_AGENT_TIMEOUT_S=600
```

Both transports are implemented in [`ontogeny_ext_agent_extract/adapter.py`](./ontogeny_ext_agent_extract/adapter.py).
The extension registers the capability only when one of the two is set.

## Request

```json
{
  "protocol": "ontogeny-doc-agent/v1",
  "schema": {
    "vertexlabels": [{"name": "supplier-note", "id": 2, "id_strategy": "CUSTOMIZE_STRING",
                      "primary_keys": ["supplier_name"], "properties": ["supplier_name", "risk_level"],
                      "nullable_keys": ["risk_level"], "description": "..."}],
    "edgelabels": [{"name": "supplier-risk-note", "source_label": "supplier",
                    "target_label": "supplier-note", "properties": []}],
    "propertykeys": [{"name": "supplier_name", "data_type": "TEXT", "cardinality": "SINGLE"}]
  },
  "instructions": "…schema contract, identity rules, JSON-only response…",
  "options": {"split": "paragraph", "language": "en", "max_chunks_per_doc": 200},
  "document": {
    "id": "sha256…", "path": "/pkg/data/docs/acme.md", "name": "acme.md",
    "media_type": "text/markdown", "text": "Supplier: Acme Components …", "content_b64": null
  }
}
```

Binary documents (PDF/DOCX) arrive as `content_b64` with `text` empty; the agent
parses them with its own toolchain.

## Response

```json
{
  "chunks": [
    {
      "doc_id": "sha256…",
      "index": 0,
      "text": "Supplier: Acme Components …",
      "graph": {
        "vertices": [
          {"id": "ref-acme", "label": "supplier", "properties": {"name": "Acme Components"}},
          {"id": "note-1", "label": "supplier-note",
           "properties": {"supplier_name": "Acme Components", "risk_level": "HIGH"}}
        ],
        "edges": [
          {"label": "supplier-risk-note", "outV": "ref-acme", "outVLabel": "supplier",
           "inV": "note-1", "inVLabel": "supplier-note", "properties": {}}
        ]
      },
      "issues": []
    }
  ]
}
```

- `text` is mandatory for the UI comparison: it is the exact source chunk the
  graph came from.
- A bare `graph`, or top-level `vertices`/`edges`, is also accepted for
  single-chunk agents.
- `{ "error": "..." }` fails the document with the message in the run report.
- The platform validates labels, property keys, types, edge direction and
  identity; invalid values are quarantined or queued, never written silently.

## Reference agents

| Script | What it is |
|---|---|
| [`tools/doc_agent_reference.py`](../../tools/doc_agent_reference.py) | deterministic, no network; understands the supplier-risk note format, used by the demo and tests |
| [`tools/doc_agent_openai.py`](../../tools/doc_agent_openai.py) | same contract backed by any OpenAI-compatible chat endpoint |

Replace either with your own agent (Claude Code, a LangGraph runner, an MCP
client, a remote service). The only requirement is the JSON contract above.
