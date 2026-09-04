# P0a Integration Checklist

Use this checklist to validate the current write-safety contract against a disposable HugeGraph 1.7.0 Docker instance. Never use a production graph.

## 1. Start an Isolated Server

Run from `/Users/uleng/Code` (replace the checkout path if needed):

```bash
docker pull hugegraph/hugegraph:1.7.0
docker run --rm -d --name hg-p0a-check -p 127.0.0.1:18080:8080 hugegraph/hugegraph:1.7.0
until curl -fsS http://127.0.0.1:18080/versions >/dev/null; do sleep 1; done

export HUGEGRAPH_URL=http://127.0.0.1:18080
export HUGEGRAPH_GRAPH_PATH=DEFAULT/hugegraph
export HUGEGRAPH_USER=admin
export HUGEGRAPH_PASSWORD=admin
export HUGEGRAPH_MCP_TOOLSET=v2_core
export HUGEGRAPH_MCP_READONLY=false
export HUGEGRAPH_MCP_ALLOW_AI=false
export HUGEGRAPH_MCP_ADMIN_MODE=false
export HUGEGRAPH_MCP_PLAN_STORE=sqlite
export HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT=1
export HUGEGRAPH_MCP_STATE_DIR=/tmp/hg-p0a-plan-store
export HUGEGRAPH_CONNECT_TIMEOUT_SECONDS=0.5
export HUGEGRAPH_READ_TIMEOUT_SECONDS=15
export HUGEGRAPH_WRITE_TIMEOUT_SECONDS=15

export PYTHONPATH=/Users/uleng/Code/hugegraph-ai-pr73-mcp/hugegraph-mcp:/Users/uleng/Code/hugegraph-ai-pr73-mcp/hugegraph-python-client/src
/Users/uleng/Code/hugegraph-ai-pr73-mcp/.venv/bin/python -m hugegraph_mcp.server
```

The launch command deliberately uses the checkout's root virtual environment and
binds both source trees through `PYTHONPATH`. Do not replace it with
`uv run --project .../hugegraph-mcp`: resolving that standalone subproject can
request the unavailable package-index release `hugegraph-python-client==0.1.1`
instead of loading the sibling client checkout.

Use a second MCP client process for the calls below. Replace `<RUN_ID>` with one unique suffix and preserve exact IDs returned by the server. Each JSON block is the `tools/call` name and arguments payload.

Clean up after validation:

```bash
docker stop hg-p0a-check
rm -rf -- /tmp/hg-p0a-plan-store
```

## 2. Inspect the Contract

```json
{
  "name": "inspect_graph_tool",
  "arguments": {"include_raw_schema": false, "include_counts": false}
}
```

Require `ok=true`, `data.readonly=false`, `data.toolset="v2_core"`, and `data.mcp_tool_contract_version="2.0"`. Confirm that the MCP client lists all 16 v2 tools, including `confirm_write_tool`, `get_write_status_tool`, and `reconcile_write_tool`.

## 3. Create Schema One Object Per Plan

A confirmable schema plan contains exactly one create operation. Repeat the dry-run and confirmation sequence below in dependency order:

1. `create_property_key` for `p0a_name_<RUN_ID>`.
2. `create_property_key` for `p0a_note_<RUN_ID>`.
3. `create_vertex_label` for `p0a_person_<RUN_ID>`.
4. `create_edge_label` for `p0a_knows_<RUN_ID>`.

Example dry-run for the first object:

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
      }
    ]
  }
}
```

Require `ok=true`, `data.valid=true`, `data.confirmable=true`, `data.status="ISSUED"`, and a non-empty `data.plan_id`. Confirm only the returned ID:

```json
{
  "name": "confirm_write_tool",
  "arguments": {"plan_id": "<PLAN_ID>"}
}
```

Require `ok=true` and `data.status="APPLIED"`. Query its durable result:

```json
{
  "name": "get_write_status_tool",
  "arguments": {"plan_id": "<PLAN_ID>"}
}
```

Require `data.status="APPLIED"`. Repeating `confirm_write_tool` with the same ID must return the recorded terminal result without creating the object twice.

Use the same sequence for the remaining schema objects. Their operation bodies are:

```json
{"type":"create_property_key","name":"p0a_note_<RUN_ID>","data_type":"TEXT","cardinality":"SINGLE"}
```

```json
{"type":"create_vertex_label","name":"p0a_person_<RUN_ID>","properties":["p0a_name_<RUN_ID>","p0a_note_<RUN_ID>"],"primary_keys":["p0a_name_<RUN_ID>"],"nullable_keys":["p0a_note_<RUN_ID>"]}
```

```json
{"type":"create_edge_label","name":"p0a_knows_<RUN_ID>","source_label":"p0a_person_<RUN_ID>","target_label":"p0a_person_<RUN_ID>"}
```

Verify the final vertex label:

```json
{
  "name": "inspect_schema_tool",
  "arguments": {
    "filter_kind": "vertex_label",
    "filter_name": "p0a_person_<RUN_ID>",
    "include_relations": true,
    "include_index_labels": true
  }
}
```

Also submit a dry-run containing two schema operations:

```json
{
  "name": "apply_schema_tool",
  "arguments": {
    "mode": "dry_run",
    "operations": [
      {"type":"create_property_key","name":"p0a_extra_a_<RUN_ID>","data_type":"TEXT","cardinality":"SINGLE"},
      {"type":"create_property_key","name":"p0a_extra_b_<RUN_ID>","data_type":"TEXT","cardinality":"SINGLE"}
    ]
  }
}
```

Require `data.valid=false` and an error explaining that a confirmable schema plan must contain exactly one create operation.

## 4. Verify Import Is Preview-Only

Dry-run:

```json
{
  "name": "import_graph_data_tool",
  "arguments": {
    "mode": "ingest",
    "graph_data": {
      "vertices": [
        {"label":"p0a_person_<RUN_ID>","properties":{"p0a_name_<RUN_ID>":"Alice"}},
        {"label":"p0a_person_<RUN_ID>","properties":{"p0a_name_<RUN_ID>":"Bob"}}
      ],
      "edges": [
        {
          "label":"p0a_knows_<RUN_ID>",
          "source_label":"p0a_person_<RUN_ID>",
          "source":{"p0a_name_<RUN_ID>":"Alice"},
          "target_label":"p0a_person_<RUN_ID>",
          "target":{"p0a_name_<RUN_ID>":"Bob"}
        }
      ]
    }
  }
}
```

Require `ok=true`, `data.confirmable=false`, `data.preview_only=true`, and no
`data.plan_id`. The warnings must explain that atomic vertex and edge
create-if-absent capabilities are not verified for this backend. Preserve the
returned `plan_hash`, `plan_context.nonce`, and numeric
`plan_context.expires_at`, then repeat the same ingest request with
`dry_run=false`, `confirm=true`, and that complete legacy locator. Require
`ok=false`, `error.type="FEATURE_DISABLED"`, and verify that neither vertex nor
edge was created. Do not call `confirm_write_tool` for an import preview because
there is no canonical plan to confirm.

The remaining checks need disposable fixtures but must not weaken the public MCP
import boundary. Seed them directly through the sibling Python client after the
preview-only assertion:

```bash
export RUN_ID=<RUN_ID>
PYTHONPATH=/Users/uleng/Code/hugegraph-ai-pr73-mcp/hugegraph-python-client/src \
  /Users/uleng/Code/hugegraph-ai-pr73-mcp/.venv/bin/python - <<'PY'
import os

from pyhugegraph.client import PyHugeClient

suffix = os.environ["RUN_ID"]
name_key = f"p0a_name_{suffix}"
person_label = f"p0a_person_{suffix}"
knows_label = f"p0a_knows_{suffix}"
client = PyHugeClient(
    url="http://127.0.0.1:18080",
    graph="hugegraph",
    graphspace="DEFAULT",
    user="admin",
    pwd="admin",
)
graph = client.graph()
alice = graph.addVertex(person_label, {name_key: "Alice"})
bob = graph.addVertex(person_label, {name_key: "Bob"})
edge = graph.addEdge(knows_label, alice.id, bob.id, {})
print({"alice_id": alice.id, "bob_id": bob.id, "edge_id": edge.id})
PY
```

Locate Alice and preserve the returned backend ID:

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

Require two vertices and copy Alice's exact `items[].id` value. Do not construct a backend ID from the label or primary key.

## 5. Verify Preview-Only Operations

### Property mutation

```json
{
  "name": "mutate_graph_properties_tool",
  "arguments": {
    "target": "vertex",
    "operation": "append",
    "id": "<ALICE_VERTEX_ID>",
    "properties": {"p0a_note_<RUN_ID>": "preview-only"},
    "dry_run": true
  }
}
```

Require `ok=true`, `data.confirmable=false`, and a warning that atomic conditional property update is unavailable. Copy the complete legacy locator from the preview only to verify the compatibility gate:

```json
{
  "name": "mutate_graph_properties_tool",
  "arguments": {
    "target": "vertex",
    "operation": "append",
    "id": "<ALICE_VERTEX_ID>",
    "properties": {"p0a_note_<RUN_ID>": "preview-only"},
    "dry_run": false,
    "confirm": true,
    "plan_hash": "<PLAN_HASH_FROM_PREVIEW>",
    "nonce": "<NONCE_FROM_PREVIEW>",
    "expires_at": <NUMERIC_EXPIRES_AT_FROM_PREVIEW>
  }
}
```

Pass `expires_at` as a JSON number, without quotes. Require `FEATURE_DISABLED` and verify Alice remains unchanged.

### Isolated vertex deletion

```json
{
  "name": "delete_graph_data_tool",
  "arguments": {
    "change_plan": {
      "operations": [
        {
          "op": "delete_vertex",
          "label": "p0a_person_<RUN_ID>",
          "match": {"p0a_name_<RUN_ID>": "Alice"},
          "cascade": false
        }
      ]
    },
    "dry_run": true
  }
}
```

Require `ok=true`, `data.confirmable=false`, `data.preview_only=true`, and no `plan_id`. Confirmation must return `FEATURE_DISABLED`. This is required even when the preview reports zero incident edges: Docker concurrency testing demonstrated that HugeGraph 1.7.0 cannot atomically exclude a concurrently added edge.

## 6. Delete an Exact Edge

Dry-run an edge delete whose label and endpoint primary keys resolve exactly one edge. The persisted plan binds the resulting edge ID:

```json
{
  "name": "delete_graph_data_tool",
  "arguments": {
    "change_plan": {
      "operations": [
        {
          "op":"delete_edge",
          "label":"p0a_knows_<RUN_ID>",
          "source_label":"p0a_person_<RUN_ID>",
          "source_match":{"p0a_name_<RUN_ID>":"Alice"},
          "target_label":"p0a_person_<RUN_ID>",
          "target_match":{"p0a_name_<RUN_ID>":"Bob"}
        }
      ]
    },
    "dry_run": true
  }
}
```

Require a `plan_id`, confirm it through `confirm_write_tool`, and require `APPLIED`. A bounded edge page for `p0a_knows_<RUN_ID>` must then return no edge.

## 7. Verify Failure-State Semantics

For every submitted plan:

- `APPLIED` means all operations are proven applied.
- `PARTIAL` means at least one operation applied and the workflow did not completely apply. It must never be reported as `REJECTED`.
- `UNKNOWN` means the commit outcome cannot be proven. Do not repeat the original write or create an equivalent replacement plan.

The public tools intentionally provide no fault-injection switch. Run the automated durable-executor fault suite from `/Users/uleng/Code`:

```bash
/Users/uleng/Code/hugegraph-ai-pr73-mcp/.venv/bin/pytest \
  /Users/uleng/Code/hugegraph-ai-pr73-mcp/hugegraph-mcp/tests/test_write_executor_faults.py -q
```

The suite must cover failures before claim, after claim, before write, after write, and during receipt persistence. When a controlled test produces `PARTIAL` or `UNKNOWN`, call:

```json
{"name":"get_write_status_tool","arguments":{"plan_id":"<PLAN_ID>"}}
```

Then call:

```json
{"name":"reconcile_write_tool","arguments":{"plan_id":"<PLAN_ID>"}}
```

Require reconciliation to use only read checks. Resume is allowed only when durable state proves the operation was never dispatched, or when a backend-enforced idempotency/fencing primitive proves replay safety. Reading the expected state after a dispatched request is not enough because the old request may still commit; retain `UNKNOWN` in that case.

## 8. Verify Legacy and Raw-Gremlin Gates

Legacy compatibility accepts `plan_hash`, `nonce`, and `expires_at` only when all three are supplied together and returns `LEGACY_CONFIRMATION_DEPRECATED`. A partial legacy locator must return `VALIDATION_ERROR`. Canonical lifecycle tools accept only `plan_id`; never mix the two protocols.

Each call below must return `FEATURE_DISABLED`, even if admin mode is enabled:

```json
{"name":"execute_gremlin_read_tool","arguments":{"gremlin_query":"g.V().limit(1)"}}
```

```json
{"name":"execute_gremlin_write_tool","arguments":{"gremlin_query":"g.addV('unsafe')"}}
```

```json
{"name":"generate_gremlin_tool","arguments":{"query":"list one vertex","execute":true}}
```

`generate_gremlin_tool(execute=false)` and structured query tools must remain available. The item and byte configuration values are post-materialization output guards and do not satisfy the raw-query hard-budget contract.

## Pass Criteria

- Tool contract and count match `v2_core`.
- Four single-operation schema plans reach `APPLIED` and schema post-reads match.
- Vertex/edge import remains preview-only, issues no `plan_id`, returns `FEATURE_DISABLED` on confirmation, and creates no graph elements.
- Property mutation and isolated vertex deletion remain preview-only and return `FEATURE_DISABLED` on confirmation.
- Exact edge deletion reaches `APPLIED`.
- Status and reconciliation preserve `PARTIAL` and `UNKNOWN` semantics.
- Partial legacy locators and every public Raw Gremlin execution path fail closed.
- Docker container is removed after the run.
