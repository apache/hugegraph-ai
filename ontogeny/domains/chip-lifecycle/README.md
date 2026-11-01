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

# Chip Lifecycle Domain (chip-lifecycle)

> 完整案例说明（业务背景、告警与分析、RSI 诊断示例、Agent 协同、文档智能）
> 见 [CASE.md](CASE.md)。

A complete, importable semiconductor lifecycle ontology: **10 object types,
8 link types, 16 actions, 4 sandboxed functions, 2 policy sets, 2 stores**,
with seed data, a guided demo story and one detailed FMEA document-intelligence
case. It is also the test-suite golden package: between its actions it
exercises every effect kind the runtime implements (modify-target,
modify-linked, create-object, archive-object, set-link, webhook, emit-event),
a `marking: internal` property (`tapeout-version.mask_cost`) and a derived
property (`tapeout-version.fab_lag_h`).

```text
chip-lifecycle/
├── objects/             # 9 business objects + fmea-note (document-extracted)
├── links/               # 7 lifecycle links + design-fmea-notes (extracted)
├── actions/             # 16 actions, including raise-yield-alert / record-root-cause
├── functions/           # 4 functions, including analyze-yield-loss / requirement-impact
├── policies/            # lifecycle + default PolicySet resources
├── agents/              # product / fab / cqe copilots
├── evals/               # lifecycle flow regression suite
├── projections/         # lifecycle graph
├── stores/fab.yaml      # source store (SQLite via ${ERP_DSN})
├── stores/chip-docs.yaml # FMEA / design review documents
├── data/docs/           # fmea-io-esd-dsg201.md (detailed FMEA)
├── tools/               # deterministic module FMEA agent
├── seed/01_source.sql   # English seed rows for every source-backed entity
└── seed/demo-story.yaml # guided demo: the seed rows acted into a living lifecycle
```

## Alerts and root causes

An alert is state on a `wafer-test` or `field-failure`, not a separate entity:

```text
raise-yield-alert         → alert_status / alert_severity / alert_kind / alerted_at
analyze-yield-loss        → read-only candidates from wafer-test + wafer-lot
record-root-cause         → root_cause / root_cause_class / confidence / diagnosed_at
raise-surge-alert         → the same state on a field failure
record-failure-root-cause → the reviewed root cause on a field failure
```

`analyze-yield-loss` and `analyze-field-failure` only read the objects their
capability declares and never write; the Actions persist the alert and the
reviewed root cause.

## Document intelligence case

`data/docs/fmea-io-esd-dsg201.md` is a detailed module FMEA: seven failure
modes with S/O/D, RPN, recommended actions, detection coverage and
containment rules. After document extraction and confirm:

```text
design-module DSG-201 ──design-fmea-notes──▶ fmea-note ×7
```

Each table row becomes one `fmea-note`; the `Module:` header resolves the
existing `DSG-201` row (the model never invents a reference), and nothing is
written before human confirm:

```text
New task → select fmea-io-esd-dsg201.md
  → scope(fmea-note + design-fmea-notes)
  → Run → Review → Confirm
```

To use the module FMEA agent:

```bash
export ONTOGENY_DOC_AGENT_CMD="$PWD/.venv/bin/python domains/chip-lifecycle/tools/doc_agent_fmea_module.py"
```

## The RSI demo gap (intentional)

The source table `field_failures` carries a `lot_id` column, but the
`field-failure` object does not declare it. Filtering failures by lot raises
`NotFoundError`, the `unmapped_filter_field` detector picks the signal up,
and the loop proposes `add-optional-property field-failure.lot_id` — the
traceability chain from a customer return to its wafer lot is closed by the
RSI loop, not by a human change request. See CASE.md §3.

## Import through the console

1. Zip this folder: `zip -r chip-lifecycle.zip chip-lifecycle`
2. Domain switcher → **New domain** → **Import package**, pick the zip.
3. The server validates and activates it.

## Seed and run

The demo bootstrap seeds the source database from `seed/*.sql` and syncs every
source-backed type on boot — use a dedicated data dir so it does not collide
with any other demo state:

```bash
export ONTOGENY_DOC_AGENT_CMD="$PWD/.venv/bin/python $PWD/domains/chip-lifecycle/tools/doc_agent_fmea_module.py"
.venv/bin/ontogeny serve --demo --package domains/chip-lifecycle --data-dir .ontogeny-demo-chip
```

`ONTOGENY_DOC_AGENT_CMD` is required for document extraction; without it the
document workspace still lists the corpus but tasks fail with "no document
extractor is configured". After boot, the console shows the 35 seeded rows
across 8 object types; the FMEA case is then run from the Document
intelligence workspace (see above).
