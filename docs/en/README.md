# Ontogeny Architecture & Usage Docs

> Ontogeny · Self-improving operational ontology · an ontology that grows

**[中文版](../README.md)** | English

Ontogeny models an enterprise's **nouns** (objects · properties · links) and **verbs** (actions · functions · permissions) as declarative YAML in Git, compiled into strongly-typed object tables and one unified API shared by apps, analytics and AI agents. The write path runs a five-stage pipeline — rules → Cedar policy → transaction → immutable audit — with side effects riding a transactional outbox; and a **RSI self-evolution loop** recursively improves the model itself inside the governance track (LLM proposes mutations · deterministic evals select · T0–T3 tiered promotion).

The docs come in two parts: **Part I · Architecture** explains the real construction of the system from the current code — the four-band overview, the 11 DSL resources, data & derivation, the function ecosystem, agent governance and the self-evolution loop. **Part II · Usage** walks you through startup, modeling, the function editor and governance inspection with screenshots from a real running demo instance (the reference manual covers core API endpoints, CLI and environment variables; the full contract is `/openapi.json`).

| Metric | Value |
|---|---|
| DSL resources | 11 kinds |
| API operations | 79 |
| Frontend routes | 15 pages + 9 compatibility redirects |
| Action effects | 7 kinds |
| Outbox consumers | 4 |
| Policy | Cedar subset |
| Graph engine | Apache HugeGraph |
| Source of truth | Declarative YAML in Git |
| LLM | Ollama (swappable) |
| Tests | 456 backend · 241 frontend · 8 E2E |

## Part I · Architecture

Six chapters explain how the system is really built: from the four-band overview to the ontology DSL, the data path, the kinetic layer, agent governance and the RSI loop — closed out by "Boundaries & quality": what we deliberately do not do, and how the tests map to the promises.

| # | Doc | Content |
|---|---|---|
| 01 | [Overall architecture](architecture/01-overall-architecture.md) | The four-band overview: first-class citizens · offline loop · online pipeline · supporting layer · cross-cutting mechanisms; third-party components and degradation |
| 02 | [Ontology model & DSL](architecture/02-ontology-model-and-dsl.md) | The 11 resources, two kinds of derivation, the mini-expr language, validators and lint |
| 03 | [Data & derivation](architecture/03-data-and-derivation.md) | Property-level ownership, three sync strategies + four iron laws, the outbox's four consumers, the derivation worker, graph projection |
| 04 | [Kinetic layer: actions & functions](architecture/04-actions-and-functions.md) | The four function-ecosystem capabilities, functional actions and effect plans |
| 05 | [Agent governance](architecture/05-agent-governance.md) | Plugins / sessions / approvals / budgets, the three doors, the engine paradigm and third-party integration |
| 06 | [RSI self-evolution](architecture/06-rsi-self-evolution.md) | The six-beat loop, 8 signal detectors, T0–T3 promotion, a field modeled end-to-end |
| 07 | [Boundaries & quality](architecture/07-boundaries-and-quality.md) | Non-goals, known limits, the test map |

## Part II · Usage

These chapters are hands-on: start with one command, tour the console page by page, write and verify your first sandboxed function. All screenshots come from a real running demo instance (`ontogeny serve --demo`, the product-manufacturing sample domain) — what you see is what you get.

| # | Doc | Content |
|---|---|---|
| 08 | [Quick start](usage/08-quickstart.md) | One command, first login |
| 09 | [UI tour](usage/09-ui-tour.md) | Six high-frequency pages |
| 10 | [Function editor](usage/10-function-editor.md) | Sandboxed Python in the console |
| 11 | [Manufacturing case](usage/11-manufacturing-case.md) | A full operational loop in 16 steps |
| 12 | [Reference](usage/12-reference.md) | CLI · env vars · API endpoints · routes · error codes |

---

Source-file index: DSL `server/ontogeny/core/{models,loader,validator,linter,expr,types}.py` · registry `server/ontogeny/registry/{compiled,store}.py` · data `server/ontogeny/stores/{ddl,repo,sync,sources}.py` · kinetics `server/ontogeny/action/{runtime,outbox,models}.py` · policy `server/ontogeny/policy/engine.py` · read path `server/ontogeny/engine/service.py` · functions `server/ontogeny/functions/{sandbox,child,derivation}.py` · agents `server/ontogeny/agent/{broker,catalog,models}.py` · `mcp_server.py` · evolution `server/ontogeny/evolve/{diagnoser,proposer,evalrunner,promoter}.py` · telemetry `server/ontogeny/telemetry/service.py` · projection `server/ontogeny/projection/{compiler,hugegraph}.py` · LLM `server/ontogeny/llm/ollama.py` · service composition `server/ontogeny/service.py` · `api/app.py` · `cli.py`.
