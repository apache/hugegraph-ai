# HugeGraph AI Test Taxonomy

## Layer A: Unit / Pure Contract

- Markers: `unit` or `contract`.
- No Docker, network, real HugeGraph, real LLM provider, embedding provider, reranker provider, vector DB, or UI service.
- Use fakes, fixtures, monkeypatches, and public APIs.

## Layer B: HugeGraph Server Contract

- Markers: `integration` and `hugegraph`.
- Requires HugeGraph Server, default `hugegraph/hugegraph:1.7.0`.
- If selected with `HUGEGRAPH_REQUIRED=true`, service connection failures fail.
- Must import production code and validate real server behavior.

## Layer C: Core Pipeline Smoke

- Marker: `smoke`; also use `integration` and `hugegraph` when real HugeGraph is required.
- Uses production flow/node/operator code.
- Uses fake LLM and deterministic embeddings/vector fixtures.
- Does not define local replacement pipeline implementations inside tests.

## Layer D: External Provider / Optional E2E

- Markers: `external` and usually `slow`.
- May require real provider credentials or non-HugeGraph services.
- Excluded from default PR gates.

## Required Skip Semantics

Do not silently skip selected Layer B tests. Prefer not selecting integration tests locally.
If `HUGEGRAPH_REQUIRED=true`, unavailable HugeGraph is a failure.
