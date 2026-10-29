# ontogeny

[![License](https://img.shields.io/badge/license-Apache%202-0E78BA.svg)](../LICENSE)

`ontogeny` — Greek *onto-* (being, the root of *ontology*) + *genesis* (birth, development): in biology the word names the **full-life-cycle development of an individual organism**. The name is the thesis: an ontology here is not a static schema but a living thing — declared in Git, compiled into tables and a graph, and grown through use. It is a **self-improving operational ontology platform**: it models an enterprise's business semantics (objects, properties, links) and business actions (actions, functions, policies) as declarative, Git-native YAML, and serves them to applications, analytics and AI agents through one governed API — optionally projected onto [Apache HugeGraph](https://github.com/apache/hugegraph) for deep-graph queries.

The design pairs a **semantic layer** (what the business is) with a **kinetic layer** (what it can do). **The DSL defines the model** — table definitions and graph projections are compiled artifacts. The metadata database also stores ontology-owned values, accounts and audit history; back it up rather than treating it as disposable.

The whole system on one board — this is the console's Overview dashboard, and the map for everything below:

![Overall architecture board](./docs/en/img/arch-board.png)

*Top: the DSL resources (Action = the only write gate, EvalSuite = the selection box). Middle: the online pipeline (build → explore → act → control → audit) and the offline RSI loop, joined by the agent spine — its reads/writes cross the same gates, its traces and approvals flow back as evolution signals. Bottom: the supporting layer and the three cross-cutting invariants (ownership, one gate, Git as source).*

## Key Features

- **Git-native ontology** — modeling is YAML + pull requests; consensus happens in code review, not a locked GUI
- **Single-process kernel** — `ontogeny serve` = Registry + query engine + Action runtime on SQLite / Postgres
- **Agent-first** — a governed MCP tool surface at `/mcp`; agents and humans share one policy surface, writes pass human approval gates
- **Self-improving (RSI)** — observe → mutate (LLM-generated DSL diffs) → select (deterministic eval suites) → release (T0 auto-merge / T1 PR / T2 canary); *mutation is outsourced to the LLM, the selection function is not*
- **Constitutional guardrails** — machine proposals travel the same Git/CI channel as humans; policy relaxation, markings and tier definitions always require human review
- **Bilingual enterprise console** — React 19 + TypeScript: ontology canvas (browse *and* edit), graph exploration, action runner, audit, self-evolution console

Modeling is code review, not form-filling — the ontology canvas shows every object, link, action and function of the domain, with references highlighted on hover:

![Ontology definition canvas](./docs/en/img/tour-ontology.png)

## Quick Start

### Option 1: Docker (Recommended)

```bash
git clone https://github.com/apache/hugegraph-ai.git
cd hugegraph-ai/ontogeny

docker compose up -d          # self-contained demo (SQLite + seeded data)
docker compose exec ontogeny cat /data/admin-bootstrap-password
```

Console + API: **http://localhost:8000** — the first boot creates an `admin` account. Unless `ONTOGENY_ADMIN_PASSWORD` was set, its random six-digit password is stored in an owner-only file on the data volume; retrieve it with `docker compose exec ontogeny cat /data/admin-bootstrap-password`. Change the password after first login and securely delete the file. Existing credential files are never overwritten. One command gets you a live dashboard seeded with a real manufacturing domain — the ontology model, the agent surface and the RSI loop at a glance:

![The Overview dashboard — ontology model section](./docs/en/img/qs-dashboard.png)

### Option 2: From Source

Run these commands from `hugegraph-ai/ontogeny`. Python 3.12+ and Node.js 22+ are required; the module installs independently of the root uv workspace.

```bash
# backend (with the MCP extra so /mcp is served)
uv venv --python 3.12 && source .venv/bin/activate && uv pip install -e '.[mcp]'

# web console
cd web && npm ci && npm run build && cd ..

# one-command demo: seeds a source db, installs the example ontology, serves UI + API
ontogeny serve --demo --open   # → http://127.0.0.1:8000/
```

> [!NOTE]
> The API is session/bearer authenticated. The `X-Ontogeny-Principal` dev header is disabled by default; set `ONTOGENY_DEV_AUTH=1` only for development or evaluation. With it disabled, the agent surfaces (REST + `/mcp`) require a signed-in driver and every session records WHO drove it.

The source demo serves the default `domains/product-manufacturing` package **in place**: model edits change that working directory. Add `--copy-package` to keep an editable copy under `--data-dir` instead; Docker uses this mode so changes persist on its `/data` volume. `--reseed` replaces copied demo state; in-place model files are retained.

For a source demo, the bootstrap credential file is `.ontogeny-demo/admin-bootstrap-password` (or under `--data-dir`). Set `ONTOGENY_DATA_DIR` to override its directory. Without demo mode, it defaults to the SQLite database directory, or `.ontogeny/` for a non-file database. Logs show only the file path.

### Background source demo

After the source installation, `./daemon.sh start --copy-package` runs the demo
in the background on `127.0.0.1:8000`. Its state and bootstrap credential file are
under `.ontogeny-daemon/`; use `./daemon.sh status` for the log path and
`./daemon.sh stop` to stop it. The stop command also stops Vite processes started
from this module’s `web/` directory. LLM and HugeGraph connections remain disabled
until their environment variables are configured. Relative daemon paths resolve
from the module directory, including when invoking the script from elsewhere.

### Optional databases and graph projection

Compose publishes the console/API on `127.0.0.1:8000` by default. Set `ONTOGENY_BIND_HOST` deliberately to expose it elsewhere. The default database is `/data/ontogeny.db`; the seeded ERP source is `/data/erp.db`.

To use Postgres for metadata and object tables, choose a URL-safe password (for example, `export POSTGRES_PASSWORD=$(openssl rand -hex 24)`) and run:

```bash
docker compose -f compose.yaml -f deploy/compose.postgres.yaml up -d
```

This starts Postgres, waits for its health check and configures the app's DSN. It creates a separate database; it does not migrate existing SQLite state. For a source install add the `postgres` extra.

Graph projection requires a separately configured HugeGraph server with authentication, using `hugegraph/hugegraph:latest` (currently 1.8) by default. Set `HUGEGRAPH_URL`, `HUGEGRAPH_USER` and `HUGEGRAPH_PASSWORD` for that server, then run:

```bash
docker compose -f compose.yaml -f deploy/compose.graph.yaml up -d
```

The override configures the graph extension; it does not provision a HugeGraph server. Graph algorithms are not implemented (`POST /api/v1/graph/algorithm` returns 501). These two overrides can be combined by supplying both `-f` arguments.

## Connecting an Agent (MCP)

Point any MCP client (Claude Desktop, ZCode, LangGraph, the `mcp` SDK) at **`http://localhost:8000/mcp`** with a signed-in account’s Bearer token:

1. `agent_open_session(plugin, task)` — opens a governed session for a declared plugin;
2. call any tool with `plugin` / `session_id` / `thought` — budget, tool catalog, approval gates and the step trail apply identically to the REST session protocol;
3. writes park for human approval in the console; session-less calls are read-only.

The builtin LLM engine drives its sessions over the same MCP surface (in-process), so the transport is exercised in production. Without the `mcp` extra the endpoint is absent and the engine falls back to in-process calls — governance never changes, only the transport.

In the console, the same surface lives behind the floating icon at the bottom-right of every page — click it and hand a task to a declared plugin (agent run, ontology Q&A or RSI proposal) from anywhere:

![The agent console popup](./docs/en/img/agent-console.png)

Governance you can point at: every execution and every refusal lands in an immutable audit stream (executed / rule-rejected / policy-denied), and every agent step is attributable and replayable:

![The audit stream](./docs/en/img/tour-audit.png)

## Production Notes

- **Single-process kernel**: registry, outbox, derivation, evolve and projection workers all live in the one server process. Do NOT scale with `uvicorn --workers N`; scale by domain (one process per database).
- **Background delivery**: `ontogeny serve` polls committed outbox events about once per second, then drains pending derivations. Source sync runs when explicitly requested (or once on a fresh demo); `sync.schedule` requires an external scheduler.
- **Observability**: `GET /api/v1/admin/metrics` — query/action/agent/outbox counters from the platform's own tables, zero extra dependencies.
- **Query baseline**: `python tools/bench_query.py` (p50/p95 for search/filter/traverse).

## Repository Layout

| Path | What it is |
|---|---|
| [`server/ontogeny`](./server/ontogeny) | The Python kernel (`ontogeny`): 11-kind DSL + validators (`core`), registry & compiled snapshots (`registry`), object tables & sync engine (`stores`), five-stage action runtime (`action`), Cedar-subset policy (`policy`), query engine (`engine`), sandboxed functions (`functions`), RSI loop (`telemetry` + `evolve`), graph projection (`projection`), agent session governance (`agent`), extension host (`ext_host`) |
| [`extensions`](./extensions) | Pluggable implementations: [llm-ollama](./extensions/llm-ollama) (LLM gateway), [graph-hugegraph](./extensions/graph-hugegraph) (projection store), [agent-builtin-llm](./extensions/agent-builtin-llm) (reference agent engine) |
| [`web`](./web) | React 19 + TypeScript + Vite + Tailwind v4 console, bilingual EN/zh-CN |
| [`domains`](./domains) | Domain packages (YAML + seed data + agent plugins); [product-manufacturing](./domains/product-manufacturing) is the showcase **and** the test-suite golden package: objects, links, actions, functions, policies, a projection, eval suites and a demo story |

One `ServiceContext` behind three thin shells — HTTP, MCP and CLI — a single governance channel. The full contract lives at `GET /openapi.json`.

## HugeGraph Ecosystem

- [hugegraph](https://github.com/apache/hugegraph) — graph server (the projection's query engine)
- [hugegraph-toolchain](https://github.com/apache/hugegraph-toolchain) — loader / dashboard / client tools
- [hugegraph-computer](https://github.com/apache/hugegraph-computer) — graph computing

## Contributing

See the [HugeGraph contribution guidelines](https://hugegraph.apache.org/docs/contribution-guidelines/).

```bash
uv pip install pytest pytest-asyncio ruff
pytest                              # backend; live-LLM cases auto-skip
cd web && npm ci && npm run lint && npx vitest run && npm run build && cd ..
ruff check . && ruff format --check .
```

## License

Apache 2.0 — see [LICENSE](../LICENSE).
