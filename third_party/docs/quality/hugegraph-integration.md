# HugeGraph Integration Test Service

Default image: `hugegraph/hugegraph:1.7.0`

## Environment

```text
HUGEGRAPH_URL=http://127.0.0.1:8080
HUGEGRAPH_GRAPH=hugegraph
HUGEGRAPH_USER=admin
HUGEGRAPH_PASSWORD=admin
HUGEGRAPH_GRAPHSPACE=
HUGEGRAPH_REQUIRED=true|false
```

## Semantics

- If `HUGEGRAPH_REQUIRED=true`, selected integration tests fail when the service is unavailable.
- If `HUGEGRAPH_REQUIRED=false`, local integration tests may skip when no service is present.
- Default unit/contract tests must not require Docker.
