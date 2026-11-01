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
