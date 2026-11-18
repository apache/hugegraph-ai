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

By default (`HUGEGRAPH_MCP_TRANSPORT=stdio`), the process speaks MCP JSON-RPC on stdout (`streamable-http`, `http`, and `sse` transports are also configurable). Keep `HUGEGRAPH_MCP_READONLY=true` unless controlled writes are required. Leave `HUGEGRAPH_MCP_TOOLSET` unset for the default `core` toolset. To select the 10-tool compatibility toolset, use `legacy`. For migration from `1.7.1`, see [Toolset Naming and Migration](#toolset-naming-and-migration).

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

Structured query `limit` defaults to `100` (valid range `1–500`, capped by `HUGEGRAPH_MCP_MAX_RESULT_ITEMS` when smaller). Oversized ID batches or responses exceeding `HUGEGRAPH_MCP_MAX_RESULT_ITEMS` / `HUGEGRAPH_MCP_MAX_RESULT_BYTES` are rejected without truncation.

## Public Tool Surface

With default `HUGEGRAPH_MCP_CORE_PROFILE=compat`, the `core` toolset registers 24 tools (`mcp_tool_contract_version="2.0"`), and `legacy` registers 10 tools. Setting `HUGEGRAPH_MCP_CORE_PROFILE=lean` enables the capability-filtered `3.0` contract (`prepare_write_tool`, `validate_schema_tool`, and `retrieve_context_tool` when AI is enabled, hiding disabled write/admin/AI/placeholder tools). Registration does not imply that every operation is enabled.

| Tool | Toolset | Description |
|------|----------|-------------|
| `inspect_graph_tool` | legacy, core | Inspect connection, schema summary, read-only state, and tool contract |
| `generate_gremlin_tool` | legacy, core | Generate Gremlin; execution is disabled until the hard-budget contract is verified |
| `execute_gremlin_read_tool` | legacy, core | Registered for compatibility; public raw execution currently returns `FEATURE_DISABLED` |
| `extract_graph_data_tool` | legacy, core | Extract candidate graph data without writing |
| `design_schema_tool` | legacy, core | Produce schema design guidance |
| `apply_schema_tool` | legacy, core | Validate or preview one schema create/append; core supports confirmed apply |
| `import_graph_data_tool` | legacy, core | Validate and preview structured vertex/edge creates; confirmation currently returns `FEATURE_DISABLED` |
| `delete_graph_data_tool` | legacy, core | Preview exact deletion; confirmed edge deletion is supported |
| `refresh_vid_embeddings_tool` | legacy, core | Admin write tool, disabled unless admin mode and writes are enabled |
| `execute_gremlin_write_tool` | legacy, core | Registered for compatibility; public raw execution currently returns `FEATURE_DISABLED` |
| `inspect_schema_tool` | core | Inspect and filter schema objects and relations |
| `query_graph_data_tool` | core | Perform typed, bounded vertex and edge reads |
| `traverse_graph_tool` | core | Perform bounded graph traversal (`neighbors`, `k_out`, `shortest_path`, `paths`) |
| `search_vid_embeddings_tool` | core | Search indexed vertex IDs semantically via HugeGraph-AI (requires `HUGEGRAPH_MCP_ALLOW_AI=true`) |
| `get_task_status_tool` | core | Admin read tool to inspect one HugeGraph async task without raw payload |
| `list_tasks_tool` | core | Admin read tool to list HugeGraph async tasks |
| `cancel_task_tool` | core | Admin write tool to request cancellation of a HugeGraph async task by `task_id` |
| `list_graphs_tool` | core | Admin read tool to list visible graphs in the configured graphspace |
| `mutate_graph_properties_tool` | core | Preview property changes; confirmation is disabled without atomic CAS |
| `confirm_write_tool` | core | Confirm one persisted plan by `plan_id` |
| `get_write_status_tool` | core | Read the durable plan and operation outcome by `plan_id` |
| `list_write_plans_tool` | core | List actor-owned durable write plans ordered by most recent first |
| `cancel_write_plan_tool` | core | Cancel an unexecuted `ISSUED` write plan by transitioning it to `EXPIRED` |
| `reconcile_write_tool` | core | Reconcile `UNKNOWN` or `PARTIAL` outcomes by `plan_id` using read-only checks |
| `prepare_write_tool` | lean (`3.0`) | Unified dry-run planner for `schema`, `import`, `mutate`, and `delete` writes |
| `validate_schema_tool` | lean (`3.0`) | Validate inline JSON or an `artifact_id`. With `hugegraph-llm-sdk`, the result has `validation_scope="schema_structure"`. Standalone installs check required collections and references and return `validation_scope="limited_fallback"`. |
| `retrieve_context_tool` | lean (`3.0`) | Graph/vector/hybrid evidence retrieval via HugeGraph-AI `/v1/retrieve-context` (`HUGEGRAPH_MCP_ALLOW_AI=true`) |

Empty or unknown `HUGEGRAPH_MCP_TOOLSET` values stop startup with an error; an unset variable selects `core`. Tool registration is fixed at process startup, so restart the server after changing the toolset.

## MCP Resources & Prompts

The server registers 6 MCP Resource templates (graph resources under `hugegraph://` support subscription and invalidation notifications; `plan://` subscriptions are rejected as unsupported) and 6 MCP Prompts:

### Resources

| URI Template | Name | Description |
|--------------|------|-------------|
| `hugegraph://{deployment}/{graphspace}/{graph}/schema` | `hugegraph_schema` | Bounded JSON snapshot of the HugeGraph schema with SHA-256 fingerprint |
| `hugegraph://{deployment}/{graphspace}/{graph}/summary` | `hugegraph_summary` | Graph identity, label summary, and observed counts |
| `hugegraph://{deployment}/{graphspace}/{graph}/embeddings/vid` | `hugegraph_vid_embeddings` | AI VID embedding index status for the target graph |
| `plan://{plan_id}` | `hugegraph_write_plan` | Sanitized read-only projection of an actor-owned write plan and its durable receipts |
| `artifact://{artifact_id}` | `hugegraph_artifact_manifest` | Owner-authorized manifest for an immutable extraction or preview artifact |
| `artifact://{artifact_id}/parts/{part_id}` | `hugegraph_artifact_part` | Bounded part slice of an immutable MCP artifact |

### Prompts

| Prompt | Arguments | Description |
|--------|-----------|-------------|
| `explore_graph` | `question`, `depth=2` | Guide bounded read-only graph exploration using schema and summary resources |
| `design_graph_schema` | `use_case`, `constraints?` | Guide incremental HugeGraph schema design with conflict checks |
| `review_write_plan` | `plan_id` | Review a pending write plan without triggering confirmation |
| `investigate_write_status` | `plan_id` | Guide receipt inspection and reconciliation for `PARTIAL`/`UNKNOWN` write plans |
| `ingest_text_to_graph` | `text_source`, `graph_goal?` | Guide text extraction, schema alignment, and dry-run graph import without auto-confirming |
| `optimize_gremlin_query` | `query`, `symptom?` | Guide schema-aware Gremlin query bounding and optimization |

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

The bundled SQLite plan store (`HUGEGRAPH_MCP_PLAN_STORE=sqlite`) is safe for a single write-capable MCP instance and fails closed when `HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT` is greater than one. For multi-instance deployments, install the optional PostgreSQL drivers (`hugegraph-mcp[postgres]`), configure `HUGEGRAPH_MCP_PLAN_STORE=postgres` with `HUGEGRAPH_MCP_PLAN_STORE_DSN`, and mount a shared read-write volume at `HUGEGRAPH_MCP_STATE_DIR` across all instances so `LocalArtifactStore` (`artifact://`) manifests and parts remain readable by any instance.

### Operation Boundaries

- A confirmable schema plan contains exactly one `create_property_key`, `create_vertex_label`, `create_edge_label`, `append_vertex_label`, or `append_edge_label` operation. Success is reported as `APPLIED`. Index create, `eliminate`, and `drop` remain outside the apply scope.
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
| `HUGEGRAPH_MCP_CORE_PROFILE` | `compat` | `compat` (`2.0`, 24 tools) or `lean` (`3.0`, capability-filtered tools + `prepare_write_tool`/`validate_schema_tool`/`retrieve_context_tool`) |
| `HUGEGRAPH_MCP_CONFIRMATION_MODE` | `manual` | `manual` or `elicitation` (requires interactive MCP stdio elicitation before `confirm_write_tool`) |
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
| `HUGEGRAPH_MCP_PLAN_STORE` | `sqlite` | Durable plan-store backend (`sqlite` or `postgres`) |
| `HUGEGRAPH_MCP_PLAN_STORE_DSN` | unset | PostgreSQL connection DSN (required when `HUGEGRAPH_MCP_PLAN_STORE=postgres`) |
| `HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT` | `1` | Declared count of write-capable MCP instances; SQLite requires exactly one |
| `HUGEGRAPH_MCP_STATE_DIR` | `$XDG_STATE_HOME/hugegraph-mcp` or `~/.local/state/hugegraph-mcp` | Directory for the SQLite plan store and `LocalArtifactStore` (`artifacts/`); must be a shared RWX volume in multi-instance deployments |
| `HUGEGRAPH_MCP_TRANSPORT` | `stdio` | MCP transport (`stdio`, `http`, `streamable-http`, or `sse`) |
| `HUGEGRAPH_MCP_HTTP_HOST` | `127.0.0.1` | Bind host for HTTP/SSE transports |
| `HUGEGRAPH_MCP_HTTP_PORT` | `8000` | Bind port for HTTP/SSE transports; range `1..65535` |
| `HUGEGRAPH_MCP_HTTP_PATH` | `/mcp` | Endpoint path for HTTP transport |
| `HUGEGRAPH_MCP_DEPLOYMENT` | `default` | Deployment identifier used in MCP Resource URIs |
| `HUGEGRAPH_MCP_EVENT_BUS` | `memory` | In-process event bus backend for resource invalidation notifications |
| `HUGEGRAPH_MCP_GRAPH_ROUTES` | unset | JSON route definitions. Public graph tools use the `default` route's connection and enforce its tenant, scope and readonly policy. The global readonly setting also applies. Tool arguments do not select other aliases. |
| `HUGEGRAPH_MCP_OAUTH_ISSUER` | unset | Expected OAuth2/OIDC token `iss` claim for bearer verification |
| `HUGEGRAPH_MCP_OAUTH_AUDIENCE` | unset | Expected OAuth2/OIDC token `aud` claim |
| `HUGEGRAPH_MCP_OAUTH_JWKS_URL` | unset | Remote JWKS URL for RS256/ES256 bearer token verification |
| `HUGEGRAPH_MCP_OAUTH_JWKS_JSON` | unset | Inline JWKS JSON string (takes precedence over remote fetch when set) |

Boolean values accept `1/true/yes/on` and `0/false/no/off`, case-insensitively. Invalid values use safe defaults. Invalid, non-finite, or out-of-range numeric values use the documented defaults.

Recommended defaults are `HUGEGRAPH_MCP_READONLY=true`, `HUGEGRAPH_MCP_ALLOW_AI=false`, and `HUGEGRAPH_MCP_ADMIN_MODE=false`.

### AI Service Configuration

To enable AI-backed tools (`search_vid_embeddings_tool`, `refresh_vid_embeddings_tool`, `extract_graph_data_tool`, `design_schema_tool`, `generate_gremlin_tool`):

1. Set `HUGEGRAPH_MCP_ALLOW_AI=true`, `HUGEGRAPH_AI_URL`, and `HUGEGRAPH_AI_TOKEN` (if bearer auth is enabled) on MCP.
2. Configure `GRAPH_URL`, `GRAPH_NAME`, and `GRAPH_SPACE` directly on the HugeGraph-AI service so they point to the same target graph as MCP (an unset or blank `GRAPH_SPACE` maps to `DEFAULT`; `HUGEGRAPH_AI_GRAPH_URL` is ignored).
3. For `refresh_vid_embeddings_tool` (`POST /v1/vid-embeddings/refresh`), enable `HUGEGRAPH_MCP_READONLY=false`, `HUGEGRAPH_MCP_ADMIN_MODE=true`, and pass `confirm=true` on MCP; on HugeGraph-AI, enable `ENABLE_LOGIN=true`, `HUGEGRAPH_LLM_ENABLE_THIN_WRITES=true`, and configure `USER_TOKEN` matching `HUGEGRAPH_AI_TOKEN`.

## License

Apache License 2.0
