---
name: hugegraph-schema-designer
description: Route HugeGraph MCP schema design, validation, and dry-run preview tasks to stable public tools. Use when the user asks to design vertex labels, edge labels, properties, primary keys, indexes, or preview schema operations.
---

# HugeGraph Schema Designer

## Tool Routes

| Goal | Tool |
| --- | --- |
| Inspect current schema | `inspect_graph_tool(include_raw_schema=true)` |
| Design schema operations | `design_schema_tool(operations?)` |
| Validate schema operations | `apply_schema_tool(mode="validate", operations)` |
| Dry-run schema operations | `apply_schema_tool(mode="dry_run", operations)` |
| Execute real schema apply | `apply_schema_tool(mode="apply", operations, confirm=true, plan_hash, nonce, expires_at)` in default `v2_core` for create-only P0a operations |
| Delete or roll back schema | No V1 stable tool |

The default `v2_core` toolset permits confirmed apply only for
`create_property_key`, `create_vertex_label`, and `create_edge_label`. In
`HUGEGRAPH_MCP_TOOLSET=v1`, real schema apply remains disabled.

Review the dry-run response before applying it. The confirmed call must resend
the same `operations` and use the `plan_hash`, `nonce`, and `expires_at` issued
by that dry-run.

Schema create operations use a closed field contract. Property keys accept
`data_type`, `cardinality`, `aggregate_type`, and `user_data`; vertex labels
accept `id_strategy`, `properties`, `primary_keys`, `nullable_keys`,
`index_labels`, `enable_label_index`, and `user_data`; edge labels accept
`source_label`, `target_label`, `properties`, `nullable_keys`, `sort_keys`,
`frequency`, `enable_label_index`, and `user_data`. Unsupported fields,
including `ttl*`, are rejected during validation instead of being silently
dropped. Supported fields are forwarded and checked by a live-schema post-read.

## Order

```text
inspect_graph_tool -> design_schema_tool
-> apply_schema_tool(mode="validate")
-> apply_schema_tool(mode="dry_run")
-> review operations and preview
-> apply_schema_tool(mode="apply", confirm=true, plan_hash, nonce, expires_at)
```
