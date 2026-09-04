# Tasks 4.1–6.4 Log: Atomic Graph, Schema, and Property Boundaries

## Edge endpoint identity

Create-edge dry-run resolves live endpoint IDs with bounded ID queries and stores `source_id`/`target_id` in the server compiled plan. Earlier planned vertices are accepted only when they expose an explicit stable ID; otherwise planning fails with `ENDPOINT_ID_NOT_STABLE`. Edge writes use only `g.V(source_id)` and `g.V(target_id)` and never re-evaluate endpoint predicates. Dependency operation IDs and create-vertex result receipts remain for task 4.2/7.2.

Unit and Docker tests cover predicate expansion after dry-run and verify one edge between the approved IDs. Full create identity reconciliation remains pending task 4.4.

## Schema boundary

Schema create is one operation per plan. Manager construction, request, and post-read now share one exception boundary. Schema write clients use `write_timeout_seconds`. Identical existing schema returns `ALREADY_APPLIED`; same-name different schema returns `CONFLICT`; ambiguous failures persist `UNKNOWN`.

Removed unreachable batch-partial helpers. Canonical `ApplyReceipt` supplies the status and observed state while legacy public success fields remain available during compatibility.

## Property validation and CAS

Shared validation is exception-free for arbitrary-precision integers and enforces IEEE-754 FLOAT/DOUBLE bounds, non-finite rejection, collection elements, UUID, DATE, BLOB, and OBJECT rules across import, create, and mutation planners.

Added a narrow `replace_properties_if_match` Protocol and contract without adding a nonexistent GraphManager endpoint. HugeGraph 1.7 RocksDB remains `VERIFIED_UNSUPPORTED`; mutation dry-run exposes expected/desired CAS intent and operation ID, while confirmation remains fail-closed and does not consume or write. SINGLE/LIST/SET two-client tests remain capability-gated and skipped until support is proven.

## Verification

- Complete MCP suite: 739 passed, 16 skipped.
- Edge tests: 68 unit tests and 6 focused Docker tests in the worker lane.
- Schema tests: 96 passed.
- Property validation focused tests: 47 passed.
- CAS contract: 39 passed, 3 capability-gated skipped.
- Focused Ruff, formatting, and diff checks passed.
