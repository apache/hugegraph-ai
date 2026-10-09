# 03 · Data & Derivation（stores/ · action/outbox.py · functions/derivation.py）

> Part of [Part I · Architecture](../README.md#part-i--architecture)

**[中文](../../architecture/03-data-and-derivation.md)** | English

## 3.1 Property-level ownership (who is the real source)

| owner | Sync | Action | Typical fields |
|---|---|---|---|
| `source` (default) | owns inserts and updates; full pushes accepted as-is | forbidden to modify (blocked at validation) | ledger fields: numbers, names, timestamps |
| `ontology` | seeds once, **never overwrites** | the only legal writer | business state: status, qty_completed, … |

The declaration alone kills the classic "source system's full push wipes action state" incident. Empty mapping = same-name direct mapping (all source); derived properties are automatically `ontology`.

## 3.2 The sync engine (three strategies + four iron laws)

| Strategy | Applies to | Mechanism | Guarantee / limit |
|---|---|---|---|
| `snapshot` full snapshot | initialization / small tables | full load → upsert by PK; **absent rows archived** (optional) | idempotent, rerunnable anytime |
| `watermark` incremental | 90% of cases | `watermark column > last watermark`; the watermark advances **after commit** | deletions invisible by default — needs soft-delete markers or changelog |
| `changelog` CDC | high-frequency / delete-aware | consumes the Debezium changelog (**capture not self-built**) | consumer in place, depends on a Kafka source |

**Four iron laws**: ① batches are atomic and idempotent ② at-least-once ③ deletion semantics declared explicitly ④ **bad rows go to quarantine, never blocking the batch** (bad-row rate = an RSI signal). Schema drift → alert & stop writing; mapping changes go through PRs.

## 3.3 The outbox: the only exit for derived data (four consumers, independent cursors)

| Consumer | Does | Failure semantics |
|---|---|---|
| `webhook` | POST outbound, allowlisted | outside the allowlist: warn & consume; `${VAR}` unconfigured → warn & consume, **replay after fixing** (never rolls back the business transaction) |
| `projection` | row changes → HugeGraph vertices/edges | monotonic per object by outbox id; upsert idempotent, cursor rewinds on failure |
| `derivation` | enqueues recompute (incl. cross-object `triggers` routing) | drain failures only warn; resumes next time |
| `sse` | real-time streaming | subscriber queue full → events dropped (storage unaffected) |

## 3.4 The derivation worker: function-derived materialization (one batch = one process = one transaction)

The journey of one drain (functions/derivation.py):

1. **Route**: event type → matched derived properties (own type + cross-object `triggers`; a cross-object trigger recomputes the owner's whole table — targeted invalidation would require parsing sandbox code, deliberately not done)
2. **Assemble**: fetch rows in batch → `assemble_row` (API-shaped: derived properties visible, timezone faithful)
3. **Evaluate**: `map_rows` loops all rows inside one subprocess (may call ontogeny.query / ontogeny.llm)
4. **Persist**: type-coerce → write the current version's column in one transaction. **No revisions, no audit entries** (recomputable values must not pollute the audit); action decisions never read it

## 3.5 Graph projection (optional · derived · rebuildable)

| Stage | Mechanism |
|---|---|
| schema compilation | DSL types → HugeGraph propertykey/vertexlabel/edgelabel; primary keys → vertex keys; allowlisted properties get secondary indexes |
| full backfill | object tables → CSV → HugeGraph-Loader; **new graph space + atomic alias switch** (the old graph stays queryable during backfill) |
| incremental | outbox consumer upserts per event / deleting a vertex cascades to edges (optional keep-flagged) |
| degradation | endpoint unconfigured → SQL-only from startup (with an alert); ≥3 hops automatically falls back to SQL recursive CTEs |
