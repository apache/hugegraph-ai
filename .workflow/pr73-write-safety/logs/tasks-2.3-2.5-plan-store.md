# Tasks 2.3–2.5 Log: Versioned PlanStore

## Migration tests

Added coverage for a fresh versioned database, legacy issued plans, consumed-only plans, existing receipts, corrupt JSON, and restart idempotency. Legacy consumed state without a trustworthy receipt becomes `LEGACY_UNKNOWN`.

## Store implementation

Added `SQLitePlanStore` backed by `write_plans.sqlite3` with:

- schema version 1;
- immutable plan payload persistence;
- ordered per-operation records;
- canonical plan round-trip;
- legal compare-and-set plan transitions;
- operation receipt persistence and aggregate plan status updates;
- idempotent import from the existing `confirmations.sqlite3` compatibility ledger.

The existing confirmation database remains the one-release legacy protocol source. Canonical plan-ID tools will use the new store; legacy rows are imported into deterministic `wp_legacy_*` and `op_legacy_*` identities.

## Interface and deployment safety

Added the runtime-checkable `PlanStore` protocol and `plan_store_from_config()` factory. SQLite is accepted only when `write_instance_count == 1`. Write capabilities fail closed with `FEATURE_DISABLED` when multiple write-enabled MCP instances are configured without a shared transactional store; reads remain available.

## Verification

- Plan model, migration, interface, config, and guard tests: 89 passed.
- Complete MCP suite after integration: 689 passed, 15 skipped.
- Ruff check passed for PlanStore and its focused tests.
- `git diff --check` passed.
