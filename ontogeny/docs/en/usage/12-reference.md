# 12 · Reference（CLI · ENV · API · ROUTES · ERRORS）

> Part of [Part II · Usage](../README.md#part-ii--usage)

**[中文](../../zh/usage/12-reference.md)** | English

## 12.2 CLI (ontogeny)

| Command | Purpose |
|---|---|
| `validate <pkg>` · `lint <pkg>` · `docs <pkg>` | package validation / conventions / docs generation |
| `diff <old-pkg> <new-pkg>` | semantic comparison of two packages |
| `publish <pkg>` | validate + persist + compile a database snapshot; pass the same `--db` used by the service |
| `sync <type>` | run one type’s configured sync strategy once (atomic; use an external scheduler for repetition) |
| `serve [--demo] [--copy-package] [--reseed] [--data-dir DIR]` | serve (--demo fully self-contained; --open opens the browser; --no-build-ui skips the build) |
| `evolve signals \| promote <id>` | aggregate fitness signals / promote proposals by policy |
| `projection rebuild` | rebuild the graph projection (drop space → schema → Loader backfill) |


CLI database commands use `ONTOGENY_DB_DSN` or `--db`; they do not infer the running demo’s database from `--data-dir`. For example, use `--db sqlite+aiosqlite:///$PWD/.ontogeny-demo/ontogeny.db` for the default source demo. CLI publication does not notify another running process to reload; restart that process or publish through its admin API. There is no `sdk generate` command.

## 12.3 Environment variables

### Core runtime

| Variable | Default | Purpose |
|---|---|---|
| `ONTOGENY_DB_DSN` | `sqlite+aiosqlite:///./ontogeny.db` | metadata + object tables + outbox; `--demo` supplies its own SQLite DSN unless overridden. Postgres requires the `postgres` extra |
| `ONTOGENY_DATA_DIR` | demo data directory; otherwise SQLite database directory or `.ontogeny/` | directory for the owner-only `admin-bootstrap-password` file; an existing file is never overwritten |
| `ONTOGENY_ADMIN_USER` | `admin` | initial administrator username |
| `ONTOGENY_ADMIN_PASSWORD` | unset | explicit initial administrator password; no credential file is created. Does not reset an existing administrator |
| `ONTOGENY_PACKAGE_ROOT` | — | the Git working copy of the ontology package; function sources are located through it when the DB rebuilds snapshots |
| `ONTOGENY_UI_DIR` | `web/dist` | the same-origin frontend build (baked into containers) |
| `ONTOGENY_WEBHOOK_ALLOWLIST` | empty = all refused | the outbound webhook domain allowlist (anti-SSRF) |
| `ONTOGENY_DEV_AUTH` | `0` | Set to `1` only for development to accept the X-Ontogeny-Principal header. |
| `ONTOGENY_LLM_BASE_URL / ONTOGENY_LLM_MODEL` | unconfigured | the Ollama endpoint and model; unconfigured → LLM-dependent assistant, engine and function calls are unavailable |
| in-DSL `${ERP_DSN}` etc. | — | business config injected by the deployment; a missing webhook variable only affects delivery, never transactions |

## 12.4 Core API endpoints (grouped by domain · the full, live contract is `/openapi.json` with the `/api/v1` prefix)

| Domain | Endpoint | Method | Description |
|---|---|---|---|
| **meta** | `/meta/ontology` | GET | compiled snapshot export (the metadata source for SDK/MCP/frontend) |
| **meta** | `/meta/lineage` | GET | the lineage DAG |
| **objects** | `/objects/{t}/query` | POST | filter/sort/pagination/aggregation/link expansion; returns hit count and latency |
| **objects** | `/objects/{t}/{id}` · `/history` | GET | one object (masked) · version history |
| **objects** | `/objects/{t}/{id}/links/{l}` | GET | relation navigation |
| **objects** | `/objects/{t}/aggregate` | POST | count/sum/avg/min/max |
| **objects** | `/data/preview` | GET | data preview |
| **actions** | `/actions/{a}/validate` | POST | dry run: rules one by one + policy verdicts, zero writes |
| **actions** | `/actions/{a}/execute` | POST | the only write gate (expected_revision / idempotency_key) |
| **functions** | `/functions/{f}/invoke` | POST | sandboxed invocation; optional `version` anchoring (drift → 409) |
| **functions** | `/functions/{f}/versions` | GET | current content versions |
| **graph** | `/graph/explore` | POST | **neighborhood exploration**: random/specified entry + N nodes, depth-first, bidirectional dedup, reproducible seed |
| **graph** | `/graph/traverse` | POST | explicit path traversal hop by hop |
| **graph** | `/graph/projection[/vertices\|edges]` | GET | optional HugeGraph projection reads |
| **graph** | `/graph/algorithm` | POST | not implemented; returns 501 in every configuration |
| **agent** | `/agent/plugins` | GET | plugin catalog |
| **agent** | `/agent/sessions…` | POST/GET | open / list / detail / finish sessions |
| **agent** | `/agent/sessions/{id}/tools/{tool}` | POST | single-gate execution (reads run directly / writes pend approval) |
| **agent** | `/agent/sessions/{id}/run` | POST | dispatch the loop by engine.kind (builtin-llm / external-pull) |
| **agent** | `/agent/approvals…` | GET/POST | the approval queue and decisions |

Other groups: **audit** (/audit/revisions) · **evolve** (/evolve/signals · aggregate · diagnose · proposals[/eval|promote]) · **assistant** (/assistant/chat, grounding + propose modes) · **admin** (llm/status · publish · sync/{t} · outbox/dispatch · derive · projection/rebuild · **domains[/import] (zip ontology package import)**) · **subscriptions** (SSE). The complete list is at `/docs` (OpenAPI).

The normal `serve`/ASGI factory runs an outbox dispatch tick about every second and drains derivations. This does not schedule source synchronization: `sync.schedule` is declarative, and repeated source pulls require an external scheduler calling the CLI or admin sync endpoint. Manual `/api/v1/admin/outbox/dispatch` remains available and shares the background loop’s process lock.

## 12.5 Frontend routes

| Route | Page |
|---|---|
| `/` | Overview: Ontogeny intro + architecture board · ontology model · agents · the RSI loop — four sections |
| `/ontology` · `/ontology/:t` | Ontology definition (card canvas · hover highlights references) · type detail |
| `/knowledge` · `/objects/:t[/:id]` | Knowledge: semantic editing + object data / links / projection tabs (legacy /data · /objects redirect here) · object browser / detail (version timeline + link navigation) |
| `/action` · `/actions/:n` · `/functions/:n` | Kinetic layer editing (actions · functions · policy sets) · the Action runner (schema forms + dry-run + structured errors) · the function test bench |
| `/graph` | Graph explorer: neighborhood exploration (DFS) · path traversal · projection views |
| `/agent/manage` · `/evolve[/…]` | **Agent session management** (sessions / approvals / plugins; legacy /agent/* redirects) · the evolution console + proposal detail (diff / eval / promotion) |
| `/audit` · `/admin` · `/access` | Action audit · operations & extensions (LLM gateway / registry / projection / demo) · access control |

Global: ⌘K search · EN/中文 switch (persisted + `<html lang>`) · light/dark theme · **identity simulation when `ONTOGENY_DEV_AUTH=1`** (the same page shows masks or plaintext depending on the identity; overreach → 403 — the policy surface visible in the UI).

## 12.6 Error codes (localized explanations in the frontend)

| code | HTTP | Meaning |
|---|---|---|
| `RULE_REJECTED` | 422 | a business rule refused (the revision is persisted; the hit rule and revision number are attached) |
| `POLICY_DENIED` | 403 | Cedar policy refused (default-deny semantics; the refusal is audited) |
| `REVISION_CONFLICT` | 409 | optimistic-lock conflict / idempotency-key ownership conflict / function version drift |
| `CONSTITUTION_VIOLATION` | 403 | a proposal touched the constitution → dropped to T3 human review |
| `BUDGET_EXCEEDED` | 429 | the T0 weekly budget is exhausted / an agent session exceeded its budget |
| `CAPABILITY_DENIED` / `SANDBOX_ERROR` | 403/500 | sandbox capability overreach / sandbox execution failure |

## 12.7 Function execution and evaluation limits

Function source read/write/test endpoints require an administrator. A Python function runs trusted package code with resource limits; this is not operating-system isolation. The editor’s Test run does not save the edited source, publish or create a source revision, but can call external LLM/HTTP services and arbitrary Python may produce other side effects.

Scripted Agent EvalSuite cases use a disposable SQLite database and a snapshot of the live object data. Function tools and function-backed actions are refused in these cases because they can invoke external services; a case that needs them fails with an explicit error. This is distinct from the administrator’s function Test run. Query/replay cases and API contracts remain described by the live implementation and `/openapi.json`.
