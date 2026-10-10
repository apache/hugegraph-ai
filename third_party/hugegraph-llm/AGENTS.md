# hugegraph-llm AGENTS.md

Module-specific guidance for AI agents. Root `../AGENTS.md` still applies; this file only adds rules that matter inside `hugegraph-llm`.

## Module Focus

- This module owns GraphRAG, knowledge graph construction, and Text2Gremlin behavior.
- Prefer changes in the owning layer first. If a fix crosses API, flow, node, operator, model, prompt, or index boundaries, preserve the existing contract or update tests for the new contract explicitly.
- `hugegraph-python-client` is the HugeGraph access boundary. Prefer adapting LLM-side code unless the client contract is actually wrong.

## Testing Expectations

- Any code change must add or update tests that exercise the changed behavior, regression risk, or failure path.
- For pipeline changes, cover the relevant flow, node, or operator contract instead of only testing a helper in isolation.
- For API or request/response changes, cover the public model or endpoint behavior.
- For prompt or Text2Gremlin changes, preserve and test the expected output contract, especially Gremlin-only fenced output when callers depend on it.
- External-service tests may be skipped only through explicit, traceable skip controls. Do not hide failures by silently swallowing HugeGraph, LLM provider, or vector DB connection errors.

## Code Search Anchors

- `src/hugegraph_llm/api/` and `src/hugegraph_llm/api/models/` - FastAPI endpoints and request/response models.
- `src/hugegraph_llm/flows/`, `src/hugegraph_llm/nodes/`, and `src/hugegraph_llm/operators/` - pipeline orchestration and executable units.
- `src/hugegraph_llm/config/` and `src/hugegraph_llm/resources/` - runtime config and prompt resources.
- `src/hugegraph_llm/indices/` - vector index implementations and backends.
- `src/tests/` - unit, integration, and contract tests for this module.

## Build & Test

From the repository root:

```bash
uv sync --extra llm --extra dev
```

From `hugegraph-llm/`, these commands mirror the CI split:

```bash
SKIP_EXTERNAL_SERVICES=true uv run pytest src/tests/config/ src/tests/document/ src/tests/middleware/ src/tests/operators/ src/tests/models/ src/tests/indices/ src/tests/test_utils.py -v --tb=short
SKIP_EXTERNAL_SERVICES=true uv run pytest src/tests/integration/test_graph_rag_pipeline.py src/tests/integration/test_kg_construction.py src/tests/integration/test_rag_pipeline.py -v --tb=short
```

- Use narrower `pytest` targets while iterating, but finish with coverage that matches the touched behavior.
- For Python code changes, run root `uv run ruff format --check .` and `uv run ruff check .` before handoff.

## LLM-specific Rules

- Preserve Text2Gremlin prompt/output contracts unless the task explicitly changes them.
- Keep GraphRAG retrieval, KG construction, and Text2Gremlin paths behaviorally separate; shared helpers should not blur pipeline semantics.
- Do not introduce a new LLM, embedding, reranker, or vector DB dependency without wiring it through existing config patterns.
- Treat HugeGraph Server, LLM providers, and vector databases as external services with explicit configuration and explicit test skip behavior.

## Style

- Python is `>=3.10,<3.12` for this module.
- Use `uv` for dependency management; do not document or rely on ad hoc `pip install` workflows.
- Ruff and mypy behavior comes from `pyproject.toml`; do not duplicate their rule sets here.
