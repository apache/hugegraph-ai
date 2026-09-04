# Implementation Plan: HugeGraph MCP Confirmed Write Safety

- [x] 1. **Research and current-state inventory** `[优先级: 高]`

  - [x] 1.1. Map the current uncommitted plan-store, receipt, executor, graph-operation, schema, import, query-budget, configuration, and compatibility changes to requirements R1–R12; identify reusable code and code that conflicts with the approved design. `(关联需求: R1-R12)`
  - [x] 1.2. Inspect HugeGraph 1.7 client/server capabilities for create-if-absent, edge identity, isolated vertex deletion, property CAS, evaluation timeout, result limiting, and response streaming; encode the supported capability matrix as test fixtures or constants. `(依赖于: 1.1)` `(关联需求: R2-R4, R7-R10)`
  - [x] 1.3. Define the compatibility contract for the current `plan_hash`/`nonce` API and the new `plan_id` API in contract tests before changing public tools. `(依赖于: 1.1)` `(关联需求: R1, R11)`

- [x] 2. **Canonical plan, receipt, and state model** `[优先级: 高]`

  - [x] 2.1. **TDD:** Add tests for immutable `WritePlan`, ordered `OperationPlan`, operation identity, canonical serialization, and the complete status-transition matrix including `PARTIAL`. `(依赖于: 1.3)` `(关联需求: R1, R5)`
  - [x] 2.2. Implement the canonical plan/operation/receipt dataclasses and central status aggregation rules; remove competing ad-hoc status strings from tool modules. `(依赖于: 2.1)` `(关联需求: R1, R5)`
  - [x] 2.3. **TDD:** Add SQLite migration tests covering current confirmation tables, existing rows, corrupt payloads, `LEGACY_UNKNOWN`, schema versioning, and restart persistence. `(依赖于: 2.2)` `(关联需求: R5, R6, R11)`
  - [x] 2.4. Replace the confirmation-only schema with versioned `write_plans` and per-operation `write_operations`; preserve immutable plan payloads and atomic state transitions. `(依赖于: 2.3)` `(关联需求: R1, R5, R6)`
  - [x] 2.5. Add a PlanStore interface, retain SQLite as the declared single-instance implementation, and fail closed when a write-enabled multi-instance configuration lacks a shared store. `(依赖于: 2.4)` `(关联需求: R1, R5)`

- [x] 3. **Unified confirm, status, and reconciliation entry points** `[优先级: 高]`

  - [x] 3.1. **TDD:** Add contract and concurrency tests showing that `confirm_write_tool(plan_id)` executes the stored plan, allows one executor claim, and returns persisted state on repeated confirmation. `(依赖于: 2.5)` `(关联需求: R1, R5, R11)`
  - [x] 3.2. Implement the unified confirm executor dispatch and atomically transition `ISSUED → EXECUTING` before invoking an adapter. `(依赖于: 3.1)` `(关联需求: R1, R5)`
  - [x] 3.3. **TDD:** Add status tests for `APPLIED`, `ALREADY_APPLIED`, `REJECTED`, `CONFLICT`, `PARTIAL`, crash-left `EXECUTING`, and `UNKNOWN`, including payload redaction. `(依赖于: 3.2)` `(关联需求: R5, R11)`
  - [x] 3.4. Implement `get_write_status_tool(plan_id)` using canonical plan and operation receipts; expose crash-left `EXECUTING` as `UNKNOWN`. `(依赖于: 3.3)` `(关联需求: R5, R11)`
  - [x] 3.5. **TDD:** Add reconciliation decision tests for create, delete, schema create, and property replacement expected/desired/third-state outcomes. `(依赖于: 3.4)` `(关联需求: R6)`
  - [x] 3.6. Implement `reconcile_write_tool(plan_id)` as a read-only, idempotent operation and permit resume only from a proven not-applied state. `(依赖于: 3.5)` `(关联需求: R6, R11)`

- [x] 4. **Stable graph-operation compilation and execution** `[优先级: 高]`

  - [x] 4.1. **TDD:** Add a barrier-controlled regression test in which edge endpoint predicates expand after planning; assert exactly one edge is created between the approved IDs. `(依赖于: 3.2)` `(关联需求: R2, R12)`
  - [x] 4.2. Compile existing edge endpoints to backend IDs and compile newly created endpoints to dependency operation IDs; persist actual vertex IDs in create receipts. `(依赖于: 4.1)` `(关联需求: R2, R8)`
  - [x] 4.3. Change edge execution to consume only persisted source/target IDs and stable sort-key or idempotency identity; remove predicate-based endpoint lookup from the write traversal. `(依赖于: 4.2)` `(关联需求: R2)`
  - [x] 4.4. **TDD:** Add create-vertex and create-edge reconciliation tests for identical existing state, conflicting state, missing state, and indistinguishable duplicate-edge rejection. `(依赖于: 4.3)` `(关联需求: R2, R6)`
  - [x] 4.5. Keep delete compilation bound to backend ID and label, and route delete receipts through the unified executor and reconciler. `(依赖于: 3.6)` `(关联需求: R2, R5, R6)`
  - [x] 4.6. **TDD:** Add backend-specific concurrent add-edge versus isolated-delete tests with barriers and database-state assertions. `(依赖于: 1.2, 4.5)` `(关联需求: R3, R12)`
  - [x] 4.7. Enable the isolated-delete adapter only for backends that pass the atomicity test; otherwise return `FEATURE_DISABLED` before confirmation consumption. `(依赖于: 4.6)` `(关联需求: R3)`

- [x] 5. **Schema execution boundary** `[优先级: 高]`

  - [x] 5.1. **TDD:** Add tests for one-operation plans, identical existing objects, same-name conflicts, manager construction failure, transport failure, post-read failure, and receipt persistence. `(依赖于: 3.2)` `(关联需求: R5, R7)`
  - [x] 5.2. Move schema manager construction, request, response handling, and verification into one executor exception boundary that persists `UNKNOWN` when the result is ambiguous. `(依赖于: 5.1)` `(关联需求: R5, R7)`
  - [x] 5.3. Construct schema write clients with `write_timeout_seconds` and preserve read timeout only for planning and reconciliation reads. `(依赖于: 5.2)` `(关联需求: R7, R10)`
  - [x] 5.4. Remove schema batch-partial compatibility paths and route every schema create through the canonical receipt/status model. `(依赖于: 5.3)` `(关联需求: R5, R7, R11)`

- [x] 6. **Property validation and backend CAS capability** `[优先级: 高]`

  - [x] 6.1. **TDD:** Extend shared property-validation tests with arbitrary-precision integers, FLOAT/DOUBLE overflow, non-finite floats, collection elements, UUID, DATE, BLOB, and OBJECT cases. `(依赖于: 1.1)` `(关联需求: R4, R10)`
  - [x] 6.2. Make numeric validation total and exception-free, and ensure import, vertex/edge creation, and mutation planners use the same validator. `(依赖于: 6.1)` `(关联需求: R4, R10)`
  - [x] 6.3. Define and test the pyhugegraph contract for backend `replace_properties_if_match`, including operation ID, expected state, desired state, and result mapping. `(依赖于: 1.2, 6.2)` `(关联需求: R4, R5)`
  - [x] 6.4. Keep confirmed property mutation fail-closed until the server capability exists and passes two-client SINGLE/LIST/SET concurrency tests; connect the adapter only after those tests pass. `(依赖于: 6.3)` `(关联需求: R4, R12)`

- [x] 7. **Durable graph import workflow** `[优先级: 高]`

  - [x] 7.1. **TDD:** Add workflow aggregation tests proving that known prior writes plus a later failure produce `PARTIAL`, never `REJECTED`. `(依赖于: 2.2, 3.4)` `(关联需求: R5, R8)`
  - [x] 7.2. Compile imports into ordered vertex and edge operations with explicit dependencies, stable identities, and per-operation receipts. `(依赖于: 4.3, 7.1)` `(关联需求: R2, R8)`
  - [x] 7.3. Replace the direct sequential import loop and legacy AI write path with the durable workflow executor; persist vertex result IDs before dependent edge execution. `(依赖于: 7.2)` `(关联需求: R5, R8)`
  - [x] 7.4. **TDD:** Add crash/resume tests at every operation boundary and verify that resume reconciles before executing only proven-not-applied operations. `(依赖于: 7.3)` `(关联需求: R6, R8, R12)`

- [x] 8. **Configuration and raw-query safety** `[优先级: 高]`

  - [x] 8.1. **TDD:** Add typed configuration boundary tests for empty, negative, non-finite, overflowing, and excessively large integer/float timeout and budget values. `(依赖于: 1.1)` `(关联需求: R10)`
  - [x] 8.2. Implement field-spec-based configuration parsing with explicit type, default, minimum, and maximum; ensure server import never raises for environment input. `(依赖于: 8.1)` `(关联需求: R10)`
  - [x] 8.3. **TDD:** Add bounded nested-envelope tests and replace recursive upstream-envelope normalization with iterative depth-limited normalization. `(依赖于: 1.1)` `(关联需求: R10, R11)`
  - [x] 8.4. Define pyhugegraph/server contracts and tests for a read-only principal, evaluation timeout, server result cap, and streaming HTTP byte cap. `(依赖于: 1.2)` `(关联需求: R9)`
  - [x] 8.5. Keep public raw execution disabled until all hard-budget capabilities pass integration tests; retain post-materialization limits only as output guards and label them accordingly. `(依赖于: 8.4)` `(关联需求: R9, R11)`

- [x] 9. **Public compatibility and documentation** `[优先级: 中]`

  - [x] 9.1. Add the one-release compatibility adapter for `plan_hash`, `nonce`, and `expires_at`, including deprecation warnings and server-plan-only execution tests. `(依赖于: 3.6)` `(关联需求: R1, R11)`
  - [x] 9.2. Update tool docstrings and generated/listed contracts for plan IDs, canonical statuses, mutation preview-only behavior, raw-query gating, timeout fields, and status/reconcile tools. `(依赖于: 5.4, 6.4, 8.5, 9.1)` `(关联需求: R11)`
  - [x] 9.3. Update `README.md`, `README.zh-CN.md`, and the P0a integration checklist to match the tested runtime contract and single-operation schema workflow. `(依赖于: 9.2)` `(关联需求: R11)`

- [x] 10. **Automated verification and regression gates** `[优先级: 高]`

  - [x] 10.1. Run the affected MCP, HugeGraph Python client, and Thin API unit/contract suites and resolve regressions without weakening safety assertions. `(依赖于: 4.7, 5.4, 6.4, 7.4, 8.5, 9.3)` `(关联需求: R12)`
  - [x] 10.2. Run SQLite migration and fault-injection suites in fresh processes, covering all documented crash points and durable status recovery. `(依赖于: 10.1)` `(关联需求: R5, R6, R12)`
  - [x] 10.3. Run Docker HugeGraph 1.7 integration suites for supported backends, verifying graph state and ledger state together for edge creation, isolated deletion, schema create, import partials, and reconciliation. `(依赖于: 10.2)` `(关联需求: R2-R8, R12)`
  - [x] 10.4. Run repository-declared lint, formatting, and diff-hygiene checks over the final changed paths. `(依赖于: 10.3)` `(关联需求: R12)`
