---
name: hugegraph-query-analyst
description: Route HugeGraph MCP V1 graph query tasks to stable read-only tools. Use when the user asks graph questions, asks to generate Gremlin, provides Gremlin to execute safely, or needs read-only graph exploration.
---

# HugeGraph Query Analyst

## Tool Routes

| Goal | Tool |
| --- | --- |
| Inspect schema, labels, properties, or edge directions | `inspect_graph_tool(include_raw_schema=false)` or `inspect_graph_tool(include_raw_schema=true)` |
| Generate Gremlin from natural language | `generate_gremlin_tool(query, execute=false)` |
| Answer a natural-language graph question | `generate_gremlin_tool(query, execute=false)` -> `execute_gremlin_read_tool(gremlin_query)` |
| Execute user-provided Gremlin | `execute_gremlin_read_tool(gremlin_query)` |
| Generate only, without execution | `generate_gremlin_tool(query, execute=false)` |


## Order

```text
Need schema: inspect_graph_tool
Natural-language query: generate_gremlin_tool -> execute_gremlin_read_tool
Existing Gremlin: execute_gremlin_read_tool
```
