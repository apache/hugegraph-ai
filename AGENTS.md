# AGENTS.md

Repository guidance for coding agents. Keep product usage in README files and use this file for ownership, validation and decisions agents commonly get wrong.

## Module ownership

- `hugegraph-llm-sdk/` owns reusable schema design, validation and reviewed graph-extraction contracts. Keep its base installation independent of application and provider dependencies.
- `hugegraph-llm/` owns GraphRAG, knowledge-graph construction, prompts, model integration, vector indexes, API/UI and application orchestration. Read its local guidance before editing it.
- `hugegraph-python-client/` owns the HugeGraph Python protocol and public client APIs. Change it only when the client contract itself must change, then verify application callers.
- `hugegraph-mcp/` owns MCP transport, tool contracts, safety defaults and write confirmation.
- `hugegraph-ml/` and `vermeer-python-client/` are lower-frequency standalone modules. Do not expand a change into them without a direct dependency or behavior reason.

## Load on demand

| Task | Read first |
|---|---|
| Documentation ownership and durable links | [docs/README.md](docs/README.md) |
| LLM application or GraphRAG | [`hugegraph-llm/`](hugegraph-llm/) and its local guidance |
| Standalone SDK | [`hugegraph-llm-sdk/`](hugegraph-llm-sdk/) and [SDK architecture](docs/sdk/architecture.md) |
| Python client | [`hugegraph-python-client/`](hugegraph-python-client/) |
| MCP | [`hugegraph-mcp/`](hugegraph-mcp/) |
| CI and test selection | [docs/quality/ci.md](docs/quality/ci.md) and [test taxonomy](docs/quality/test-taxonomy.md) |
| Complex multi-file or API-contract work | [rules/README.md](rules/README.md) |

## Repository constraints

- Keep a change in the package that owns the behavior. Update callers deliberately rather than moving shared behavior into the application for convenience.
- A shared SDK or Python-client change requires downstream `hugegraph-llm` validation, not only package-local tests.
- Keep root and module READMEs as entry points. Put detailed cross-module policy in `docs/` and link every durable page from `docs/README.md` or a module-local index.
- Do not duplicate quick starts, Docker procedures or public API examples in this file.
- Document current contracts and failure boundaries, not implementation chronology. Avoid PR links, commit hashes, timestamps and review logs in durable docs.
- Keep Markdown prose as logical lines; wrap near 160 characters only when necessary for review.

## Build, type and style checks

Run these commands from the repository root.

```bash
uv sync --all-extras
uv run --extra dev ruff format --check .
uv run --extra dev ruff check .
uv run --extra dev ty check \
  hugegraph-llm-sdk/src/hugegraph_llm_sdk \
  hugegraph-llm/src/hugegraph_llm \
  hugegraph-python-client/src/pyhugegraph
```

The exact Python ranges, extras and tool versions live in root and module `pyproject.toml` files. Do not copy them into agent notes unless the version is the subject of the change.

## Testing expectations

- Test changed behavior, regression risk and meaningful failure paths; do not add tests that mock away the contract being changed.
- Run affected-module tests rather than an unconditional full-repository sweep. Use the CI policy to add downstream or integration tiers when shared code or external behavior changes.
- `hugegraph-llm-sdk` changes require SDK tests and relevant LLM application tests.
- `hugegraph-python-client` changes require client tests and affected LLM/MCP callers.
- MCP safety or write-path changes require tests for read-only defaults, confirmation, target revalidation and error behavior.
- When automated testing is not practical, state the missing environment and provide the exact manual verification performed.

Documentation-only changes require relative-link, package-name, import, command-working-directory and rendered-heading review plus `git diff --check`.
