---
name: hugegraph-data-importer
description: Route HugeGraph MCP graph data extraction and controlled import/delete tasks to stable public tools. Use when the user asks to extract graph data from text, import structured vertices or edges, verify an import, or asks whether table, SQL, update, or delete graph writes are available.
---

# HugeGraph Data Importer

## Tool Routes

| Goal | Tool |
| --- | --- |
| Inspect schema, primary keys, or edge endpoints | `inspect_graph_tool(include_raw_schema=true)` |
| Extract candidate graph data from text | `extract_graph_data_tool(text, graph_schema?, example_prompt?)` |
| Preview structured vertex/edge import | `import_graph_data_tool(mode="ingest", graph_data, dry_run=true)` |
| Execute confirmed import | Unavailable: preview-only, no `plan_id`; confirmation returns `FEATURE_DISABLED` |
| Preview controlled vertex/edge delete | `delete_graph_data_tool(change_plan, dry_run=true)` |
| Execute confirmed controlled delete | `confirm_write_tool(plan_id)` for a confirmable exact edge delete only |
| Verify imported data | `query_graph_data_tool` (bounded page or exact ID query) |

`change_plan` must contain exact operations. For example, a vertex delete preview (not executable) is:

```json
{"operations":[{"op":"delete_vertex","label":"person","match":{"name":"Alice"}}]}
```

Edge deletion uses `op: "delete_edge"`, `label`, `source_label`,
`source_match`, `target_label`, and `target_match`. Each operation must resolve
to exactly one target during dry-run; bulk and cascade deletes are not supported.

## Order

```text
inspect_graph_tool -> extract_graph_data_tool or prepare graph_data
-> import_graph_data_tool(dry_run=true)
-> review preview (stop: no executable import plan)
```

For controlled deletes:

```text
inspect_graph_tool(include_raw_schema=true)
-> delete_graph_data_tool(dry_run=true)
-> confirm_write_tool(plan_id), only for confirmable exact edge deletes
-> get_write_status_tool(plan_id) -> query_graph_data_tool
```

Structured query and plan lifecycle tools require the default `v2_core` toolset. For a `v1` deployment, enable `HUGEGRAPH_MCP_TOOLSET=v2_core` and restart before using them.
