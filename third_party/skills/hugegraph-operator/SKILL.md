---
name: hugegraph-operator
description: Route HugeGraph MCP operational checks to status, schema, permission, AI availability, and read-only verification tools. Use when the user asks to check the current graph, schema, MCP connection, readonly state, HugeGraph-AI state, counts, indexes, or readiness.
---

# HugeGraph Operator

## Tool Routes

| Goal | Tool |
| --- | --- |
| Quick check connection, status, permissions | `inspect_graph_tool(include_raw_schema=false)` |
| Fetch vertex/edge counts | `inspect_graph_tool(include_counts=true)` |
| Inspect full schema, primary keys, indexes, edge endpoints | `inspect_graph_tool(include_raw_schema=true)` |
| Check readonly, graph, or graphspace | `inspect_graph_tool(include_raw_schema=false)` |
| Verify whether graph data exists | `query_graph_data_tool` (bounded page or exact ID query) |
| Get schema context before query | `inspect_graph_tool(include_raw_schema=true)` |
| Check schema before import | `inspect_graph_tool(include_raw_schema=true)` |
| Check schema before schema design | `inspect_graph_tool(include_raw_schema=true)` |
| Check AI generation readiness | `inspect_graph_tool(include_raw_schema=false)`, then optionally `generate_gremlin_tool(query, execute=false)` |

`inspect_graph_tool` reports `hugegraph_ai_status`, but does not expose the
`HUGEGRAPH_MCP_ALLOW_AI` or `HUGEGRAPH_MCP_ADMIN_MODE` configuration values.
Check those environment variables in the server process when diagnosing a
disabled AI call or an admin-gated tool.

## Order

```text
Status check: inspect_graph_tool
Schema audit: inspect_graph_tool(include_raw_schema=true)
Data verification: inspect_graph_tool(include_counts=true) -> query_graph_data_tool
```

When AI is disabled by configuration, `hugegraph_ai_status="disabled"` is normal; no AI service check is needed. `unavailable` means an enabled AI service check failed.

Structured query and plan lifecycle tools require the default `v2_core` toolset. For a `v1` deployment, enable `HUGEGRAPH_MCP_TOOLSET=v2_core` and restart before using them.
