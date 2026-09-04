# Task 2.1 Log: Canonical Write Model TDD

## Scope

Replaced the initial receipt-only test with the red-phase contract for the approved canonical write model. Production code was intentionally not changed in this task.

## Test contract

The tests require:

- frozen `GraphTarget`, `OperationPlan`, `WritePlan`, and `ApplyReceipt` models;
- deep immutability for nested target, expected-state, and desired-state mappings;
- ordered operation storage;
- unique operation IDs within a plan;
- dependencies that reference only earlier operations;
- deterministic canonical JSON and digest independent of mapping insertion order;
- digest changes whenever authorized desired state changes;
- receipts with stable plan ID, operation ID, attempt, reason code, commit time, observed state, and reconciliation flag;
- separate `ApplyStatus` and `PlanStatus` vocabularies;
- an explicit, complete, fail-closed plan transition matrix;
- plan status aggregation that preserves `PARTIAL` whenever known successful operations coexist with rejected, conflicting, or unknown operations.

## State decisions locked by tests

```text
ISSUED -> EXECUTING | EXPIRED
EXECUTING -> APPLIED | ALREADY_APPLIED | REJECTED | CONFLICT | PARTIAL | UNKNOWN
UNKNOWN -> APPLIED | CONFLICT | RETRYABLE_NOT_APPLIED
RETRYABLE_NOT_APPLIED -> EXECUTING
PARTIAL -> PARTIAL | APPLIED | UNKNOWN
terminal states -> no transition
```

Aggregation distinguishes:

- all already applied -> `ALREADY_APPLIED`;
- applied plus already applied -> `APPLIED`;
- any known success plus any non-success -> `PARTIAL`;
- no known success plus unknown -> `UNKNOWN`;
- proven conflict/rejection/not-applied -> their corresponding status.

## Verification

- `test_write_plan.py` passes Ruff check.
- `test_write_plan.py` passes Ruff format check.
- Pytest red phase is confirmed: collection fails because the current production module does not yet export `ALLOWED_PLAN_TRANSITIONS` and the rest of the canonical model API.

## Result

Task 2.1 is complete as a TDD red-phase task. Task 2.2 must implement the specified model and make this suite pass without weakening its immutability or state-transition assertions.
