---
name: hugegraph-regression-tester
description: Route HugeGraph MCP regression testing tasks to the current public tool surface, including inspection, read-only queries, Gremlin generation, extraction, controlled import, schema validate/dry-run, safety guards, and admin-gated tool checks.
---

# HugeGraph Regression Tester

## Tool Routes

| Test goal | Tool |
| --- | --- |
| MCP, graph status, or schema | `inspect_graph_tool(include_raw_schema=false)` and when needed `inspect_graph_tool(include_raw_schema=true)` |
| Structured read | `query_graph_data_tool` (bounded page or exact ID query) |
| Natural-language Gremlin generation | `generate_gremlin_tool(query, execute=false)` |
| Generate Gremlin without execution | `generate_gremlin_tool(query, execute=false)`; raw execution must return `FEATURE_DISABLED` |
| Write Gremlin rejection | `execute_gremlin_read_tool(unsafe_write_query)` |
| Text-to-graph extraction | `extract_graph_data_tool(text, graph_schema?, example_prompt?)` |
| Import dry-run | `import_graph_data_tool(mode="ingest", graph_data, dry_run=true)` |
| Import preview boundary | Assert `confirmable=false`, `preview_only=true`, no `plan_id`; confirmation returns `FEATURE_DISABLED` |
| Verify existing graph data | `query_graph_data_tool` |
| Schema design | `design_schema_tool(operations?)` |
| Schema validation | `apply_schema_tool(mode="validate", operations)` |
| Schema dry-run | `apply_schema_tool(mode="dry_run", operations)` |
| Admin write-tool gate check | `execute_gremlin_write_tool(gremlin_query)` |
| VID refresh gate check | `refresh_vid_embeddings_tool(confirm=false)` |

## Order

```text
inspect -> generate/read -> extract -> import dry-run -> assert preview-only boundary
-> verify read -> schema validate/dry-run -> safety/gate checks
```

Structured query and plan lifecycle tools require the default `v2_core` toolset. For a `v1` deployment, enable `HUGEGRAPH_MCP_TOOLSET=v2_core` and restart before using them.
