# Contributing to HugeGraph-AI

Thank you for your interest in contributing! Before submitting a pull request, please run the end-to-end integration tests locally to make sure nothing is broken.

## Prerequisites

1. **HugeGraph Server** running on `localhost:8080` (see [README.md](./README.md) for setup)
2. **Python 3.10+** with dependencies installed via `uv sync --extra llm`
3. **Proxy users**: If you have `http_proxy`/`https_proxy` set, make sure to exclude localhost:
   ```bash
   export no_proxy=localhost,127.0.0.1
   export NO_PROXY=localhost,127.0.0.1
   ```

## Running Integration Tests

```bash
# Activate the virtual environment
source .venv/bin/activate

# Run the end-to-end integration tests
cd hugegraph-llm
python -m pytest src/tests/integration/test_flows_integration.py -v
```

All 6 tests must pass before you submit your code:

| Test | What it verifies |
|------|-----------------|
| `test_build_knowledge_graph` | Vector index building, graph extraction, data import, and VID embedding update |
| `test_schema_generator` | Schema generation from text |
| `test_graph_extract_prompt` | Graph extraction prompt generation |
| `test_rag` | All RAG modes (raw, vector-only, graph-only, graph+vector) |
| `test_build_example_index` | Example vector index building for Text2Gremlin |
| `test_text_2_gremlin` | Natural language to Gremlin query translation |

## Submission Checklist

- [ ] Integration tests pass locally (`6 passed`)
- [ ] Code is formatted with `ruff format .`
- [ ] Linting passes with `ruff check .`
