# 03 · Data & Derivation（stores/ · action/outbox.py · functions/derivation.py）

> Part of [Part I · Architecture](../README.md#part-i--architecture)

**[中文](../../zh/architecture/03-data-and-derivation.md)** | English

## 3.1 Property-level ownership (who is the real source)

| owner | Sync | Action | Typical fields |
|---|---|---|---|
| `source` (default) | owns inserts and updates; full pushes accepted as-is | forbidden to modify (blocked at validation) | ledger fields: numbers, names, timestamps |
| `ontology` | seeds once, **never overwrites** | the only legal writer | business state: status, qty_completed, … |

The declaration alone kills the classic "source system's full push wipes action state" incident. Empty mapping = same-name direct mapping (all source); derived properties are automatically `ontology`.

## 3.2 The sync engine (three strategies + four iron laws)

| Strategy | Applies to | Mechanism | Guarantee / limit |
|---|---|---|---|
| `snapshot` full snapshot | initialization / small tables | one streamed SQL result → upsert by PK; **absent rows archived** (optional) | idempotent, rerunnable anytime |
| `watermark` incremental | 90% of cases | `watermark column >= last committed watermark` (replay equality ties); the watermark advances **after commit** | deletions invisible by default — needs soft-delete markers or changelog |
| `changelog` | reserved for an external CDC integration | the current SQL/CSV source adapters do not consume Kafka/Debezium | requires a separate adapter; not a built-in CDC service |

**Four iron laws**: ① batches are atomic and idempotent ② at-least-once ③ deletion semantics declared explicitly ④ **bad rows go to quarantine, never blocking the batch** (bad-row rate = an RSI signal). Schema drift → alert & stop writing; mapping changes go through PRs.

A sync is one explicit operation: run `ontogeny sync <type>` with the service’s database DSN, or call `POST /api/v1/admin/sync/{type}`. `sync.schedule` is metadata for an external scheduler; the server does not poll source databases on that schedule. A fresh `--demo` performs its initial sync once. SQL snapshots keep one result open across fetch batches, so deleting an already-read row cannot shift later pages and falsely archive a live object. This is a snapshot of one source query, not a transaction spanning every object type. The sync commits atomically; fetch batches are not separate commits.

Quarantined native database values are converted recursively to JSON-safe diagnostics: Decimal/UUID values become strings, dates/times use ISO text and binary values use hex. A bad native value must not prevent valid rows in the same sync from committing.

Declared array/struct columns encode nested dates and timestamps at the JSON storage boundary and restore their declared types on read. Publish, reload, existing-registry startup and domain activation commit schema changes before installing the new runtime and MCP tools.

The object tables enforce at most one current row per complete business primary key with a partial unique index (`_valid_to IS NULL`); historical versions remain allowed. On upgrade, existing duplicate current rows block index creation with a clear error. Review and repair those duplicates before retrying; startup does not delete data automatically.

Object reads and writes coerce supplied key values to their declared property types; string keys retain leading zeroes. Snapshot reconciliation compares complete business-key tuples, so deleting one composite-key row does not retain it merely because another row shares its first key component. A quarantined row with an identifiable complete key still preserves the last valid object.

Domains in one database share the physical table namespace. Publishing or activating a domain rejects object-table or join-table link names reserved by another domain, including retired resource definitions; use distinct names or a separate database. Old resource names remain conservatively reserved when backing or join kind changes. Data already mixed across domains before this guard is not automatically separated or recovered. Before switching, stop old-domain writes and source sync, wait for in-flight operations, and dispatch and confirm all old events; resolve failed deliveries first. The name check does not isolate or reroute pending outbox events by domain.

## 3.3 The outbox: the only exit for derived data (four consumers, per-event receipts)

| Consumer | Does | Failure semantics |
|---|---|---|
| `webhook` | POST outbound, allowlisted | outside the allowlist: warn & consume; `${VAR}` unconfigured → warn & consume, **replay after fixing** (never rolls back the business transaction) |
| `projection` | row changes → HugeGraph vertices/edges | idempotent upserts; a failed event remains unacknowledged for retry |
| `derivation` | enqueues recompute (incl. cross-object `triggers` routing) | drain failures only warn; resumes next time |
| `sse` | real-time streaming | subscriber queue full → events dropped (storage unaffected) |

`ontogeny serve` (the ASGI factory) starts an outbox consumer loop and polls about once per second. It delivers **committed outbox events**, then drains pending derivations; it does not perform source sync. The loop follows the current dispatcher after a publish or domain switch. `POST /api/v1/admin/outbox/dispatch` remains available for an immediate manual tick; both paths share the same process lock. Shutdown cancels and awaits the workers before closing clients and database resources.

Delivery is at least once: a crash after an external POST but before its receipt commit can cause a retry, so receivers must be idempotent. HTTP 5xx/connection failures leave that consumer’s event unacknowledged; rejected 4xx requests, unconfigured URLs and allowlist denials are logged and consumed for later operator replay. A failing consumer does not prevent the others from advancing. Pending work is selected by missing `(consumer, event_id)` receipts, so a lower-ID transaction committed later is not lost behind a high-water cursor.

On the first dispatch after upgrade, each legacy cursor is migrated once by acknowledging currently visible events with `id <= last_id`; old webhooks are not blindly resent. An already-visible historical event that an older cursor skipped cannot be distinguished automatically from a successful delivery. Audit such ranges and explicitly use the internal `await sc.outbox.replay('webhook', from_id=..., through_id=...)`, then dispatch again; this can duplicate external delivery. The same bounded replay applies to the other consumers. Archive outbox rows and their receipts together.

## 3.4 The derivation worker: function-derived materialization (one batch = one process = one transaction)

Read-time expression derivations are evaluated in dependency order, irrespective of YAML field order. Cycles and all fields depending on them return `null` (`None` in Python) with a warning; independent fields still evaluate.

A non-primary-key function-derived property may be SQL `NULL` until its first successful materialization, even when declared `required`. A required result of `None` keeps the previous valid value and remains pending for retry. Existing columns already created with `NOT NULL` require an explicit reviewed schema migration (or SQLite table rebuild); startup does not automatically relax that constraint.

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
