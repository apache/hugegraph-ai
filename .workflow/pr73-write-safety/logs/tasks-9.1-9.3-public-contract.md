# Tasks 9.1–9.3 Log: Compatibility and Public Documentation

## Compatibility adapter

Legacy `plan_hash`, `nonce`, and `expires_at` fields are validated as an all-or-nothing group before business logic. Complete legacy confirmation responses carry `LEGACY_CONFIRMATION_DEPRECATED`. Canonical confirm, status, and reconcile tools accept only `plan_id`; legacy endpoints do not accept `plan_id`, preventing mixed protocol ambiguity.

## Public contract

Updated tool docstrings and contract tests for canonical lifecycle tools, status vocabulary, schema single-operation behavior, mutation and unsupported graph operations as preview-only, Raw Gremlin hard-budget gating, timeouts, PlanStore topology, and legacy warnings.

## Documentation

Updated both READMEs and the P0a checklist. The checklist uses canonical plan-ID flows, includes complete legacy examples, separates executable DELETE_EDGE from preview-only operations, documents `PARTIAL`/`UNKNOWN`, and points to executable fault and Docker tests.

## Verification

- Public docs, tool contract, confirmation contract, and schema tests: 156 passed.
- Focused Ruff/format and diff checks passed.
- Two independent reader passes reported no blocker or important documentation issue.
