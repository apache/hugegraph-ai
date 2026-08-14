---
name: hugegraph-regression-tester
description: Route HugeGraph MCP V1 regression testing tasks to the current public tool surface, including inspection, read-only queries, Gremlin generation, extraction, controlled import, schema validate/dry-run, safety guards, and admin-gated tool checks.
---

# HugeGraph Regression Tester

## Tool Routes

| Test goal | Tool |
| --- | --- |
| MCP, graph status, or schema | `inspect_graph_tool(include_raw_schema=false)` and when needed `inspect_graph_tool(include_raw_schema=true)` |
| Read-only Gremlin query | `execute_gremlin_read_tool(gremlin_query)` |
| Natural-language Gremlin generation | `generate_gremlin_tool(query, execute=false)` |
| Generate then execute read query | `generate_gremlin_tool(query, execute=false)` -> `execute_gremlin_read_tool(gremlin_query)` |
| Write Gremlin rejection | `execute_gremlin_read_tool(unsafe_write_query)` |
| Text-to-graph extraction | `extract_graph_data_tool(text, graph_schema?, example_prompt?)` |
| Import dry-run | `import_graph_data_tool(mode="ingest", graph_data, dry_run=true)` |
| Import confirm | `import_graph_data_tool(mode="ingest", graph_data, dry_run=false, confirm=true, plan_hash, nonce, expires_at)` |
| Verify import | `execute_gremlin_read_tool(gremlin_query)` |
| Schema design | `design_schema_tool(operations?)` |
| Schema validation | `apply_schema_tool(mode="validate", operations)` |
| Schema dry-run | `apply_schema_tool(mode="dry_run", operations)` |
| Admin write-tool gate check | `execute_gremlin_write_tool(gremlin_query)` |
| VID refresh gate check | `refresh_vid_embeddings_tool(confirm=false)` |

## Order

```text
inspect -> generate/read -> extract -> import dry-run -> import confirm
-> verify read -> schema validate/dry-run -> safety/gate checks
```
