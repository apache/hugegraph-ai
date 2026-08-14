# HugeGraph MCP

[中文文档](README.zh-CN.md)

HugeGraph MCP is a Model Context Protocol server for HugeGraph. It is designed as a safe, controlled, thin adapter layer: it exposes a small set of stable tools and centralizes configuration, permission checks, read-only Gremlin validation, the dry-run/confirm write safety chain, and the unified response envelope.

**Requires HugeGraph Server >= 1.7.0** (MCP defaults to `graphspace=DEFAULT` and relies on graphspace-scoped API routes that are not available in older versions).

## Quick Start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if it is not already available. Then, from the repository root, install the MCP extra and start the stdio server:

```bash
uv sync --extra mcp --extra dev

export HUGEGRAPH_URL=http://127.0.0.1:8080
export HUGEGRAPH_GRAPH_PATH=DEFAULT/hugegraph
export HUGEGRAPH_USER=admin
export HUGEGRAPH_PASSWORD=admin
export HUGEGRAPH_MCP_READONLY=true

uv run --project hugegraph-mcp hugegraph-mcp
```

The process speaks MCP JSON-RPC on stdout; connect it from an MCP client. Keep
`HUGEGRAPH_MCP_READONLY=true` unless you have a deliberate write-validation
plan. The default toolset is `v2_core`; set `HUGEGRAPH_MCP_TOOLSET=v1` before
startup when an older client requires the 10-tool compatibility contract.

## Developer Notes

### Design Boundary

HugeGraph MCP does not turn MCP into a second business kernel. The MCP layer is responsible for:

- Exposing stable MCP tool interfaces
- Reading runtime configuration
- Enforcing permission and readonly guards
- Validating whether Gremlin is read-only
- Generating and validating `plan_hash`
- Returning a unified response envelope
- Forwarding AI capabilities to HugeGraph-AI, or graph reads/writes to HugeGraph Server

### Public Tool Surface

The default `v2_core` toolset registers 13 MCP tools: 11 normal user-facing stable tools plus 2 admin/debug tools that are registered but blocked by default.

The normal user-facing stable tools are:

- `inspect_graph_tool`
- `inspect_schema_tool`
- `query_graph_data_tool`
- `generate_gremlin_tool`
- `execute_gremlin_read_tool`
- `extract_graph_data_tool`
- `design_schema_tool`
- `apply_schema_tool`
- `mutate_graph_properties_tool`
- `import_graph_data_tool`
- `delete_graph_data_tool`

These tools are still registered in MCP, but they are admin/debug capabilities and are blocked by default when `HUGEGRAPH_MCP_ADMIN_MODE=false`. Write-capable admin tools also require `HUGEGRAPH_MCP_READONLY=false`:

- `execute_gremlin_write_tool`
- `refresh_vid_embeddings_tool`

`execute_gremlin_write_tool` is the sole break-glass exception to the write safety chain. It executes arbitrary Gremlin writes without a preview, dry-run, plan hash, or confirmation. Enable it only on an isolated transport available to trusted administrators; do not enable it on a shared agent or client endpoint.

### Toolset Selection

`HUGEGRAPH_MCP_TOOLSET` controls the public tool contract:

| Value | Tools | Intended use |
|-------|------:|--------------|
| `v1` | 10 | Compatibility mode for old clients; exposes the original stable tools and admin/debug tools, hides the three `v2_core` tools, and keeps `apply_schema_tool(mode="apply")` disabled |
| `v2_core` | 13 | New deployment default; exposes the V1 tools plus `inspect_schema_tool`, `query_graph_data_tool`, and `mutate_graph_properties_tool`, and enables the P0a schema create apply path |

When `HUGEGRAPH_MCP_TOOLSET` is unset, the server defaults to `v2_core`. Any value other than exact `v1` is treated as `v2_core`.
Toolset selection is applied when the MCP server starts and registers tools; restart the MCP server after changing this variable.

### Unified Response Envelope

High-level tools return a unified envelope:

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

When a call fails, `ok=false` and `error` uses this structure:

```json
{
  "type": "READONLY_VIOLATION",
  "message": "DATA_WRITE capability is disabled in read-only mode",
  "suggestion": "Disable HUGEGRAPH_MCP_READONLY to allow this operation.",
  "retryable": false,
  "source": "hugegraph-mcp",
  "details": {}
}
```

## Tool Reference

### User-Facing Tool Overview

| Tool | Description |
|------|-------------|
| `inspect_graph_tool` | Inspect HugeGraph Server status, schema summary, vertex/edge counts, readonly state, AI availability, and current MCP tool contract fields |
| `inspect_schema_tool` | Inspect schema objects, relations, and index labels; supports filtering by property key, vertex label, edge label, or index label |
| `query_graph_data_tool` | Query vertices or edges by typed operations (`get_by_id`, `get_by_ids`, `page`, `condition`) with explicit limits and no Gremlin full-scan fallback |
| `generate_gremlin_tool` | Generate Gremlin from natural language; defaults to generation only; `execute=true` still requires read-only validation |
| `execute_gremlin_read_tool` | Execute read-only Gremlin queries; rejects queries whose safety cannot be confirmed and supports `limit_policy` for unbounded reads |
| `extract_graph_data_tool` | Extract candidate graph data from natural language text and return vertex/edge structures without writing to HugeGraph |
| `import_graph_data_tool` | Structured graph data import entrypoint; real writes must pass `dry_run -> plan_hash -> confirm` |
| `delete_graph_data_tool` | Controlled delete entrypoint; supports only exact vertex or edge deletion, not conditional bulk delete or cascade delete |
| `design_schema_tool` | Provide schema design guidance from proposed schema operations without modifying the database |
| `apply_schema_tool` | Validate schema operations and dry-run the P0a apply scope; in `v2_core`, dry-run and confirmed `apply` support only `create_property_key`, `create_vertex_label`, and `create_edge_label`; in `v1`, real `apply` remains disabled |
| `mutate_graph_properties_tool` | Append or eliminate properties on one exact vertex or edge; both operations require `dry_run -> plan_hash -> confirm` and reject stale targets |
| `execute_gremlin_write_tool` | Execute direct Gremlin writes; disabled by default and available only when `HUGEGRAPH_MCP_ADMIN_MODE=true` and `HUGEGRAPH_MCP_READONLY=false` |
| `refresh_vid_embeddings_tool` | Refresh VID embeddings and mutate index state; disabled by default and available only when `HUGEGRAPH_MCP_ADMIN_MODE=true` and `HUGEGRAPH_MCP_READONLY=false` |

The old `query_graph_tool`, `manage_schema_tool`, and `manage_graph_data_tool` are no longer exposed as user interfaces. New integrations should use the stable tools listed above.

## Write Safety Chain

All normal user-facing write operations must follow this chain. The admin-only `execute_gremlin_write_tool` break-glass exception described above does not:

```text
dry_run=true
  -> user/agent reviews preview, warnings, matched_count, mutation_summary
  -> records plan_hash, nonce, expires_at
  -> dry_run=false + confirm=true + original payload + plan_hash + nonce + expires_at
  -> MCP revalidates target, permission, schema, payload digest, and expiry
  -> executes the write
  -> returns write/delete results and failure details
```

`plan_hash` is not just a payload hash. It binds at least:

- Tool name
- Operation mode
- Graph URL
- Graph name
- Graph space
- MCP readonly state
- Current schema hash
- Normalized payload digest
- Nonce
- Expiry

The confirm phase must fully revalidate the plan. If the dry-run result expires, the target graph changes, the schema changes, the payload changes, or permissions change, confirm must fail and require a new dry run.

### Import Semantics

`import_graph_data_tool(mode="ingest")` is the structured import path shared by `v2_core` and the `v1` compatibility toolset. It uses local schema validation, dry-run/hash/confirm, and direct Gremlin writes through `manage_graph_data()`; it does not call the HugeGraph-AI `/graph-import` HTTP path. The legacy/internal AI-backed function is named `ingest_graph_data_via_ai()`.

When `import_graph_data_tool(mode="ingest")` executes a create operation, it returns one of three states:

- `success`: all writes succeeded
- `partial` / `degraded`: some writes succeeded, some failed, or the final state cannot be fully confirmed
- `error`: the write failed

The response should include written counts, failure details, and compensation suggestions to avoid an untraceable partial write.

#### Edge Endpoint Contract

Edge endpoints accept both object and scalar forms:

```text
object source/target  -> forwarded as-is
  {"id": "1:Alice"}   -> HugeGraph vertex id match
  {"name": "Alice"}   -> complete primary-key match; arbitrary property
                         matching is not part of the public graph_data contract

scalar source/target  -> if the live schema says the endpoint label has exactly
                         one primary key, match by that primary key first;
                         otherwise fall back to {"id": value}

outV / inV / vertex id in payload -> always HugeGraph vertex id, with no
                                     primary-key remapping
```

The scalar endpoint form is a same-payload import convenience, but under a single-primary-key live schema it is resolved as a primary-key match and may match an already existing vertex in the graph. It is not limited to vertices in the current payload, so edge-only or edge-to-existing-vertex payloads are valid when the dry-run live match resolves each endpoint to exactly one vertex.

### Delete Semantics

`delete_graph_data_tool` is a controlled delete tool:

- The dry-run phase must resolve the concrete objects that would be deleted
- The confirm phase must re-match and verify that the target is unchanged
- The tool must verify after deletion that the target no longer exists
- Vertex deletion is rejected by default when the vertex has associated edges

Therefore, when deleting a vertex with associated edges, explicitly dry-run and delete the related edges first, then dry-run and delete the vertex.

## Configuration

All configuration is read from environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `HUGEGRAPH_URL` | `http://127.0.0.1:8080` | HugeGraph Server URL |
| `HUGEGRAPH_GRAPH_PATH` | `DEFAULT/hugegraph` | Graph path in `GRAPH_SPACE/GRAPH_NAME` format |
| `HUGEGRAPH_GRAPHSPACE` | unset | Override graph space separately |
| `HUGEGRAPH_GRAPH` | unset | Override graph name separately |
| `HUGEGRAPH_USER` | `admin` | HugeGraph username |
| `HUGEGRAPH_PASSWORD` | `""` | HugeGraph password |
| `HUGEGRAPH_MCP_TOOLSET` | `v2_core` | Public tool contract: `v1` for 10-tool compatibility mode, `v2_core` for the 13-tool default |
| `HUGEGRAPH_MCP_READONLY` | `true` | Whether readonly mode is enabled |
| `HUGEGRAPH_MCP_ALLOW_AI` | `false` | Whether HugeGraph-AI calls are allowed |
| `HUGEGRAPH_MCP_ADMIN_MODE` | `false` | Whether admin/debug tools are enabled |
| `HUGEGRAPH_AI_URL` | `http://127.0.0.1:8001` | HugeGraph-AI URL |
| `HUGEGRAPH_AI_TOKEN` | unset | Bearer token for an authenticated HugeGraph-AI service; public MCP tools configure this through the environment (an internal HTTP caller may override it per request) |
| `HUGEGRAPH_AI_GRAPH_URL` | unset | Graph URL used by HugeGraph-AI; defaults to `HUGEGRAPH_URL` when unset |
| `HUGEGRAPH_MCP_TIMEOUT_SECONDS` | `30` | AI call timeout in seconds |
| `HUGEGRAPH_MCP_MAX_REPEAT_TIMES` | `10` | Recommended maximum for read-cost warnings on `repeat().times(n)` |
| `HUGEGRAPH_MCP_STATE_DIR` | `$XDG_STATE_HOME/hugegraph-mcp`, or `~/.local/state/hugegraph-mcp` when `XDG_STATE_HOME` is unset | Local state directory for the persistent single-use confirmation ledger |

`HUGEGRAPH_MCP_TIMEOUT_SECONDS` only applies to HugeGraph-AI HTTP calls; it does not apply to PyHugeClient Gremlin queries. Read-only Gremlin cost boundaries are reported as non-blocking read cost guard warnings for bare full-graph scans, `repeat()` without a `times()` bound, and `path` / `group` / `profile` without `limit` or `range`.

Boolean configuration accepts `1`, `true`, `yes`, or `on` and `0`, `false`, `no`, or `off`, ignoring case and surrounding whitespace. Empty or invalid values fail closed: `HUGEGRAPH_MCP_READONLY` remains enabled, while `HUGEGRAPH_MCP_ALLOW_AI` and `HUGEGRAPH_MCP_ADMIN_MODE` remain disabled.

The confirmation ledger persists server-issued dry-run plans and consumed nonce digests. Confirm accepts only a matching server-issued plan, enforces the server's 10-minute maximum TTL, and atomically consumes it so a write plan can be used only once across local process restarts and workers sharing the same state directory. On POSIX platforms, HugeGraph MCP restricts the state directory to mode `0700` and the ledger database to mode `0600`.

Recommended safe defaults:

- `HUGEGRAPH_MCP_READONLY=true`
- `HUGEGRAPH_MCP_ALLOW_AI=false`
- `HUGEGRAPH_MCP_ADMIN_MODE=false`

Common combinations:

| Scenario | Configuration |
|----------|---------------|
| Read-only graph query | `HUGEGRAPH_MCP_READONLY=true`, `HUGEGRAPH_MCP_ALLOW_AI=false` |
| AI Gremlin generation / text extraction | `HUGEGRAPH_MCP_READONLY=true`, `HUGEGRAPH_MCP_ALLOW_AI=true` |
| Controlled import and delete | `HUGEGRAPH_MCP_READONLY=false`, set `HUGEGRAPH_MCP_ALLOW_AI=true` as needed |
| Administration/debugging | `HUGEGRAPH_MCP_READONLY=false`, `HUGEGRAPH_MCP_ADMIN_MODE=true` |

## License

Apache License 2.0
