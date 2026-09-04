# Tasks 3.1–3.6 Log: Confirm, Status, and Reconcile

## Confirm

Added a canonical `WriteExecutor`, adapter registry, and `confirm_write_tool(plan_id)`. The executor validates that every operation kind has an adapter before claiming the plan, atomically elects one executor, increments operation attempts in durable storage, and records every adapter receipt.

Repeated confirmation returns persisted status. An eight-thread concurrency test proves one adapter attempt for one plan.

## Status

Added canonical `get_write_status_tool(plan_id)`. Stored plan and operation payloads are removed from public responses. Crash-left `EXECUTING` and migrated `LEGACY_UNKNOWN` are exposed as `UNKNOWN` with reconciliation required.

## Reconcile and resume

Added a read-only `WriteReconciler`, reader registry, pure expected/desired/observed decision function, and `reconcile_write_tool(plan_id)`.

Reconciliation maps:

- observed desired state -> `APPLIED`;
- observed expected state -> `RETRYABLE_NOT_APPLIED`;
- observed third state -> `CONFLICT`;
- missing delete target -> `APPLIED`.

Reconciliation is idempotent and skips final operations. A later concurrency review proved that observing expected state cannot exclude a previously dispatched request from committing. The final rule therefore allows `RETRYABLE_NOT_APPLIED` only for an unclaimed attempt-0 operation. A claimed operation remains `UNKNOWN` with `IN_FLIGHT_COMMIT_NOT_EXCLUDED`, even when its current state still equals expected.

Execution uses durable plan leases, owner tokens, and per-attempt fencing tokens. Each operation claim renews the lease for at least the configured write timeout plus safety margin. Receipt writes compare status, attempt, attempt token, owner, and lease. Reconcile can take ownership only after lease expiry, and an active PARTIAL lease cannot be replaced by a second resume owner.

## Verification

- Confirm, status, reconciliation, fencing, and public tool tests pass in the final full suite.
- PlanStore/model focused tests: 29 passed.
- Public toolset contract includes confirm, status, and reconcile.
- `git diff --check` passed.
