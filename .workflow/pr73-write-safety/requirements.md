# Requirements: HugeGraph MCP Confirmed Write Safety

The requirements below consolidate the user-approved PR #73 review package, the verified current implementation defects, and the approved design in `design.md`.

- **R1 — Immutable authorization:** A confirmed write must execute the exact server-persisted plan approved during dry-run. Client-resubmitted mutation payloads are never authoritative.
- **R2 — Stable graph identity:** Delete targets and edge endpoints must be bound to stable backend identities before a write. Write traversals must not re-evaluate mutable property predicates.
- **R3 — Atomic conditional delete:** `cascade=false` vertex deletion must atomically enforce the no-incident-edge precondition at the HugeGraph boundary.
- **R4 — Backend property CAS:** Property mutation must use backend-enforced expected-to-desired compare-and-set. It remains preview-only while that capability is unavailable.
- **R5 — Durable outcome model:** Every confirmed operation must have a durable state and receipt. `APPLIED`, `ALREADY_APPLIED`, `REJECTED`, `CONFLICT`, `PARTIAL`, and `UNKNOWN` must retain distinct meanings.
- **R6 — Reconciliation:** `UNKNOWN`, `PARTIAL`, and migrated legacy-unknown operations must be queryable and reconcilable. Another attempt is authorized only when durable state proves the operation was never dispatched, or a backend-enforced idempotency/fencing primitive proves replay safety; observing the expected state alone is insufficient after dispatch.
- **R7 — Schema safety:** One schema plan creates one object, uses the write timeout, and treats manager construction through post-read verification as one UNKNOWN boundary.
- **R8 — Durable import workflow:** Graph import must persist per-operation dependencies, results, and backend IDs. Partial progress must be explicit and resumable only after reconciliation.
- **R9 — Query resource boundary:** Raw Gremlin remains disabled until a read-only principal, server execution timeout, server-side result cap, and streaming response-byte cap are enforceable.
- **R10 — Typed configuration:** Timeout and budget configuration must reject invalid, non-finite, overflowing, and excessively large values without raising during server import.
- **R11 — Stable public contracts:** Confirm, status, reconcile, errors, tool registration, documentation, and compatibility behavior must agree.
- **R12 — Verifiable correctness:** Unit, migration, fault-injection, concurrency, and Docker HugeGraph 1.7 tests must prove the safety invariants and database state together.
