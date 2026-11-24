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

## Tests

The [document-agent tests](../../test_documents_agent.py) load this package
through the shared [fixture setup](../../doc_fixtures.py). The deterministic
[reference agent](../../../tools/doc_agent_reference.py) exercises the subprocess
contract without a model or network connection.
