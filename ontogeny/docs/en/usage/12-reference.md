# 12 · Reference（CLI · ENV · API · ROUTES · ERRORS）

> Part of [Part II · Usage](../README.md#part-ii--usage)

**[中文](../../zh/usage/12-reference.md)** | English

## 12.2 CLI (ontogeny)

| Command | Purpose |
|---|---|
| `validate / lint / docs / diff <pkg>` | package validation (blocking) / conventions / docs generation / semantic diff |
| `publish <pkg>` | validate + persist + compile the snapshot (hot path switches snapshots) |
| `sync <type>` | incremental sync of one type (atomic; schedulable by Airflow) |
| `serve [--demo] [--reseed] [--data-dir]` | serve (--demo fully self-contained; --open opens the browser; --no-build-ui skips the build) |
| `evolve signals \| promote <id>` | aggregate fitness signals / promote proposals by policy |
| `projection rebuild` | rebuild the graph projection (drop space → schema → Loader backfill) |
| `sdk generate` | SDK generation (planned) |

## 12.3 Environment variables

### Core runtime

| Variable | Default | Purpose |
|---|---|---|
| `ONTOGENY_DB_DSN` | `sqlite+aiosqlite:///./ontogeny.db` | metadata + object tables + outbox (Postgres asyncpg in production) |
| `ONTOGENY_PACKAGE_ROOT` | — | the Git working copy of the ontology package; function sources are located through it when the DB rebuilds snapshots |
| `ONTOGENY_UI_DIR` | `web/dist` | the same-origin frontend build (baked into containers) |
| `ONTOGENY_WEBHOOK_ALLOWLIST` | empty = all refused | the outbound webhook domain allowlist (anti-SSRF) |
| `ONTOGENY_DEV_AUTH` | `1` | accept the X-Ontogeny-Principal header (off in production, replaced by OIDC) |
| `ONTOGENY_LLM_BASE_URL / ONTOGENY_LLM_MODEL` | unconfigured | the Ollama endpoint and model; unconfigured → assistant 503, everything else unaffected |
| in-DSL `${ERP_DSN}` etc. | — | business config injected by the deployment; a missing webhook variable only affects delivery, never transactions |

## 12.4 Core API endpoints (grouped by domain · the full, live contract is `/openapi.json` — 79 operations / 70 paths)

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
| **graph** | `/graph/projection[/vertices\|edges]` · `/graph/algorithm` | GET/POST | projection reads and graph algorithms (M3) |
| **agent** | `/agent/plugins` | GET | plugin catalog |
| **agent** | `/agent/sessions…` | POST/GET | open / list / detail / finish sessions |
| **agent** | `/agent/sessions/{id}/tools/{tool}` | POST | single-gate execution (reads run directly / writes pend approval) |
| **agent** | `/agent/sessions/{id}/run` | POST | dispatch the loop by engine.kind (builtin-llm / external-pull) |
| **agent** | `/agent/approvals…` | GET/POST | the approval queue and decisions |

Other groups: **audit** (/audit/revisions) · **evolve** (/evolve/signals · aggregate · diagnose · proposals[/eval|promote]) · **assistant** (/assistant/chat, grounding + propose modes) · **admin** (llm/status · publish · sync/{t} · outbox/dispatch · derive · projection/rebuild · **domains[/import] (zip ontology package import)**) · **subscriptions** (SSE). The complete list is at `/docs` (OpenAPI).

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

Global: ⌘K search · EN/中文 switch (persisted + `<html lang>`) · light/dark theme · **identity switching** (the same page shows masks or plaintext depending on the identity; overreach → 403 — the policy surface visible in the UI).

## 12.6 Error codes (localized explanations in the frontend)

| code | HTTP | Meaning |
|---|---|---|
| `RULE_REJECTED` | 422 | a business rule refused (the revision is persisted; the hit rule and revision number are attached) |
| `POLICY_DENIED` | 403 | Cedar policy refused (default-deny semantics; the refusal is audited) |
| `REVISION_CONFLICT` | 409 | optimistic-lock conflict / idempotency-key ownership conflict / function version drift |
| `CONSTITUTION_VIOLATION` | 403 | a proposal touched the constitution → dropped to T3 human review |
| `BUDGET_EXCEEDED` | 429 | the T0 weekly budget is exhausted / an agent session exceeded its budget |
| `CAPABILITY_DENIED` / `SANDBOX_ERROR` | 403/500 | sandbox capability overreach / sandbox execution failure |
