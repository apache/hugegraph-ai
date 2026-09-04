# HugeGraph MCP

[中文文档](README.zh-CN.md)

HugeGraph MCP is a safe, controlled Model Context Protocol adapter for HugeGraph Server. It exposes stable structured tools, centralizes configuration and permission checks, and persists immutable write plans and outcomes.

**Requires HugeGraph Server >= 1.7.0.** The default graph path is `DEFAULT/hugegraph` and uses graphspace-scoped APIs unavailable in older releases.

## Quick Start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then start the server in read-only mode:

```bash
export HUGEGRAPH_URL=http://hugegraph.example.com:8080
export HUGEGRAPH_GRAPH_PATH=DEFAULT/hugegraph
export HUGEGRAPH_USER=admin
export HUGEGRAPH_PASSWORD=admin
export HUGEGRAPH_MCP_READONLY=true

uvx --from hugegraph-mcp==1.7.0 hugegraph-mcp
```

The process speaks MCP JSON-RPC on stdout. Keep `HUGEGRAPH_MCP_READONLY=true` unless controlled writes are required. The default toolset is `v2_core`; set `HUGEGRAPH_MCP_TOOLSET=v1` before startup only for the legacy 10-tool contract.

For MCP clients that accept JSON server configuration:

```json
{
  "mcpServers": {
    "hugegraph": {
      "command": "uvx",
      "args": ["--from", "hugegraph-mcp==1.7.0", "hugegraph-mcp"],
      "env": {
        "HUGEGRAPH_URL": "http://hugegraph.example.com:8080",
        "HUGEGRAPH_GRAPH_PATH": "DEFAULT/hugegraph",
        "HUGEGRAPH_USER": "admin",
        "HUGEGRAPH_PASSWORD": "admin",
        "HUGEGRAPH_MCP_READONLY": "true"
      }
    }
  }
}
```

## Developer Notes

Run from the repository checkout while keeping the repository path explicit:

```bash
export PYTHONPATH=/Users/uleng/Code/hugegraph-ai-pr73-mcp/hugegraph-mcp:/Users/uleng/Code/hugegraph-ai-pr73-mcp/hugegraph-python-client/src
/Users/uleng/Code/hugegraph-ai-pr73-mcp/.venv/bin/python -m hugegraph_mcp.server
```

This command uses the checkout's existing root virtual environment and forces both
`hugegraph-mcp` and its sibling Python client to resolve from the current checkout.
It does not ask uv to solve the standalone `hugegraph-mcp` subproject, which would
try to satisfy `hugegraph-python-client>=1.7.0` from a package index instead of the
sibling source tree.

The MCP layer exposes stable tools, reads runtime configuration, enforces permissions, validates structured requests, persists write plans and receipts, and delegates graph operations to HugeGraph Server or enabled AI operations to HugeGraph-AI.

## Public Tool Surface

The default `v2_core` contract registers 16 tools. The `v1` compatibility contract registers 10 tools and omits the six v2 additions.

| Tool | Contract | Description |
|------|----------|-------------|
| `inspect_graph_tool` | v1, v2 | Inspect connection, schema summary, read-only state, and tool contract |
| `generate_gremlin_tool` | v1, v2 | Generate Gremlin; execution is disabled until the hard-budget contract is verified |
| `execute_gremlin_read_tool` | v1, v2 | Registered for compatibility; public raw execution currently returns `FEATURE_DISABLED` |
| `extract_graph_data_tool` | v1, v2 | Extract candidate graph data without writing |
| `design_schema_tool` | v1, v2 | Produce schema design guidance |
| `apply_schema_tool` | v1, v2 | Validate or preview one schema create; v2 supports confirmed apply |
| `import_graph_data_tool` | v1, v2 | Validate and preview structured vertex/edge creates; confirmation currently returns `FEATURE_DISABLED` |
| `delete_graph_data_tool` | v1, v2 | Preview exact deletion; confirmed edge deletion is supported |
| `refresh_vid_embeddings_tool` | v1, v2 | Admin write tool, disabled unless admin mode and writes are enabled |
| `execute_gremlin_write_tool` | v1, v2 | Registered for compatibility; public raw execution currently returns `FEATURE_DISABLED` |
| `inspect_schema_tool` | v2 | Inspect and filter schema objects and relations |
| `query_graph_data_tool` | v2 | Perform typed, bounded vertex and edge reads |
| `mutate_graph_properties_tool` | v2 | Preview property changes; confirmation is disabled without atomic CAS |
| `confirm_write_tool` | v2 | Confirm one persisted plan by `plan_id` |
| `get_write_status_tool` | v2 | Read the durable plan and operation outcome by `plan_id` |
| `reconcile_write_tool` | v2 | Reconcile `UNKNOWN` or `PARTIAL` outcomes by `plan_id` using read-only checks |

Invalid `HUGEGRAPH_MCP_TOOLSET` values fail closed to `v1`. Tool registration is fixed at process startup, so restart the server after changing the toolset.

## Unified Response Envelope

High-level tools return:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "warnings": [],
  "next_actions": [],
  "meta": {
    "request_id": "req-...",
    "graph": "hugegraph",
    "graphspace": "DEFAULT",
    "readonly": true,
    "duration_ms": 12.3
  }
}
```

Failures set `ok=false`; `error.type` is a stable machine-readable code and `error.retryable` must be observed.

## Write Safety Contract

Canonical writes use only a server-issued `plan_id`:

```text
structured dry-run
  -> review concrete targets, warnings, and mutation summary
  -> receive immutable persisted plan_id
  -> confirm_write_tool(plan_id)
  -> get_write_status_tool(plan_id)
  -> if required, reconcile_write_tool(plan_id)
```

The confirmation call never accepts the original payload. The persisted plan is the sole execution authority. Each operation records a durable receipt, and reusing a completed `plan_id` returns its recorded outcome rather than applying the write again.

`APPLIED` means every operation is proven applied. `PARTIAL` means at least one operation was applied and the workflow did not completely apply. `UNKNOWN` means the service cannot prove whether an operation committed, so callers must query status and reconcile; they must not blindly repeat the write.

The old `plan_hash`, `nonce`, and `expires_at` locator remains on legacy write entry points for the single compatibility release immediately following introduction of the plan-ID contract. All three fields are required together, cannot be mixed with `plan_id`, and produce a `LEGACY_CONFIRMATION_DEPRECATED` warning. New integrations must use `confirm_write_tool(plan_id)`.

The bundled SQLite plan store is safe for a single write-capable MCP instance. Configure a shared transactional store before deploying multiple write instances; the current package fails closed when `HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT` is greater than one with the SQLite backend.

### Operation Boundaries

- A confirmable schema plan contains exactly one `create_property_key`, `create_vertex_label`, or `create_edge_label` operation. Success is reported as `APPLIED`. Index create, append/eliminate, and drop remain outside the apply scope.
- Graph import is always preview-only because atomic create-if-absent capability has not been verified for HugeGraph 1.7.0. Its preview sets `confirmable=false` and `preview_only=true`, issues no `plan_id`, and confirmation returns `FEATURE_DISABLED` without writing.
- Property mutation is preview-only because HugeGraph 1.7.0 does not expose an atomic compare-and-set property update. Confirmation returns `FEATURE_DISABLED`.
- Isolated vertex deletion is preview-only. Docker concurrency testing proved that HugeGraph 1.7.0 cannot atomically guarantee “delete only if no incident edge”; confirmation returns `FEATURE_DISABLED`. Delete incident edges explicitly, then use an independently controlled maintenance path for the vertex.
- Exact edge deletion remains confirmable because the plan binds the concrete edge ID.

Schema and graph-data dry-runs reject more than 200 operations or payloads larger than 1 MiB before returning a usable preview or plan.

### Raw Gremlin Boundary

Every public raw Gremlin execution path is disabled, including `execute_gremlin_read_tool`, `execute_gremlin_write_tool`, and `generate_gremlin_tool(execute=true)`. Admin mode does not override this gate. Raw execution can be opened only after the deployment proves server evaluation and wait timeouts, a server-side result-item cap, a client streaming byte cap, and a read-only principal. Post-materialization item or byte checks are output guards, not hard resource budgets.

Structured reads and `generate_gremlin_tool(execute=false)` remain available.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `HUGEGRAPH_URL` | `http://127.0.0.1:8080` | HugeGraph Server URL |
| `HUGEGRAPH_GRAPH_PATH` | `DEFAULT/hugegraph` | `GRAPH_SPACE/GRAPH_NAME` |
| `HUGEGRAPH_GRAPHSPACE`, `HUGEGRAPH_GRAPH` | unset | Explicit values that override `HUGEGRAPH_GRAPH_PATH` |
| `HUGEGRAPH_USER` | `admin` | HugeGraph username |
| `HUGEGRAPH_PASSWORD` | empty | HugeGraph password |
| `HUGEGRAPH_MCP_TOOLSET` | `v2_core` | `v1` or `v2_core`; invalid values fall back to `v1` |
| `HUGEGRAPH_MCP_READONLY` | `true` | Disable all controlled writes when true |
| `HUGEGRAPH_MCP_ALLOW_AI` | `false` | Allow HugeGraph-AI calls |
| `HUGEGRAPH_MCP_ADMIN_MODE` | `false` | Enable eligible admin/debug tools |
| `HUGEGRAPH_AI_URL` | `http://127.0.0.1:8001` | HugeGraph-AI URL |
| `HUGEGRAPH_AI_TOKEN` | unset | Optional HugeGraph-AI bearer token |
| `HUGEGRAPH_AI_GRAPH_URL` | unset | Graph URL presented to HugeGraph-AI; falls back to `HUGEGRAPH_URL` |
| `HUGEGRAPH_CONNECT_TIMEOUT_SECONDS` | `0.5` | HugeGraph connection timeout; range `0.001..86400` |
| `HUGEGRAPH_READ_TIMEOUT_SECONDS` | `15` | Structured HugeGraph read timeout; range `0.001..86400` |
| `HUGEGRAPH_WRITE_TIMEOUT_SECONDS` | `15` | HugeGraph data and schema write timeout; range `0.001..86400` |
| `HUGEGRAPH_AI_TIMEOUT_SECONDS` | `30` | HugeGraph-AI HTTP timeout; range `1..86400` |
| `HUGEGRAPH_MCP_TIMEOUT_SECONDS` | `30` | Deprecated fallback for AI timeout |
| `HUGEGRAPH_MCP_MAX_RESULT_ITEMS` | `100` | Post-materialization output item guard; range `1..1000000` |
| `HUGEGRAPH_MCP_MAX_RESULT_BYTES` | `1048576` | Post-materialization output byte guard; range `1..1073741824` |
| `HUGEGRAPH_MCP_PLAN_STORE` | `sqlite` | Durable plan-store backend; only `sqlite` is currently supported |
| `HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT` | `1` | Declared count of write-capable MCP instances; SQLite requires exactly one |
| `HUGEGRAPH_MCP_STATE_DIR` | `$XDG_STATE_HOME/hugegraph-mcp` or `~/.local/state/hugegraph-mcp` | Directory containing the plan, operation, and receipt database |

Boolean values accept `1/true/yes/on` and `0/false/no/off`, case-insensitively. Invalid values use safe defaults. Invalid, non-finite, or out-of-range numeric values use the documented defaults.

Recommended defaults are `HUGEGRAPH_MCP_READONLY=true`, `HUGEGRAPH_MCP_ALLOW_AI=false`, and `HUGEGRAPH_MCP_ADMIN_MODE=false`.

## License

Apache License 2.0
