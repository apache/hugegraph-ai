# HugeGraph MCP

[中文文档](README.zh-CN.md)

HugeGraph MCP is a safe, controlled Model Context Protocol adapter for HugeGraph Server. It exposes stable structured tools, centralizes configuration and permission checks, and persists immutable write plans and outcomes.

**Requires HugeGraph Server >= 1.7.0.** The default graph path is `DEFAULT/hugegraph` and uses graphspace-scoped APIs unavailable in older releases.

## Quick Start

Installing a published package does not require cloning this repository. The
commands below target the release prepared by this checkout and become available
after publication to PyPI. Before publication, use the
[developer setup](#developer-notes). This release uses `core`/`legacy`; the previous
`1.7.1` release uses `v2_core`/`v1`. See the [release workflow](docs/releasing.md).

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then start the server in read-only mode:

```bash
export HUGEGRAPH_URL=http://hugegraph.example.com:8080
export HUGEGRAPH_GRAPH_PATH=DEFAULT/hugegraph
export HUGEGRAPH_USER=admin
export HUGEGRAPH_PASSWORD=admin
export HUGEGRAPH_MCP_READONLY=true

uvx hugegraph-mcp@1.8.0
```

The process speaks MCP JSON-RPC on stdout. Keep `HUGEGRAPH_MCP_READONLY=true` unless controlled writes are required. Leave `HUGEGRAPH_MCP_TOOLSET` unset for the default `core` toolset. To select the 10-tool compatibility toolset, use `legacy`. For migration from `1.7.1`, see [Toolset Naming and Migration](#toolset-naming-and-migration).

For MCP clients that accept JSON server configuration:

```json
{
  "mcpServers": {
    "hugegraph": {
      "command": "uvx",
      "args": ["hugegraph-mcp@1.8.0"],
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

To try both packages from the same checkout, run from the repository root:

```bash
uvx --no-config --no-cache --with ./hugegraph-python-client --from ./hugegraph-mcp hugegraph-mcp
```

From the root of the PR checkout, install uv, then create an isolated environment and install both packages from this branch:

```bash
uv venv --python 3.12 .venv-mcp
uv --no-config pip install --python .venv-mcp -e ./hugegraph-python-client -e ./hugegraph-mcp
```

Set the HugeGraph URL and credentials shown above for your server, then start on macOS/Linux:

```bash
.venv-mcp/bin/python -m hugegraph_mcp.server
```

On Windows PowerShell (set variables with `$env:NAME="value"`):

```powershell
.\.venv-mcp\Scripts\python.exe -m hugegraph_mcp.server
```

Both packages load from this checkout; no author-specific path or pre-existing environment is required. `--no-config` keeps installation independent of the root workspace configuration.

For an MCP client, set `command` to the absolute path of this Python interpreter in your own checkout and `args` to `["-m", "hugegraph_mcp.server"]`.

After connecting, call `inspect_graph_tool(include_raw_schema=true)` and check that `hugegraph_server_status="available"`. Then run a bounded structured query, replacing `person` with an existing label:

```json
{"name":"query_graph_data_tool","arguments":{"target":"vertex","operation":"page","label":"person","limit":5}}
```

[Architecture and roadmap](docs/architecture.md) · [Integration checklist](docs/integration.md) · [Release order](docs/releasing.md)

MCP Inspector can verify the connection and run `inspect_graph_tool(include_counts=true)`:

![MCP Inspector graph inspection](https://raw.githubusercontent.com/hugegraph/hugegraph-ai/fb6a3d91c26fc82cc4e0a98667e9d49418659bcf/docs/images/mcp/inspector.png)

Structured query `limit` defaults to `100` and must be an integer in `1–500`; values above `500` return `VALIDATION_ERROR`. Valid values are then reduced to `HUGEGRAPH_MCP_MAX_RESULT_ITEMS` when that configured ceiling is smaller (for example, `limit=100` with a ceiling of `50` uses `50`). ID batches exceeding the effective limit are rejected before querying. Responses exceeding the item or byte limit are rejected without truncation or a continuation cursor; these checks do not bound backend execution or transport memory.

## Public Tool Surface

The default `core` toolset registers 16 tools. The `legacy` compatibility toolset registers 10 tools and omits the six core-only tools. Registration does not imply that every operation is enabled.

| Tool | Toolset | Description |
|------|----------|-------------|
| `inspect_graph_tool` | legacy, core | Inspect connection, schema summary, read-only state, and tool contract |
| `generate_gremlin_tool` | legacy, core | Generate Gremlin; execution is disabled until the hard-budget contract is verified |
| `execute_gremlin_read_tool` | legacy, core | Registered for compatibility; public raw execution currently returns `FEATURE_DISABLED` |
| `extract_graph_data_tool` | legacy, core | Extract candidate graph data without writing |
| `design_schema_tool` | legacy, core | Produce schema design guidance |
| `apply_schema_tool` | legacy, core | Validate or preview one schema create; core supports confirmed apply |
| `import_graph_data_tool` | legacy, core | Validate and preview structured vertex/edge creates; confirmation currently returns `FEATURE_DISABLED` |
| `delete_graph_data_tool` | legacy, core | Preview exact deletion; confirmed edge deletion is supported |
| `refresh_vid_embeddings_tool` | legacy, core | Admin write tool, disabled unless admin mode and writes are enabled |
| `execute_gremlin_write_tool` | legacy, core | Registered for compatibility; public raw execution currently returns `FEATURE_DISABLED` |
| `inspect_schema_tool` | core | Inspect and filter schema objects and relations |
| `query_graph_data_tool` | core | Perform typed, bounded vertex and edge reads |
| `mutate_graph_properties_tool` | core | Preview property changes; confirmation is disabled without atomic CAS |
| `confirm_write_tool` | core | Confirm one persisted plan by `plan_id` |
| `get_write_status_tool` | core | Read the durable plan and operation outcome by `plan_id` |
| `reconcile_write_tool` | core | Reconcile `UNKNOWN` or `PARTIAL` outcomes by `plan_id` using read-only checks |

Empty or unknown `HUGEGRAPH_MCP_TOOLSET` values stop startup with an error; an unset variable selects `core`. Tool registration is fixed at process startup, so restart the server after changing the toolset.

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

## Toolset Naming and Migration

`core` and `legacy` select groups of tools within one package. They are not
package releases, HugeGraph Server versions, or MCP protocol versions. Both
toolsets report `mcp_tool_contract_version="2.0"`; selecting a smaller toolset
does not change that contract version.

For deployments upgrading from `1.7.1`:

- Replace `HUGEGRAPH_MCP_TOOLSET=v2_core` with `core`, and `v1` with `legacy`.
  The old values remain accepted as deprecated input aliases and log a warning
  on startup. They do not select separate implementations.
- `inspect_graph_tool` now reports only `core` or `legacy` in both `data.toolset`
  and `meta.toolset`, even when an old alias was supplied. Update clients that
  compare these fields; there is no second, parallel toolset field.
- Unset the variable for the default. Empty or unknown values (including `v2`)
  now prevent startup instead of falling back to the compatibility toolset.
- Restart after configuration changes. Tool registration, routing, and reported
  toolset all use the same startup selection.

Backward-compatible additions belong to `core`; adding a tool does not create a
new numbered toolset. `legacy` retains its compatibility surface with necessary
fixes. Breaking tool changes and eventual alias removal require an explicit
migration notice and the project's release compatibility process; this change
does not schedule alias removal. Neither toolset bypasses readonly, AI, admin,
or backend capability checks.

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

Structured reads remain available. `generate_gremlin_tool(execute=false)` additionally requires `HUGEGRAPH_MCP_ALLOW_AI=true` and a configured AI service.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `HUGEGRAPH_URL` | `http://127.0.0.1:8080` | HugeGraph Server URL |
| `HUGEGRAPH_GRAPH_PATH` | `DEFAULT/hugegraph` | `GRAPH_SPACE/GRAPH_NAME` |
| `HUGEGRAPH_GRAPHSPACE`, `HUGEGRAPH_GRAPH` | unset | Explicit values that override `HUGEGRAPH_GRAPH_PATH` |
| `HUGEGRAPH_USER` | `admin` | HugeGraph username |
| `HUGEGRAPH_PASSWORD` | empty | HugeGraph password |
| `HUGEGRAPH_MCP_TOOLSET` | `core` | `core` or `legacy`; empty/unknown values prevent startup |
| `HUGEGRAPH_MCP_READONLY` | `true` | Disable all controlled writes when true |
| `HUGEGRAPH_MCP_ALLOW_AI` | `false` | Allow HugeGraph-AI calls |
| `HUGEGRAPH_MCP_ADMIN_MODE` | `false` | Enable eligible admin/debug tools |
| `HUGEGRAPH_AI_URL` | `http://127.0.0.1:8001` | HugeGraph-AI URL |
| `HUGEGRAPH_AI_TOKEN` | unset | Optional HugeGraph-AI bearer token |
| `HUGEGRAPH_AI_GRAPH_URL` | unset | Deprecated, ignored; configure `GRAPH_URL` on the AI service instead |
| `HUGEGRAPH_CONNECT_TIMEOUT_SECONDS` | `0.5` | HugeGraph connection timeout; range `0.001..86400` |
| `HUGEGRAPH_READ_TIMEOUT_SECONDS` | `15` | Structured HugeGraph read timeout; range `0.001..86400` |
| `HUGEGRAPH_WRITE_TIMEOUT_SECONDS` | `15` | HugeGraph data and schema write timeout; range `0.001..86400` |
| `HUGEGRAPH_AI_TIMEOUT_SECONDS` | `30` | HugeGraph-AI HTTP timeout; range `1..86400` |
| `HUGEGRAPH_MCP_TIMEOUT_SECONDS` | `30` | Deprecated fallback for AI timeout |
| `HUGEGRAPH_MCP_MAX_RESULT_ITEMS` | `100` | Post-materialization output item guard; range `1..1000000` |
| `HUGEGRAPH_MCP_MAX_RESULT_BYTES` | `1048576` | Post-materialization output byte guard; range `1..1073741824` |
| `HUGEGRAPH_MCP_MAX_REPEAT_TIMES` | `10` | Depth above which `repeat().times(n)` produces a Gremlin cost warning; the warning does not block the query |
| `HUGEGRAPH_MCP_PLAN_STORE` | `sqlite` | Durable plan-store backend; only `sqlite` is currently supported |
| `HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT` | `1` | Declared count of write-capable MCP instances; SQLite requires exactly one |
| `HUGEGRAPH_MCP_STATE_DIR` | `$XDG_STATE_HOME/hugegraph-mcp` or `~/.local/state/hugegraph-mcp` | Directory containing the plan, operation, and receipt database |

Boolean values accept `1/true/yes/on` and `0/false/no/off`, case-insensitively. Invalid values use safe defaults. Invalid, non-finite, or out-of-range numeric values use the documented defaults.

Recommended defaults are `HUGEGRAPH_MCP_READONLY=true`, `HUGEGRAPH_MCP_ALLOW_AI=false`, and `HUGEGRAPH_MCP_ADMIN_MODE=false`.

### AI Service Configuration

Set `HUGEGRAPH_MCP_ALLOW_AI=true`, the reachable `HUGEGRAPH_AI_URL`, and
`HUGEGRAPH_AI_TOKEN` when the AI service requires bearer authentication. Configure
`GRAPH_URL`, `GRAPH_NAME`, and `GRAPH_SPACE` on the AI service itself. Its address
must be reachable from that service (for example, `http://server:8080` inside
Docker), and its graph/graphspace must match the MCP target. Changing MCP's
`HUGEGRAPH_URL` does not reconfigure the AI service. `HUGEGRAPH_AI_GRAPH_URL` is
ignored and is not a way to override the AI target.
For the default MCP target `DEFAULT/hugegraph`, set AI `GRAPH_NAME=hugegraph`.
An unset, null, empty, or whitespace-only AI graphspace is equivalent to
`GRAPH_SPACE=DEFAULT` for target validation. This comparison does not change
stored configuration or the existing vector-index path convention.

Refresh requires MCP writes enabled, admin mode, AI enabled, and `confirm=true`.
For the current AI source, also set `ENABLE_LOGIN=true` and
`HUGEGRAPH_LLM_ENABLE_THIN_WRITES=true` on the AI service, configure a strong
`USER_TOKEN`, and supply it through `HUGEGRAPH_AI_TOKEN`. These AI-side write gates
apply to this implementation; older deployments may lack them. Verify the actual
service version rather than assuming every AI deployment implements these gates.

The current MCP refresh path checks `GET /vid-embeddings/refresh-capabilities` for
`protocol_version=1`, then sends both expected target fields to
`POST /v1/vid-embeddings/refresh`. This versioned POST requires the fields and
validates them under the same configuration lock as the refresh. Discovery alone
cannot guarantee that the POST reaches the same replica during a rolling upgrade;
the versioned POST is the validation boundary. If an older replica lacks that
route, MCP reports that an AI upgrade is required and never falls back to
`POST /vid-embeddings/refresh`. The legacy route still accepts empty requests from
authenticated callers with writes enabled, for compatibility.

Target validation checks graph names and graphspace, not whether MCP and AI
connect to the same physical server; operators must configure and verify both
addresses. Refresh reads graph IDs/schema and updates the VID vector index; it
does not write graph records.

## License

Apache License 2.0
