# Tasks 8.1–8.5 Log: Configuration and Raw Query Safety

## Typed configuration

Central numeric field specifications now define type, default, minimum, and maximum. Timeout values are limited to 0.001–86400 seconds, AI timeout to 1–86400 seconds, result items to 1–1,000,000, result bytes to 1 byte–1 GiB, and write instance count to 1–1024. Empty, invalid, negative, non-finite, arbitrary-precision, and over-limit inputs fall back safely without raising during server import.

## Upstream envelope boundary

Thin envelope normalization is iterative and depth-limited. One compatibility wrapper is accepted; excessive depth, cycles, and malformed nested envelopes return a structured, non-retryable upstream-response error.

## Raw Gremlin

All public raw execution paths remain disabled even in admin mode:

- direct raw read;
- direct raw write;
- generated query with `execute=true`.

Generate-only behavior remains available. Re-enabling execution requires verified read-only principal enforcement, server evaluation timeout, server result cap, and streaming HTTP byte cap. Current post-materialization item/byte checks are explicitly labeled output guards with `hard_budget=false`.

A pyhugegraph contract fixture records the missing request/response capabilities and confirms that `GremlinManager.exec()` does not claim per-request timeout or streaming-budget parameters.

## Verification

- Configuration tests: 50 passed.
- HugeGraph AI client tests: 31 passed.
- Raw Gremlin focused MCP tests: 45 passed in the worker lane.
- PyHugeGraph raw-query contract tests: 2 passed.
- Complete MCP suite after integration: 689 passed, 15 skipped.
- Focused Ruff and diff checks passed.
