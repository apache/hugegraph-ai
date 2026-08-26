# P0a Integration Checklist

This checklist is for the next person running P0a integration validation against a real HugeGraph Server. It expands the six-step path from the P0a design into concrete MCP tool calls and expected responses.

Use a disposable graph. Do not run this checklist against a production graph.

## Prerequisites

### Start HugeGraph Server

Use the repository's existing Docker path:

```bash
cd <YOUR_PROJECT_PATH>
cp docker/env.template docker/.env
sed -i.bak "s|PROJECT_PATH=path_to_project|PROJECT_PATH=<YOUR_PROJECT_PATH>|" docker/.env
cd docker
docker compose -f docker-compose-network.yml up -d --wait hugegraph-server
curl -fsS http://127.0.0.1:8080/versions
```

`docker-compose-network.yml` pins HugeGraph Server 1.7.0 and also defines the RAG service, but P0a validation below only needs HugeGraph Server. HugeGraph MCP requires HugeGraph Server >= 1.7.0 because the default graphspace route is `DEFAULT/<graph>`. The `--wait` option prevents the checklist from continuing before the server health check passes.

### Configure MCP

Set these variables in the shell or MCP client process that launches `hugegraph-mcp`:

```bash
cd <YOUR_PROJECT_PATH>/hugegraph-mcp
export HUGEGRAPH_URL=http://127.0.0.1:8080
export HUGEGRAPH_GRAPHSPACE=DEFAULT
export YOUR_GRAPH_NAME=p0a_check_20260705
export HUGEGRAPH_GRAPH_PATH="$HUGEGRAPH_GRAPHSPACE/$YOUR_GRAPH_NAME"
export HUGEGRAPH_USER=admin
export HUGEGRAPH_PASSWORD=admin
export HUGEGRAPH_MCP_TOOLSET=v2_core
export HUGEGRAPH_MCP_READONLY=false
export HUGEGRAPH_MCP_ALLOW_AI=false
export HUGEGRAPH_MCP_ADMIN_MODE=false
```

Use a fresh `$YOUR_GRAPH_NAME`, for example `p0a_check_20260705`. First list
the graphs in the target graphspace and verify that the graph exists:

```bash
curl -fsS -u "$HUGEGRAPH_USER:$HUGEGRAPH_PASSWORD" \
  "$HUGEGRAPH_URL/graphspaces/$HUGEGRAPH_GRAPHSPACE/graphs"
```

If the graph is missing, create it through the HugeGraph REST API before
continuing. For a RocksDB graph on a server version that supports dynamic graph
creation:

```bash
curl -fsS -u "$HUGEGRAPH_USER:$HUGEGRAPH_PASSWORD" \
  -H 'Content-Type: application/json' \
  -X POST \
  -d "{\"gremlin.graph\":\"org.apache.hugegraph.auth.HugeFactoryAuthProxy\",\"backend\":\"rocksdb\",\"serializer\":\"binary\",\"store\":\"$YOUR_GRAPH_NAME\"}" \
  "$HUGEGRAPH_URL/graphspaces/$HUGEGRAPH_GRAPHSPACE/graphs/$YOUR_GRAPH_NAME"
```

HugeGraph 1.7.0 has a known dynamic-graph-creation limitation; use the
pre-created default graph or a server version containing the fix when that
endpoint is unavailable. Never run the checklist against a production graph.

Start the MCP server with the same environment:

```bash
uv run hugegraph-mcp
```

Confirmed write plans are single-use. The server persists only a SHA-256 digest
of each nonce and atomically consumes it before the first write side effect. A
second call with the same confirmation returns `PLAN_ALREADY_USED`, including
after an execution timeout, failure, or partial apply. Inspect the target state
and run a new dry-run instead of retrying an already submitted confirmation.

The request examples below show MCP `tools/call` payloads. Paste the `name` and `arguments` into your MCP client. Replace every `<RUN_ID>` with one short unique suffix, for example `20260705a`, and keep the same suffix through all steps. Replace `<EXPIRES_AT_...>` placeholders with the numeric `expires_at` value from the dry-run response, not a quoted string.

## Step 1: Inspect Tool Contract

Safety decision verified: `inspect_graph_tool` must expose the runtime contract version and confirm that this server is running the `v2_core` toolset before any write path is tested.

Call:

```json
{
  "name": "inspect_graph_tool",
  "arguments": {
    "include_raw_schema": false
  }
}
```

Expected key fields:

```json
{
  "ok": true,
  "data": {
    "graph": "<YOUR_GRAPH_NAME>",
    "graphspace": "DEFAULT",
    "hugegraph_server_status": "available",
    "readonly": false,
    "mcp_tool_contract_version": "2.0",
    "toolset": "v2_core"
  },
  "meta": {
    "readonly": false,
    "mcp_tool_contract_version": "2.0",
    "toolset": "v2_core"
  }
}
```

Continue only when `data.toolset` is `v2_core` and `data.readonly` is `false`. If `hugegraph_ai_status` is `unavailable`, ignore it for this P0a checklist.

## Step 2: Create Minimal Schema Through Dry-Run And Confirm

Safety decision verified: `apply_schema_tool(mode="apply")` is unlocked only for P0a create operations, and real schema writes must use the `dry_run -> plan_hash -> confirm` chain. The confirm step also verifies by post-reading live schema.

Schema create operations use a closed field contract. `enable_label_index`,
`index_labels`, and `user_data` are forwarded and checked when supplied;
unimplemented fields such as `ttl*` must fail validation before a plan is
issued. Keep any optional fields identical between the dry-run and confirm
requests.

Dry-run call:

```json
{
  "name": "apply_schema_tool",
  "arguments": {
    "mode": "dry_run",
    "operations": [
      {
        "type": "create_property_key",
        "name": "p0a_name_<RUN_ID>",
        "data_type": "TEXT",
        "cardinality": "SINGLE"
      },
      {
        "type": "create_property_key",
        "name": "p0a_note_<RUN_ID>",
        "data_type": "TEXT",
        "cardinality": "SINGLE"
      },
      {
        "type": "create_vertex_label",
        "name": "p0a_person_<RUN_ID>",
        "properties": ["p0a_name_<RUN_ID>", "p0a_note_<RUN_ID>"],
        "primary_keys": ["p0a_name_<RUN_ID>"],
        "nullable_keys": ["p0a_note_<RUN_ID>"]
      },
      {
        "type": "create_edge_label",
        "name": "p0a_knows_<RUN_ID>",
        "source_label": "p0a_person_<RUN_ID>",
        "target_label": "p0a_person_<RUN_ID>"
      }
    ]
  }
}
```

Expected dry-run fields:

```json
{
  "ok": true,
  "data": {
    "valid": true,
    "confirmable": true,
    "plan_hash": "<32 hex chars>",
    "plan_context": {
      "nonce": "<nonce>",
      "expires_at": 1780000000,
      "graph_name": "<YOUR_GRAPH_NAME>",
      "graphspace": "DEFAULT",
      "readonly": false
    },
    "mutation_summary": "Schema operations planned: create_edge_label=1, create_property_key=2, create_vertex_label=1"
  }
}
```

Confirm call. Copy `plan_hash`, `plan_context.nonce`, and `plan_context.expires_at` exactly from the dry-run response:

```json
{
  "name": "apply_schema_tool",
  "arguments": {
    "mode": "apply",
    "operations": [
      {
        "type": "create_property_key",
        "name": "p0a_name_<RUN_ID>",
        "data_type": "TEXT",
        "cardinality": "SINGLE"
      },
      {
        "type": "create_property_key",
        "name": "p0a_note_<RUN_ID>",
        "data_type": "TEXT",
        "cardinality": "SINGLE"
      },
      {
        "type": "create_vertex_label",
        "name": "p0a_person_<RUN_ID>",
        "properties": ["p0a_name_<RUN_ID>", "p0a_note_<RUN_ID>"],
        "primary_keys": ["p0a_name_<RUN_ID>"],
        "nullable_keys": ["p0a_note_<RUN_ID>"]
      },
      {
        "type": "create_edge_label",
        "name": "p0a_knows_<RUN_ID>",
        "source_label": "p0a_person_<RUN_ID>",
        "target_label": "p0a_person_<RUN_ID>"
      }
    ],
    "confirm": true,
    "plan_hash": "<PLAN_HASH_FROM_DRY_RUN>",
    "nonce": "<NONCE_FROM_DRY_RUN>",
    "expires_at": <EXPIRES_AT_FROM_DRY_RUN>
  }
}
```

Expected confirm fields:

```json
{
  "ok": true,
  "data": {
    "status": "applied",
    "valid": true,
    "applied_operations": [
      {"type": "create_property_key", "name": "p0a_name_<RUN_ID>"},
      {"type": "create_property_key", "name": "p0a_note_<RUN_ID>"},
      {"type": "create_vertex_label", "name": "p0a_person_<RUN_ID>"},
      {"type": "create_edge_label", "name": "p0a_knows_<RUN_ID>"}
    ],
    "schema_summary": {
      "propertykeys": [
        {"name": "p0a_name_<RUN_ID>"},
        {"name": "p0a_note_<RUN_ID>"}
      ],
      "vertexlabels": [
        {"name": "p0a_person_<RUN_ID>"}
      ],
      "edgelabels": [
        {"name": "p0a_knows_<RUN_ID>"}
      ]
    }
  }
}
```

Verify with `inspect_schema_tool`:

```json
{
  "name": "inspect_schema_tool",
  "arguments": {
    "include_raw_schema": false,
    "include_relations": true,
    "include_index_labels": true,
    "filter_kind": "vertex_label",
    "filter_name": "p0a_person_<RUN_ID>"
  }
}
```

Expected key fields:

```json
{
  "ok": true,
  "data": {
    "filtered": {
      "name": "p0a_person_<RUN_ID>",
      "properties": ["p0a_name_<RUN_ID>", "p0a_note_<RUN_ID>"],
      "primary_keys": ["p0a_name_<RUN_ID>"],
      "nullable_keys": ["p0a_note_<RUN_ID>"]
    }
  }
}
```

Do not add `create_index_label` to this step. P0a apply intentionally rejects index create and rebuild work.

## Step 3: Import Two Vertices And One Edge

Safety decision verified: `import_graph_data_tool(mode="ingest")` remains the structured graph-data write path, and it must keep the same `dry_run -> plan_hash -> confirm` safety chain before writing data.

Dry-run call:

```json
{
  "name": "import_graph_data_tool",
  "arguments": {
    "mode": "ingest",
    "graph_data": {
      "vertices": [
        {
          "label": "p0a_person_<RUN_ID>",
          "properties": {
            "p0a_name_<RUN_ID>": "Alice"
          }
        },
        {
          "label": "p0a_person_<RUN_ID>",
          "properties": {
            "p0a_name_<RUN_ID>": "Bob"
          }
        }
      ],
      "edges": [
        {
          "label": "p0a_knows_<RUN_ID>",
          "source_label": "p0a_person_<RUN_ID>",
          "source": {
            "p0a_name_<RUN_ID>": "Alice"
          },
          "target_label": "p0a_person_<RUN_ID>",
          "target": {
            "p0a_name_<RUN_ID>": "Bob"
          }
        }
      ]
    }
  }
}
```

Expected dry-run fields:

```json
{
  "ok": true,
  "data": {
    "valid": true,
    "confirmable": true,
    "plan_hash": "<32 hex chars>",
    "plan_context": {
      "nonce": "<nonce>",
      "expires_at": 1780000000,
      "readonly": false
    },
    "mutation_summary": {
      "create_vertex": 2,
      "create_edge": 1
    }
  }
}
```

Confirm call. Copy `plan_hash`, `nonce`, and `expires_at` exactly from the dry-run response:

```json
{
  "name": "import_graph_data_tool",
  "arguments": {
    "mode": "ingest",
    "graph_data": {
      "vertices": [
        {
          "label": "p0a_person_<RUN_ID>",
          "properties": {
            "p0a_name_<RUN_ID>": "Alice"
          }
        },
        {
          "label": "p0a_person_<RUN_ID>",
          "properties": {
            "p0a_name_<RUN_ID>": "Bob"
          }
        }
      ],
      "edges": [
        {
          "label": "p0a_knows_<RUN_ID>",
          "source_label": "p0a_person_<RUN_ID>",
          "source": {
            "p0a_name_<RUN_ID>": "Alice"
          },
          "target_label": "p0a_person_<RUN_ID>",
          "target": {
            "p0a_name_<RUN_ID>": "Bob"
          }
        }
      ]
    },
    "dry_run": false,
    "confirm": true,
    "plan_hash": "<PLAN_HASH_FROM_DRY_RUN>",
    "nonce": "<NONCE_FROM_DRY_RUN>",
    "expires_at": <EXPIRES_AT_FROM_DRY_RUN>
  }
}
```

Expected confirm fields:

```json
{
  "ok": true,
  "data": {
    "status": "success",
    "success": true,
    "planned": {
      "create_vertex": 2,
      "create_edge": 1
    },
    "written": {
      "create_vertex": 2,
      "create_edge": 1
    },
    "failed_items": []
  }
}
```

If this returns `INVALID_GRAPH_DATA` or `SCHEMA_MISMATCH`, verify that Step 2 used the same `<RUN_ID>` and that both vertex payloads include the primary key property `p0a_name_<RUN_ID>`.

## Step 4: Query A Vertex By ID

Safety decision verified: `query_graph_data_tool` must provide typed bounded reads without falling back to unbounded Gremlin scans. This step proves that exact ID lookup works after import.

HugeGraph backend vertex IDs may encode the label and primary key together in a format that varies by server version and configuration. Do not assume a specific format; always read the exact ID string back from a bounded query before using it. If your import response does not show the exact ID, first find Alice with a bounded page query:

```json
{
  "name": "query_graph_data_tool",
  "arguments": {
    "target": "vertex",
    "operation": "page",
    "label": "p0a_person_<RUN_ID>",
    "limit": 10
  }
}
```

Expected page fields:

```json
{
  "ok": true,
  "data": {
    "target": "vertex",
    "operation": "page",
    "items": [
      {
        "id": "<ALICE_VERTEX_ID>",
        "label": "p0a_person_<RUN_ID>",
        "properties": {
          "p0a_name_<RUN_ID>": "Alice"
        }
      }
    ],
    "count": 2,
    "limit": 10
  }
}
```

Copy Alice's `items[].id` into `<ALICE_VERTEX_ID>`, then run the exact lookup:

```json
{
  "name": "query_graph_data_tool",
  "arguments": {
    "target": "vertex",
    "operation": "get_by_id",
    "id": "<ALICE_VERTEX_ID>"
  }
}
```

Expected key fields:

```json
{
  "ok": true,
  "data": {
    "target": "vertex",
    "operation": "get_by_id",
    "items": [
      {
        "id": "<ALICE_VERTEX_ID>",
        "label": "p0a_person_<RUN_ID>",
        "properties": {
          "p0a_name_<RUN_ID>": "Alice"
        }
      }
    ],
    "count": 1
  }
}
```

If you use `operation="condition"` instead, HugeGraph may return `NO_INDEX` because P0a intentionally does not create indexes. That is expected for this checklist and is covered in the troubleshooting table.

## Step 5: Append A Property And Reject A Stale Eliminate Plan

Safety decision verified: `mutate_graph_properties_tool` treats append and eliminate as write operations with the same dry-run/confirm chain. The stale eliminate confirm must be rejected with `TARGET_CHANGED`, proving the target snapshot digest blocks concurrent changes from being confirmed with an old plan.

### 5.1 Append A Property

Dry-run append call:

```json
{
  "name": "mutate_graph_properties_tool",
  "arguments": {
    "target": "vertex",
    "operation": "append",
    "id": "<ALICE_VERTEX_ID>",
    "properties": {
      "p0a_note_<RUN_ID>": "first-note"
    }
  }
}
```

Expected dry-run fields:

```json
{
  "ok": true,
  "data": {
    "status": "planned",
    "confirmable": true,
    "risk_level": "medium",
    "before": {
      "properties": {
        "p0a_name_<RUN_ID>": "Alice"
      }
    },
    "after": {
      "properties": {
        "p0a_name_<RUN_ID>": "Alice",
        "p0a_note_<RUN_ID>": "first-note"
      }
    },
    "plan_hash": "<32 hex chars>",
    "plan_context": {
      "nonce": "<nonce>|ts:<snapshot-prefix>",
      "expires_at": 1780000000,
      "readonly": false
    }
  }
}
```

Confirm append:

```json
{
  "name": "mutate_graph_properties_tool",
  "arguments": {
    "target": "vertex",
    "operation": "append",
    "id": "<ALICE_VERTEX_ID>",
    "properties": {
      "p0a_note_<RUN_ID>": "first-note"
    },
    "dry_run": false,
    "confirm": true,
    "plan_hash": "<APPEND_PLAN_HASH>",
    "nonce": "<APPEND_NONCE>",
    "expires_at": <APPEND_EXPIRES_AT>
  }
}
```

Expected confirm fields:

```json
{
  "ok": true,
  "data": {
    "status": "applied",
    "after": {
      "properties": {
        "p0a_name_<RUN_ID>": "Alice",
        "p0a_note_<RUN_ID>": "first-note"
      }
    }
  }
}
```

### 5.2 Prepare An Eliminate Plan

Dry-run eliminate call. Do not confirm it yet:

```json
{
  "name": "mutate_graph_properties_tool",
  "arguments": {
    "target": "vertex",
    "operation": "eliminate",
    "id": "<ALICE_VERTEX_ID>",
    "properties": {
      "p0a_note_<RUN_ID>": "first-note"
    }
  }
}
```

Expected dry-run fields:

```json
{
  "ok": true,
  "data": {
    "status": "planned",
    "risk_level": "high",
    "before": {
      "properties": {
        "p0a_name_<RUN_ID>": "Alice",
        "p0a_note_<RUN_ID>": "first-note"
      }
    },
    "after": {
      "properties": {
        "p0a_name_<RUN_ID>": "Alice"
      }
    },
    "plan_hash": "<ELIMINATE_PLAN_HASH>",
    "plan_context": {
      "nonce": "<ELIMINATE_NONCE>",
      "expires_at": 1780000000
    }
  }
}
```

Save `ELIMINATE_PLAN_HASH`, `ELIMINATE_NONCE`, and `ELIMINATE_EXPIRES_AT`.

### 5.3 Change The Target Before Confirm

Use another append dry-run/confirm to modify Alice after the eliminate dry-run:

```json
{
  "name": "mutate_graph_properties_tool",
  "arguments": {
    "target": "vertex",
    "operation": "append",
    "id": "<ALICE_VERTEX_ID>",
    "properties": {
      "p0a_note_<RUN_ID>": "changed-before-eliminate-confirm"
    }
  }
}
```

Confirm that second append with the returned `plan_hash`, `nonce`, and `expires_at`:

```json
{
  "name": "mutate_graph_properties_tool",
  "arguments": {
    "target": "vertex",
    "operation": "append",
    "id": "<ALICE_VERTEX_ID>",
    "properties": {
      "p0a_note_<RUN_ID>": "changed-before-eliminate-confirm"
    },
    "dry_run": false,
    "confirm": true,
    "plan_hash": "<SECOND_APPEND_PLAN_HASH>",
    "nonce": "<SECOND_APPEND_NONCE>",
    "expires_at": <SECOND_APPEND_EXPIRES_AT>
  }
}
```

Expected second append result:

```json
{
  "ok": true,
  "data": {
    "status": "applied",
    "after": {
      "properties": {
        "p0a_note_<RUN_ID>": "changed-before-eliminate-confirm"
      }
    }
  }
}
```

### 5.4 Confirm The Old Eliminate Plan

Now confirm the old eliminate plan saved in 5.2:

```json
{
  "name": "mutate_graph_properties_tool",
  "arguments": {
    "target": "vertex",
    "operation": "eliminate",
    "id": "<ALICE_VERTEX_ID>",
    "properties": {
      "p0a_note_<RUN_ID>": "first-note"
    },
    "dry_run": false,
    "confirm": true,
    "plan_hash": "<ELIMINATE_PLAN_HASH>",
    "nonce": "<ELIMINATE_NONCE>",
    "expires_at": <ELIMINATE_EXPIRES_AT>
  }
}
```

Expected rejection:

```json
{
  "ok": false,
  "error": {
    "type": "TARGET_CHANGED",
    "message": "Target changed since dry_run; property mutation was not applied.",
    "source": "mutate_graph_properties_tool"
  },
  "next_actions": [
    "Call query_graph_data_tool to inspect the current target."
  ]
}
```

This failure is the expected pass condition for stale-plan protection. If this call succeeds, P0a concurrency protection failed.

## Step 6: Reject An Unbounded Gremlin Read

Safety decision verified: `execute_gremlin_read_tool(limit_policy="reject_unbounded")` must reject safe-but-unbounded full graph reads instead of silently appending a limit or executing an unbounded scan.

Call:

```json
{
  "name": "execute_gremlin_read_tool",
  "arguments": {
    "gremlin_query": "g.V()",
    "limit_policy": "reject_unbounded"
  }
}
```

Expected fields:

```json
{
  "ok": false,
  "error": {
    "type": "VALIDATION_ERROR",
    "message": "Gremlin read query is unbounded and limit_policy='reject_unbounded'."
  },
  "warnings": [
    "Unbounded traversal ..."
  ]
}
```

Confirm that `executed_gremlin` is absent. The query must be rejected before execution.

Run a bounded read to confirm the read path itself still works:

```json
{
  "name": "execute_gremlin_read_tool",
  "arguments": {
    "gremlin_query": "g.V().hasLabel('p0a_person_<RUN_ID>').limit(10)",
    "limit_policy": "reject_unbounded"
  }
}
```

Expected bounded-read fields:

```json
{
  "ok": true,
  "data": {
    "is_read": true,
    "limit_policy": "reject_unbounded",
    "original_gremlin": "g.V().hasLabel('p0a_person_<RUN_ID>').limit(10)",
    "executed_gremlin": "g.V().hasLabel('p0a_person_<RUN_ID>').limit(10)",
    "total": 2
  }
}
```

## Troubleshooting

| Error type | Where it appears | Meaning | Action |
|---|---|---|---|
| `CONNECTION_FAILED` | `inspect_schema_tool`, `apply_schema_tool`, `import_graph_data_tool`, `mutate_graph_properties_tool`, Gremlin reads | MCP could not reach HugeGraph Server, read schema, or read a target object. | Check `docker compose ps`, `curl http://127.0.0.1:8080/versions`, `HUGEGRAPH_URL`, `HUGEGRAPH_GRAPH_PATH`, `HUGEGRAPH_USER`, and `HUGEGRAPH_PASSWORD`. Retry after the server is healthy. |
| `READONLY_VIOLATION` | Any confirm call for schema/data/property writes | `HUGEGRAPH_MCP_READONLY=true` at confirm time. Dry-run may be preview-only in readonly mode. | Set `HUGEGRAPH_MCP_READONLY=false`, restart or reconfigure the MCP process, rerun dry-run, then confirm with the new `plan_hash`. |
| `PLAN_HASH_MISMATCH` | Confirm calls for schema/data/property writes | The submitted payload, graph target, schema hash, readonly state, principal, `nonce`, or `expires_at` no longer matches the dry-run plan. | Do not edit the payload between dry-run and confirm. Rerun dry-run and copy the new `plan_hash`, `nonce`, and `expires_at`. |
| `PLAN_EXPIRED` | Confirm calls after waiting too long | The dry-run plan expired. Default plan TTL is 10 minutes. | Rerun dry-run and confirm within the returned `expires_at` window. |
| `PLAN_ALREADY_USED` | A confirm call repeats a nonce that already entered execution | Confirmation nonces are globally single-use. A prior call may have succeeded, failed, timed out, or partially applied. | Inspect the current graph or schema state, then rerun dry-run and use its new `plan_hash`, `nonce`, and `expires_at`. Do not retry the old confirmation. |
| `TARGET_CHANGED` | Step 5 stale eliminate confirm | The vertex or edge was changed after dry-run and before confirm. | Treat this as a successful stale-plan rejection in Step 5. For real work, rerun `query_graph_data_tool`, review current state, then create a new dry-run plan. |
| `NO_INDEX` | `query_graph_data_tool(operation="condition")` or Gremlin `has()` filters | HugeGraph requires an index for that property query, and P0a does not create indexes. | Use `get_by_id` or bounded `page` for this checklist. Index create/rebuild belongs to the P0b workflow. |
| `PARTIAL_APPLY` | `apply_schema_tool(mode="apply")` | At least one schema operation may have been applied before a later operation failed. | Call `inspect_schema_tool`, remove already-applied operations, rerun dry-run for the remaining operations only. Do not blindly retry the original full batch. |
| `INVALID_GRAPH_DATA` or `SCHEMA_MISMATCH` | Import dry-run or property mutation dry-run | Payload does not match live schema: missing primary key, unknown property, wrong endpoint label, duplicate identity, or property not defined on the target label. | Compare the payload with `inspect_schema_tool`. In this checklist, ensure all names use the same `<RUN_ID>` and that `p0a_note_<RUN_ID>` was included in the vertex label properties. |
| `VALIDATION_ERROR` | Query parameter validation or Step 6 unbounded Gremlin rejection | Input violates the public tool contract, or the unbounded Gremlin query was rejected by policy. | Fix the input. For Step 6, `VALIDATION_ERROR` is expected for `g.V()` with `reject_unbounded`. |

## Acceptance Conclusion Template

Use this checklist as the final run record:

```text
P0a integration acceptance
Graph path: DEFAULT/<YOUR_GRAPH_NAME>
Run id: <RUN_ID>
HugeGraph Server URL: <HUGEGRAPH_URL>
Executed by:
Date:

[ ] Step 1 passed: inspect_graph_tool returned ok=true, toolset=v2_core, readonly=false.
[ ] Step 2 passed: apply_schema_tool dry-run returned plan_hash and confirm applied property keys, vertex label, and edge label.
[ ] Step 3 passed: import_graph_data_tool dry-run returned plan_hash and confirm wrote 2 vertices + 1 edge.
[ ] Step 4 passed: query_graph_data_tool get_by_id returned Alice by exact vertex id.
[ ] Step 5 passed: append property applied, and stale eliminate confirm returned TARGET_CHANGED.
[ ] Step 6 passed: g.V() with reject_unbounded was rejected before execution, while bounded read succeeded.

Overall result: PASS / FAIL
Notes:
```
