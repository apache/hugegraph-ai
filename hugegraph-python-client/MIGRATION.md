# Python API migration

New code should use snake_case. Existing public CamelCase method and property names remain
as direct aliases, so a spelling change alone does not break existing callers. These aliases
share the canonical implementations and add no request routing or naming-conversion layer.
New APIs only introduce snake_case names.

Naming compatibility does not undo parameter or return-value changes listed below; those
changes apply to both spellings. Server JSON keys and graph IDs retain their original types and spelling.

| Legacy alias | Preferred name |
| --- | --- |
| `addEdge` | `add_edge` |
| `addEdges` | `add_edges` |
| `addVertex` | `add_vertex` |
| `addVertices` | `add_vertices` |
| `appendEdge` | `append_edge` |
| `appendVertex` | `append_vertex` |
| `asBlob` | `as_blob` |
| `asBool` | `as_bool` |
| `asByte` | `as_byte` |
| `asDate` | `as_date` |
| `asDouble` | `as_double` |
| `asFloat` | `as_float` |
| `asInt` | `as_int` |
| `asLong` | `as_long` |
| `asObject` | `as_object` |
| `asText` | `as_text` |
| `baseType` | `base_type` |
| `baseValue` | `base_value` |
| `calcMax` | `calc_max` |
| `calcMin` | `calc_min` |
| `calcOld` | `calc_old` |
| `calcSum` | `calc_sum` |
| `dataType` | `data_type` |
| `edgeLabel` | `edge_label` |
| `eliminateEdge` | `eliminate_edge` |
| `eliminateVertex` | `eliminate_vertex` |
| `enableLabelIndex` | `enable_label_index` |
| `getEdgeById` | `get_edge_by_id` |
| `getEdgeByPage` | `get_edge_by_page` |
| `getEdgeLabel` | `get_edge_label` |
| `getEdgeLabels` | `get_edge_labels` |
| `getEdgesById` | `get_edges_by_id` |
| `getIndexLabel` | `get_index_label` |
| `getIndexLabels` | `get_index_labels` |
| `getPropertyKey` | `get_property_key` |
| `getPropertyKeys` | `get_property_keys` |
| `getRelations` | `get_relations` |
| `getSchema` | `get_schema` |
| `getVertexByCondition` | `get_vertex_by_condition` |
| `getVertexByConditionWithPage` | `get_vertex_by_condition_with_page` |
| `getVertexById` | `get_vertex_by_id` |
| `getVertexByPage` | `get_vertex_by_page` |
| `getVertexLabel` | `get_vertex_label` |
| `getVertexLabels` | `get_vertex_labels` |
| `getVerticesById` | `get_vertices_by_id` |
| `idStrategy` | `id_strategy` |
| `ifNotExist` | `if_not_exist` |
| `inV` | `in_v` |
| `inVLabel` | `in_v_label` |
| `indexLabel` | `index_label` |
| `indexLabels` | `index_labels` |
| `indexType` | `index_type` |
| `multiTimes` | `multi_times` |
| `nullableKeys` | `nullable_keys` |
| `onE` | `on_e` |
| `onV` | `on_v` |
| `outV` | `out_v` |
| `outVLabel` | `out_v_label` |
| `primaryKeys` | `primary_keys` |
| `propertyKey` | `property_key` |
| `removeEdgeById` | `remove_edge_by_id` |
| `removeVertexById` | `remove_vertex_by_id` |
| `singleTime` | `single_time` |
| `sortKeys` | `sort_keys` |
| `sourceLabel` | `source_label` |
| `targetLabel` | `target_label` |
| `useAutomaticId` | `use_automatic_id` |
| `useCustomizeNumberId` | `use_customize_number_id` |
| `useCustomizeStringId` | `use_customize_string_id` |
| `usePrimaryKeyId` | `use_primary_key_id` |
| `valueList` | `value_list` |
| `valueSet` | `value_set` |
| `valueSingle` | `value_single` |
| `vertexLabel` | `vertex_label` |

`weighted_shortest_path(source_id, target_id, weight, *, ...)` and
`single_source_shortest_path(source_id, *, weight=None, ...)` do not accept `max_depth`:
these server endpoints use capacity/degree/limit controls instead. Neighbourhood and unweighted
shortest-path APIs still accept the depth controls offered by their server endpoints.

The legacy `client.graphs().get_all_graphs()`, `get_version()` and `get_graph_info()` helpers
keep returning JSON strings, so existing `json.loads(...)` calls keep working. For parsed dictionaries,
use `client.graphs().list()`, `client.version().version()` and `client.graphs().get(graph_name)`, respectively.
The corresponding `client.rest()` resources also return native dictionaries.
Close `PyHugeClient` (or use its context manager), rather than closing an individual manager.
Version-probe failures raise instead of silently selecting legacy routes. Choose an explicit graphspace
only when the deployment supports graphspace routes. Graphspace-only resources reject legacy profiles.

Use `client.olap()` for full-graph jobs, `client.traverser()` for immediate OLTP algorithms,
and `client.rest()` when complete server request/response payloads are required.

Schema export uses `get_schema()` (also available as `getSchema()`) and always returns the server JSON schema.
The legacy `getSchema(_format=...)` call still accepts its historical argument; schema output remains JSON.
It does not convert schema to Groovy. The canonical `get_schema()` has no format argument.
`NeighborRankParameters` no longer accepts the unsupported top-level `label`; edge labels belong to its steps.
Only `source` may be positional. Pass `alpha`, `capacity` and `steps` by keyword so legacy
`NeighborRankParameters(source, label)` calls fail explicitly instead of binding `label` to `alpha`.
`NeighborRankStep` keeps `top` as its fourth positional argument; pass the new `skip_degree` by keyword.
Older servers may ignore `with_result=false` and return the result during task polling.

LLM and ML releases now require `hugegraph-python>=1.8.0,<2`. LLM backups write native JSON to `schema.json`.
When a same-day backup directory is reused, a stale `schema.groovy` is removed; historical files in other backup directories are untouched.

HTTP timeouts must be positive, finite values. Unlimited components such as `timeout=(5, None)`
raise `ValueError`; choose a finite read timeout instead.

Graph helpers omit cursor pagination when a nonzero `offset` is supplied without `page`.
Combining an explicit `page` (including `""`) with nonzero `offset` raises `ValueError`.

For JSON REST operations, omitting `body` sends no entity; explicitly passing `body=None` sends JSON `null`.
Required request fields remain subject to server validation.
