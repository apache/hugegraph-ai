# supplier-risk — the document data-source showcase

This domain is deliberately small and complete: it has **two sources of truth**
for two different kinds of fact.

| Object | Source | Authority |
|---|---|---|
| `supplier` | ERP SQLite (`suppliers`) | `source` — the system of record |
| `supplier-note` | `data/docs/supplier-notes/` | `document` — extracted, reviewed, never invented |

The link `supplier-risk-note` is `join.kind: extracted`: it is asserted by a
document, resolved against an existing supplier by name, and stored in the same
link table the projection and traversal already read.

## What to try

```bash
export SUPPLIER_DSN="sqlite+aiosqlite:///$PWD/suppliers.db"
sqlite3 suppliers.db < seed/01_suppliers.sql
ontogeny serve --package domains/supplier-risk
```

1. **Document intelligence → New task.** Choose the files, the local scope
   (object types/links/properties) and a skill addendum, then create the tasks.
   With `ONTOGENY_DOC_AGENT_CMD="python tools/doc_agent_reference.py"`, the
   reference agent returns chunks + graphs; nothing is written yet.
2. Open a task: the original text sits beside the extracted graph (graph/JSON
   toggle). Edit the JSON, run again, or resolve blockers.
3. Click **Confirm into graph** only when ready. The binder writes the object,
   the extracted link and the per-field assertions; projection/outbox run
   afterwards.
4. Rerun a confirmed task: a new revision is created, reviewed and confirmed
   independently; the old revision remains as audit history.

## Running without an LLM (tests / CI)

`tools/doc_agent_reference.py` is a deterministic agent implementing the exact
external-agent contract; `tests/test_documents_agent.py` drives the whole
pipeline through it as a subprocess. No model or network is involved.
