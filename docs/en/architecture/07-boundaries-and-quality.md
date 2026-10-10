# 07 · Boundaries & Quality（NON-GOALS · LIMITS · TEST MAP）

> Part of [Part I · Architecture](../README.md#part-i--architecture)

**[中文](../../zh/architecture/07-boundaries-and-quality.md)** | English

## Explicitly out of scope

batch/stream compute grids · DAG orchestration (Airflow won) · CDC capture (only consumes Debezium) · graph kernels & algorithm libraries (HugeGraph's job) · a fourth semantic standard (OWL / RDF's job) · unbounded RSI · AI permission backdoors

## Known limits

OWL/RDF import not implemented (export at M4) · changelog depends on a Kafka source · approval runtime (declared in the DSL) · graph-algorithm jobs · multi-tenancy and drop-column/type-change migrations · TS sandbox (deno sidecar planned) · streaming calls in design

## The test map (456 backend · 241 frontend · 8 E2E)

| Layer | Cases | Coverage highlights |
|---|---|---|
| `test_core` + `test_expr` | 41 | DSL model/loader/validation (golden ontology + 12 injected error classes) / mini-expr semantics, precedence, time semantics |
| `test_registry` + `test_restart` | 16 | publish/rebuild/soft-delete/lineage; **policy text survives restart**; function sources locatable; missing package dirs fail loudly |
| `test_stores` + `test_schema_evolution` | 18 | the three sync strategies / ownership / quarantine / watermarks; cross-package DDL without conflicts; **T0-added columns are auto-added and queryable**; timezone fidelity |
| `test_action` | 15 | five stages / rules / policy / masks / idempotency / 409 / outbox allowlist / SSE |
| `test_engine_functions` + `test_graph_explore` + `test_function_ecosystem` | 27 | assembly / derived visibility / **DFS backtracking dual regression** / sandbox capabilities & timeouts / **LLM budget** / version anchoring / cross-object triggers |
| `test_agent` + `test_agent_approval` + `test_agent_engine` + `test_agent_eval` | 35 | plugin identity / session budgets / tool catalogs / approval gates / **the builtin-llm engine loop** / Agent-eval |
| `test_evolve` + `test_demo` + `test_demo_story` + `test_llm` + `test_domain_import` + `test_product_manufacturing` + `test_projection*` | 81 | the full RSI loop (budget & constitution blocks) / demo bootstrap & story / Ollama (2 skippable live tests) / domain package import / the manufacturing contract / projections |
| `test_api` + `test_cli` + `test_deploy` | 28 | HTTP shell e2e / CLI / CMD flags & route existence / build-context consistency |
| `test_system_example` | 27 | the system example end-to-end (incl. the **example-tree hash guard**: a test polluting the example fails) |

**E2E** (vitest + globalSetup): a real Python backend subprocess + real Ollama; 8 tests cover meta / sync / query masking / the full action lifecycle / traversal / the RSI loop / both assistant paths (auto-skipped when the cluster is unreachable).
