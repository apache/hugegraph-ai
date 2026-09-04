# Task 1.3 Log: Confirmation Compatibility Contract

## Scope

Defined a machine-readable contract and executable contract tests before changing public write tools. The contract separates the canonical plan-ID protocol from the one-release legacy hash/nonce protocol.

## Decisions

### Canonical protocol

- `confirm_write_tool` accepts only `plan_id`.
- The authoritative execution payload is the immutable server-persisted plan.
- Client-resubmitted targets, operations, properties, hashes, or nonces are not authoritative.
- Repeated confirmation returns persisted status and does not create a second attempt.
- `get_write_status_tool` and `reconcile_write_tool` use `plan_id`.

### Legacy compatibility protocol

- `plan_hash`, `nonce`, and `expires_at` remain accepted for one release.
- The three fields form one all-or-nothing locator group.
- They locate and integrity-check a server-persisted plan; they never authorize a client payload.
- Legacy responses carry warning code `LEGACY_CONFIRMATION_DEPRECATED`.
- Canonical and legacy fields are mutually exclusive. Mixed requests are rejected rather than assigned implicit precedence.

### Outcome contract

The public vocabulary is:

```text
APPLIED
ALREADY_APPLIED
REJECTED
CONFLICT
PARTIAL
UNKNOWN
```

No public outcome is directly retryable. A later reconcile result may prove that an operation was not applied and permit an explicit resume transition.

Error mapping is fixed as follows:

- ambiguous outcome -> `WRITE_OUTCOME_UNKNOWN`
- changed precondition -> `WRITE_CONFLICT`
- known partial workflow -> `PARTIAL_APPLY`
- missing atomic primitive -> `FEATURE_DISABLED`

## Artifacts

- `hugegraph-mcp/tests/contracts/write_confirmation_v2.json`
- `hugegraph-mcp/tests/test_write_confirmation_contract.py`

The contract tests also inspect the four existing public write-tool signatures and require them to retain the complete legacy locator group during the compatibility window.

## Verification

- Contract tests: 5 passed.
- Ruff check passed for the new test.
- Ruff format check passed.
- JSON contract loads through the test suite and contains disjoint canonical/legacy field sets.

## Result

Task 1.3 and the complete research group 1 are finished. The next approved task is 2.1: write failing tests for the canonical immutable plan/operation/receipt model and complete state-transition matrix.
