# Task 1.2 Log: HugeGraph 1.7 Backend Capabilities

## Scope

Inspected HugeGraph 1.7 server configuration from `hugegraph/hugegraph:1.7.0`, the local pyhugegraph request and graph APIs, the existing Docker integration tests, and official HugeGraph 1.7 authentication/configuration documentation. Encoded only evidence-backed conclusions; unknown version/backend combinations fail closed.

## Evidence

- Docker `conf/gremlin-server.yaml` configures `evaluationTimeout: 30000`.
- HugeGraph 1.7 documents the REST-to-Gremlin wait timeout as `gremlinserver.timeout`.
- HugeGraph 1.7 documents `task.result_size_limit`; this applies to task/job results, not general `/gremlin` responses.
- Docker graph config contains `memory.one_query_max_capacity`, but it is commented out by default and its Gremlin/backend behavior was not proven.
- `GraphManager` exposes unconditional vertex/edge create and ID-based update/delete APIs. It has no expected-state CAS or graph-data create-if-absent parameter.
- Schema `ifNotExist()` does not establish a graph-data conditional-create capability.
- Existing HugeGraph 1.7 Docker tests prove edge IDs can be returned and addressed by ID. They do not prove duplicate-edge uniqueness or idempotency.
- The current pyhugegraph request layer uses `requests` without `stream=True` and materializes JSON/text before returning it.
- HugeGraph 1.7 StandardAuthenticator supports users, groups, operation permissions, and resource scopes. The default Docker image does not enable authentication.

## Encoded profile

Added `hugegraph_mcp.backend_capabilities` with:

- `BackendFeature`
- `SupportStatus`
- immutable `CapabilityEvidence`
- immutable, complete `BackendProfile`
- exact-match `profile_for(server_version, backend)` lookup

Only `VERIFIED_SUPPORTED` enables `supports()`. Both `VERIFIED_UNSUPPORTED` and `UNKNOWN` fail closed.

### HugeGraph 1.7.0 + RocksDB

| Feature | Status | Reason |
|---|---|---|
| Vertex create-if-absent | `VERIFIED_UNSUPPORTED` | Local graph client exposes unconditional POST only. |
| Edge create-if-absent | `VERIFIED_UNSUPPORTED` | Local graph client exposes unconditional POST only. |
| Edge ID stable addressing | `VERIFIED_SUPPORTED` | Docker integration proves returned edge ID round-trip and ID-based access. |
| Edge idempotent identity | `UNKNOWN` | Duplicate-edge uniqueness is not proven. |
| Isolated vertex delete | `UNKNOWN` | Ordered scenario passes; simultaneous transaction isolation is not proven. |
| Property compare-and-set | `VERIFIED_UNSUPPORTED` | Append/eliminate APIs have no expected-state field. |
| Gremlin evaluation timeout | `VERIFIED_SUPPORTED` | Docker server config sets 30 seconds. |
| REST Gremlin wait timeout | `VERIFIED_SUPPORTED` | HugeGraph 1.7 server configuration exposes it. |
| Task result-size limit | `VERIFIED_SUPPORTED` | Applies to task/job results only. |
| Query memory limit | `UNKNOWN` | Config exists but is disabled by default and unverified. |
| General Gremlin result-item limit | `UNKNOWN` | No general `/gremlin` cap was verified. |
| HTTP streaming response limit | `VERIFIED_UNSUPPORTED` | Current client fully materializes responses. |
| Read-only principal | `VERIFIED_SUPPORTED` | Server auth model supports resource/operation permissions; configuration is required. |

No capability is inferred for HStore or future server versions. Runtime code must not assume the configured backend from the server version or Docker default.

## Verification

- `test_backend_capabilities.py`: 17 passed.
- Ruff check passed for the new module and tests.
- Ruff format check passed after applying repository formatting.
- The test suite covers profile completeness, expected evidence states, immutable records, unknown-profile behavior, and fail-closed `supports()` semantics.

## Result

Task 1.2 is complete. Task 1.3 can now define the legacy hash/nonce compatibility contract and the new plan-ID contract without assuming unavailable HugeGraph primitives.
