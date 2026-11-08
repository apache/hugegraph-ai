# HugeGraph Python Client

`hugegraph-python` is the Python SDK for Apache HugeGraph; its import name is `pyhugegraph`.
Use `client.traverser()` for immediate OLTP neighbourhood/path queries and `client.olap()` for asynchronous full-graph computation.

## Install and connect

Requires Python 3.12+ and HugeGraph Server 1.5+. New endpoints require a server that implements them.
The APIs below describe the current source tree; released-package availability follows the corresponding release.

```bash
uv pip install hugegraph-python
# From the HugeGraph-AI workspace, to use current source:
uv sync --extra python-client
source .venv/bin/activate
```

```python
from pyhugegraph.client import PyHugeClient

with PyHugeClient("http://127.0.0.1:8080", "hugegraph", "admin", "admin") as client:
    print(client.graphs().list())
    print(client.olap().run("count_vertex", timeout=60))
```

The client probes `/versions` once when no graphspace is supplied. Server 1.7+ selects `DEFAULT`;
1.5/1.6 use legacy graph/auth routes. An explicit `graphspace` selects the graphspace profile without probing.
A failed probe raises an error instead of guessing a profile. URLs may include a reverse-proxy prefix.
The default HTTP `(connect, read)` timeout is `(0.5, 15.0)` seconds; set `timeout=(2, 30)` when needed, or pass a positive scalar for both values.
One client owns one session, shared by all managers. Close the client or use a `with` block.

Subsequent snippets assume `client` is open, for example inside the `with` block above.

## Choose an API

| Need | Entry | Result |
| --- | --- | --- |
| Schema definitions | `client.schema()` | Fluent builders and schema objects |
| Read/write graph data | `client.graph()` | Vertex/edge objects or REST envelopes |
| Immediate neighbourhood/path queries (OLTP) | `client.traverser()` | JSON result |
| Personal/neighbor rank (OLTP) | `client.rank()` | JSON result |
| Whole-graph computation (OLAP) | `client.olap()` | Task receipt, or decoded result with `run()` |
| Task status, waiting, cancellation | `client.task()` | Native task information |
| Index/label rebuild jobs | `client.rebuild()` | Task receipt |
| Graph lifecycle / graphspaces / templates | `client.graphs()`, `client.graphspaces()`, `client.schema_templates()` | JSON or text |
| Queries | `client.gremlin()`, `client.cypher()` | Query response |
| Auth / variables / metrics | `client.auth()`, `client.variable()`, `client.metrics()` | JSON or text |
| Full REST and deployment-specific extensions | `client.rest()` | Native REST response |

## OLTP: schema, data and traversal

```python
schema = client.schema()
schema.property_key("name").as_text().if_not_exist().create()
schema.vertex_label("person").properties("name").primary_keys("name").if_not_exist().create()
schema.edge_label("knows").link("person", "person").if_not_exist().create()

graph = client.graph()
alice = graph.add_vertex("person", {"name": "Alice"})
bob = graph.add_vertex("person", {"name": "Bob"})
graph.add_edge("knows", alice.id, bob.id, {})
print(client.traverser().k_out(alice.id, 2, direction="OUT", limit=100))
```

`VertexData.to_dict()` and `EdgeData.to_dict()` return native server payloads, preserving wire field names and additional server fields.
Vertex IDs preserve their type: `123` is a numeric ID, `"123"` is a string ID. UUIDs are supported.
List methods such as `graph.list_vertices(page="", limit=100)` return the REST envelope;
`get_vertex_by_page(...)` returns `(vertices, next_page)`. Pass the returned token to continue.
Batch creation accepts complete entity dictionaries, including IDs; batch updates accept server update strategies.
Use `client.rest()` for full Schema payloads, including fields not represented by the fluent builders.

## OLAP: submit, wait and read a result

```python
receipt = client.olap().count_vertex()
task = client.task().wait(receipt["task_id"], timeout=300, poll_interval=1)
print(client.task().result(task))

# The same submit/wait/result workflow in one call:
result = client.olap().run("count_vertex", timeout=300)

# On a graph prepared for PageRank write-back:
result = client.olap().run("page_rank", {"times": 10, "top": 10}, timeout=300)
```

Named methods submit asynchronously and return `{"task_id": ...}`. `submit(name, parameters)` also accepts
server-added/custom algorithm names. Parameters are forwarded to the server; full-graph results retain the server's shape.
PageRank writes computed properties back to the graph. Before importing vertices for that workflow,
declare nullable DOUBLE property `r_rank` on their vertex labels. The live tests prepare this schema explicitly.

Supported named algorithms:

- `count_edge`
- `count_vertex`
- `subgraph_stat`
- `betweenness_centrality`
- `closeness_centrality`
- `degree_centrality`
- `eigenvector_centrality`
- `stress_centrality`
- `cluster_coefficient`
- `k_core`
- `louvain`
- `lpa`
- `triangle_count`
- `weak_connected_component`
- `rings`
- `page_rank`
- `fusiform_similarity`

Older servers may ignore `with_result=false` and still return a task result during polling.

`wait()` polls with `with_result=false` and loads the result on completion. It returns the full task record;
`result(task)` decodes its serialized JSON result once and preserves plain text. `run()` returns that decoded value.
Failed/cancelled jobs raise `TaskFailedError`/`TaskCancelledError`, with `.task` and `.task_id` for inspection.
`TaskTimeoutError` means waiting ended; it does not cancel the server job. HTTP and waiting timeouts are distinct.
Waiting requests use the remaining deadline without automatic HTTP retries or redirects; configure the final service URL.
Cancel explicitly with `cancel_task(id)`; delete task records with `delete_task(id, force=False)`.
`list_tasks(ids=[...])` cannot combine IDs with status or page filters.

## Complete REST surface

```python
rest = client.rest()
print(rest.vertex.list(label="person", offset=0, limit=20))
print(rest.kout.post(body={"source": alice.id, "steps": {"direction": "OUT"}, "max_depth": 2}))
# Requires a deployment with graphspace management enabled:
# print(client.graphspaces().list())
print(client.cypher().post(body={"cypher": "MATCH (n) RETURN n LIMIT 5"}))
```

See [all REST operations and query parameters](https://github.com/apache/hugegraph-ai/blob/main/hugegraph-python-client/API_COVERAGE.md).
`client.rest()` exposes explicit resource methods, accepts complete request bodies, and shares authentication and transport.
For JSON endpoints, an omitted `body` sends no entity; `body=None` explicitly sends JSON `null`.
Operations preserve JSON/text responses; HTTP 204 returns an empty dictionary. Server errors are surfaced through
the existing exception types. A configured Bearer token (`client.use_token(token)`) takes precedence over Basic auth;
`client.use_token(None)` restores Basic. Login/verify/logout are explicit and never silently change credentials.

Raft, Arthas, IP whitelist, Computer submission and exception tracing are available through their separate REST resources.
They require the relevant server configuration and privileges; a REST wrapper does not provision those services.
The older standalone Services manager targets custom deployments and is not exposed as a standard master capability.
Property CAS remains a protocol boundary, not a claimed server REST feature.
Graph configuration export returns source text and can be unavailable on graphs without a local configuration file.

## Migration and server synchronization

Use `snake_case` in new code. Existing public CamelCase method/property names remain direct aliases;
new APIs only introduce snake_case names. Parameter and return-value changes still require migration.
Managers no longer own `close()`.
The existing `get_all_graphs()`, `get_version()` and `get_graph_info()` graph helpers retain JSON-string returns;
use the corresponding REST resources for parsed dictionaries.
Close the owning client. See [the migration table](https://github.com/apache/hugegraph-ai/blob/main/hugegraph-python-client/MIGRATION.md), including the corrected shortest-path signatures.

The checked-in contract pins server commit `8e327b8f3d3ffcf61547be7fea1a15d3af2de8b4`.
Static REST resources and coverage tables are generated from that contract:

```bash
python scripts/client_api.py --check
python scripts/client_api.py --write
# Export /openapi.json from the target server, then inspect differences:
python scripts/client_api.py --openapi server-openapi.json
```

Review changes to the contract, then regenerate and format. Algorithm names come from the server algorithm registry;
OpenAPI alone does not enumerate them. Jersey-generated WADL metadata is explicitly excluded from SDK operations.

## Development checks

```bash
uv run --extra python-client --extra dev pytest hugegraph-python-client/src/tests -m "unit or contract"
HUGEGRAPH_REQUIRED=true uv run --extra python-client --extra dev pytest hugegraph-python-client/src/tests -m "integration and hugegraph"
uv run --extra dev ruff check hugegraph-python-client
uv run --extra dev ty check hugegraph-python-client/src/pyhugegraph
```

Use the upstream `hugegraph/hugegraph:latest` image for primary integration tests and 1.7 for compatibility regression.
Record each tested image's actual version and digest. Deployment-specific extensions need their own integration environment.
