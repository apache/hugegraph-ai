# Tasks 4.2–4.7 and 7.1–7.4 Log: Canonical Graph Workflow

## Canonical graph plans

Added graph plan compilation with ordered operation IDs, stable vertex/edge/delete identities, and explicit edge dependencies on earlier vertex operations. Live endpoints and deletion targets are bound to backend IDs. Earlier planned vertices use dependency operation IDs; create receipts are the source for resulting backend IDs.

`DELETE_EDGE` is the only graph mutation registered in the default canonical executor because HugeGraph 1.7 returns a stable edge ID and supports ID-based deletion. It produces durable receipts and has create/delete reconciliation readers.

## Fail-closed graph creation and import

HugeGraph 1.7 does not expose verified atomic vertex/edge create-if-absent primitives. CREATE_VERTEX, CREATE_EDGE, and graph import therefore compile a complete workflow preview but remain `confirmable=false` and do not issue an executable plan. The legacy sequential and HugeGraph-AI `/graph-import` confirmation paths are disabled rather than presented as durable workflows.

## Isolated vertex deletion evidence

A barrier-controlled Docker race ran three 100-round series against HugeGraph 1.7 RocksDB. The first series produced 54 cases where both add-edge and delete requests reported success while the source vertex and new edge were both absent. This proves implicit cascade can occur and the conditional traversal does not provide the required isolation.

`ISOLATED_VERTEX_DELETE` remains `UNKNOWN`; its adapter is not registered. Dry-run remains available as preview, while confirmation returns `FEATURE_DISABLED` before plan consumption.

## Fault recovery

Added deterministic tests for claim-before-call, crash after plan claim, response loss, receipt persistence failure, and response loss after receipt persistence. Every case reopens a fresh SQLitePlanStore and verifies durable status. Reconcile marks never-claimed operations as `RETRYABLE_NOT_APPLIED`; resume skips applied operations and replays only those proven not applied.

## Verification

- Canonical graph workflow/reconcile tests: 8 focused tests.
- Executor fault suite and related model/store tests: 59 passed.
- Barrier Docker suite: 16 passed, 1 expected failure documenting unsupported isolation.
- Complete MCP suite before final verification: 769 passed, 17 skipped.
- Focused Ruff, formatting, and diff checks passed.
