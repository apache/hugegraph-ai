# HugeGraph AI documentation

This directory indexes cross-module architecture, quality and release documentation. Package installation and API usage belong in the nearest module README; long-form user tutorials belong on the [HugeGraph website](https://hugegraph.apache.org/docs/).

## Find the right document

| Task | Document |
|---|---|
| Choose a module and run the main application | [Root README](../README.md) |
| Understand CI selection and validation tiers | [quality/ci.md](quality/ci.md) |
| Understand test categories | [quality/test-taxonomy.md](quality/test-taxonomy.md) |
| Run integration tests with HugeGraph | [quality/hugegraph-integration.md](quality/hugegraph-integration.md) |
| Maintain the coverage ratchet | [quality/coverage-ratchet.md](quality/coverage-ratchet.md) |
| Understand SDK ownership and extension boundaries | [sdk/architecture.md](sdk/architecture.md) |
| Prepare a release | [releasing.md](releasing.md) |
| Work on GraphRAG, extraction or the application API | [`hugegraph-llm/`](../hugegraph-llm/) |
| Integrate the standalone SDK | [`hugegraph-llm-sdk/`](../hugegraph-llm-sdk/) |
| Configure MCP clients and toolsets | [`hugegraph-mcp/`](../hugegraph-mcp/) |
| Use the Python client | [`hugegraph-python-client/`](../hugegraph-python-client/) |
| Follow the staged workflow for complex AI-assisted changes | [`rules/README.md`](../rules/README.md) |

## Source-of-truth hierarchy

1. Source code, `pyproject.toml`, container configuration and CI workflows define current executable behavior.
2. A module README owns installation, public APIs, optional dependencies and module-specific compatibility.
3. This directory owns cross-module architecture, quality policy and release procedures.
4. The website owns released user tutorials and product-facing deployment guidance.
5. `AGENTS.md` and `rules/` guide development work; they should link to product documentation rather than restating it.

When a shared package changes, document the stable ownership boundary here and keep detailed API examples beside that package. For example, `hugegraph-llm-sdk` owns reusable schema/extraction contracts while `hugegraph-llm` owns application orchestration and presentation.

## Writing durable documentation

- Explain the current API or operational contract, prerequisites, failure boundary and verification result. Do not maintain implementation diaries or review summaries.
- Do not use pull-request links, commit hashes, temporary branches, issue chronology or fixed repository snapshots as permanent documentation.
- Link every cross-module page from this index and every package-specific page from the package README or local index. Avoid orphan Markdown files.
- Use explicit package names, import paths, configuration keys, commands and expected results. This improves both developer search and LLM retrieval.
- Keep prose paragraphs as logical lines. Do not hard-wrap every sentence; wrap near 160 characters only when a source line becomes difficult to review. Preserve lists, tables, code and output formatting.
- Keep one canonical example for each workflow. Link to it instead of copying similar setup blocks across README, quality and agent files.
- Read Python ranges, optional extras and tool versions from `pyproject.toml`. Repeat a version in prose only when it is itself a compatibility contract.

## Documentation change checklist

1. Identify the module or cross-module document that owns the topic.
2. Update the smallest authoritative page and its index link.
3. Remove stale or competing copies.
4. Check relative links, commands, package names, imports and rendered headings.
5. Update the website when released user installation, configuration or behavior changes.
