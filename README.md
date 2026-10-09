# ontogeny

[![License](https://img.shields.io/badge/license-Apache%202-0E78BA.svg)](./LICENSE)
[![Backend Tests](https://img.shields.io/badge/pytest-561%20passed-brightgreen.svg)](#-contributing)
[![Frontend Tests](https://img.shields.io/badge/vitest-245%20passed-brightgreen.svg)](#-contributing)

`ontogeny` — named after the biological term for the *development of an individual organism* — is a **self-improving operational ontology platform**: it models an enterprise's business semantics (objects, properties, links) and business actions (actions, functions, policies) as declarative, Git-native YAML, and serves them to applications, analytics and AI agents through one governed API — optionally projected onto [Apache HugeGraph](https://github.com/apache/hugegraph) for deep-graph queries.

The design references the Palantir Foundry Ontology (semantic layer + dynamic action layer) but is fully open: **the DSL is the single source of truth** — object tables and the graph schema are compiled artifacts that can be deleted and rebuilt at any time.

## ✨ Key Features

- **Git-native ontology** — modeling is YAML + pull requests; consensus happens in code review, not a locked GUI
- **Single-process kernel** — `ontogeny serve` = Registry + query engine + Action runtime on SQLite / Postgres
- **Agent-first** — a governed MCP tool surface at `/mcp`; agents and humans share one policy surface, writes pass human approval gates
- **Self-improving (RSI)** — observe → mutate (LLM-generated DSL diffs) → select (deterministic eval suites) → release (T0 auto-merge / T1 PR / T2 canary); *mutation is outsourced to the LLM, the selection function is not*
- **Constitutional guardrails** — machine proposals travel the same Git/CI channel as humans; policy relaxation, markings and tier definitions always require human review
- **Bilingual enterprise console** — React 19 + TypeScript: ontology canvas (browse *and* edit), graph exploration, action runner, audit, self-evolution console

## 🚀 Quick Start

### Option 1: Docker (Recommended)

```bash
git clone https://github.com/apache/hugegraph-ai.git
cd hugegraph-ai/ontogeny

docker compose up -d          # self-contained demo (SQLite + seeded data)
# docker compose --profile postgres up -d   # Postgres-backed
# docker compose --profile graph up -d      # + HugeGraph projection
```

Console + API: **http://localhost:8000** — the first boot creates an `admin` account and prints the generated password to the container log (or preset `ONTOGENY_ADMIN_PASSWORD`).

### Option 2: From Source

```bash
# backend (with the MCP extra so /mcp is served)
uv venv && source .venv/bin/activate && uv pip install -e '.[mcp]'

# web console
cd web && npm install && npm run build && cd ..

# one-command demo: seeds a source db, installs the example ontology, serves UI + API
ontogeny serve --demo --open   # → http://127.0.0.1:8000/
```

> [!NOTE]
> The API is session/bearer authenticated. The `X-Ontogeny-Principal` dev header is **enabled by default** for evaluation (`ONTOGENY_DEV_AUTH=0` disables it) — turn it off in production, where the agent surfaces (REST + `/mcp`) then require a signed-in driver and every session records WHO drove it.

## 🤖 Connecting an Agent (MCP)

Point any MCP client (Claude Desktop, ZCode, LangGraph, the `mcp` SDK) at **`http://<host>/mcp`**:

1. `agent_open_session(plugin, task)` — opens a governed session for a declared plugin;
2. call any tool with `plugin` / `session_id` / `thought` — budget, tool catalog, approval gates and the step trail apply identically to the REST session protocol;
3. writes park for human approval in the console; session-less calls are read-only.

The builtin LLM engine drives its sessions over the same MCP surface (in-process), so the transport is exercised in production. Without the `mcp` extra the endpoint is absent and the engine falls back to in-process calls — governance never changes, only the transport.

## 🏭 Production Notes

- **Single-process kernel**: registry, outbox, derivation, evolve and projection workers all live in the one server process. Do NOT scale with `uvicorn --workers N`; scale by domain (one process per database).
- **Observability**: `GET /api/v1/admin/metrics` — query/action/agent/outbox counters from the platform's own tables, zero extra dependencies.
- **Query baseline**: `python tools/bench_query.py` (p50/p95 for search/filter/traverse).

## 📦 Repository Layout

| Path | What it is |
|---|---|
| [`server/ontogeny`](./server/ontogeny) | The Python kernel (`ontogeny`): 11-kind DSL + validators (`core`), registry & compiled snapshots (`registry`), object tables & sync engine (`stores`), five-stage action runtime (`action`), Cedar-subset policy (`policy`), query engine (`engine`), sandboxed functions (`functions`), RSI loop (`telemetry` + `evolve`), graph projection (`projection`), agent session governance (`agent`), extension host (`ext_host`) |
| [`extensions`](./extensions) | Pluggable implementations: [llm-ollama](./extensions/llm-ollama) (LLM gateway), [graph-hugegraph](./extensions/graph-hugegraph) (projection store), [agent-builtin-llm](./extensions/agent-builtin-llm) (reference agent engine) |
| [`web`](./web) | React 19 + TypeScript + Vite + Tailwind v4 console, bilingual EN/zh-CN |
| [`domains`](./domains) | Domain packages (YAML + seed data + agent plugins); [product-manufacturing](./domains/product-manufacturing) is the showcase **and** the test-suite golden package: 7 objects, 6 links, 8 actions, 3 functions, policies, a projection, an eval suite and a demo story |

One `ServiceContext` behind three thin shells — HTTP, MCP and CLI — a single governance channel. The full contract lives at `GET /openapi.json`.

## 📚 Documentation

Docs live in [`docs/`](./docs/README.md) (Chinese; English translations welcome), in two parts:

**Part I · Architecture**

- [Overall architecture](./docs/architecture/01-overall-architecture.md) — the four-band view, third-party components & degradation
- [Ontology model & DSL](./docs/architecture/02-ontology-model-and-dsl.md) — the 11 resource kinds, mini-expr, validators
- [Data & derivation](./docs/architecture/03-data-and-derivation.md) — ownership, sync engine, outbox, projection backfill
- [Kinetic layer](./docs/architecture/04-actions-and-functions.md) — function ecosystem, functional actions & effect plans
- [Agent governance](./docs/architecture/05-agent-governance.md) — sessions, engines, the MCP channel, the three doors
- [RSI self-evolution](./docs/architecture/06-rsi-self-evolution.md) — signals, selection ladder, T0–T3 promotion
- [Boundaries & quality](./docs/architecture/07-boundaries-and-quality.md) — non-goals, limits, test map

**Part II · Usage**

- [Quick start](./docs/usage/08-quickstart.md) — one command, first login
- [UI tour](./docs/usage/09-ui-tour.md) — six high-frequency pages
- [Function editor](./docs/usage/10-function-editor.md) — sandboxed Python in the console
- [Manufacturing case](./docs/usage/11-manufacturing-case.md) — a full operational loop
- [Reference](./docs/usage/12-reference.md) — CLI, env vars, API endpoints, routes, error codes

## 🔗 HugeGraph Ecosystem

- [hugegraph](https://github.com/apache/hugegraph) — graph server (the projection's query engine)
- [hugegraph-toolchain](https://github.com/apache/hugegraph-toolchain) — loader / dashboard / client tools
- [hugegraph-computer](https://github.com/apache/hugegraph-computer) — graph computing

## 🤝 Contributing

See the [HugeGraph contribution guidelines](https://hugegraph.apache.org/docs/contribution-guidelines/).

```bash
pytest                              # backend (524 tests; live-LLM cases auto-skip)
cd web && npx vitest run && npm run build   # frontend + typecheck + build
ruff check . && ruff format .       # lint
```

## 📄 License

Apache 2.0 — see [LICENSE](./LICENSE).
