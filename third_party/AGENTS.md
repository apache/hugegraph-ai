# AGENTS.md

Guidance for AI agents working in this repository. Keep README content in README files; keep this file focused on decisions agents commonly get wrong.

## Stack & Modules

- This is a Python `uv` workspace. Prefer root-level workspace commands unless a module-specific file says otherwise.
- `hugegraph-llm/` is the primary and most frequently changed module. When editing or reviewing it, read `hugegraph-llm/AGENTS.md` first.
- `hugegraph-python-client/` is a supporting dependency for HugeGraph access. Change it only when the client contract itself must change, and verify `hugegraph-llm` callers when you do.
- Treat `hugegraph-ml/` and `vermeer-python-client/` as lower-frequency modules. Do not expand changes into them without a direct reason.

## Testing Expectations

- Any code change must include sufficient and effective test coverage for the changed behavior, regression risk, or failure path.
- Do not add tests that only improve coverage numbers while mocking away the behavior being changed.
- If a change cannot reasonably include automated tests, state why and provide the manual verification performed.
- Cross-module or shared dependency changes must test the affected downstream module, not only the package where the edit was made.

## Code Search Anchors

- `hugegraph-llm/src/hugegraph_llm/` - main LLM, RAG, KG, prompt, API, and vector-index code.
- `hugegraph-python-client/src/pyhugegraph/` - Python client used by LLM code to talk to HugeGraph.
- `pyproject.toml` and module `pyproject.toml` files - workspace membership, dependency groups, lint settings, Python versions.
- `rules/README.md` - staged AI-assisted workflow for multi-file features, API contract changes, or cross-module design changes.

## Build & Test

```bash
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
```

- Run tests for the affected module rather than defaulting to a full-repository test sweep.
- For `hugegraph-llm`, use the module CI split between unit-style tests and integration tests.
- For `hugegraph-python-client`, include client tests and any `hugegraph-llm` tests needed to validate caller compatibility.

## Agent Workflow

- Before editing, identify whether the change belongs to `hugegraph-llm`, `hugegraph-python-client`, or root workspace configuration.
- For multi-file features, API contract changes, or cross-module design changes, read `rules/README.md` first.
- Keep changes scoped to the module that owns the behavior. Avoid opportunistic rewrites in sibling modules.

## Cross-module Notes

- Root dependency or workspace changes can affect multiple packages; verify the package that consumes the changed dependency.
- `hugegraph-llm` imports `hugegraph-python-client`; client API changes must preserve or deliberately update those call sites.
- Do not duplicate README quick-start, Docker, or deployment instructions in AGENTS files.
