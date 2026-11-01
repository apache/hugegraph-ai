# Python API migration

The new API uses snake_case consistently. No CamelCase aliases are installed.
Server JSON keys and graph IDs keep their original spelling and types.
Update application code together with this client upgrade.

| Previous name | Current name |
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

`client.graphs().get_all_graphs()` returns the native `{"graphs": [...]}` envelope.
Close `PyHugeClient` (or use its context manager), rather than closing an individual manager.
Version-probe failures raise instead of silently selecting legacy routes. Choose an explicit graphspace
only when the deployment supports graphspace routes. Graphspace-only resources reject legacy profiles.

Use `client.olap()` for full-graph jobs, `client.traverser()` for immediate OLTP algorithms,
and `client.rest()` when complete server request/response payloads are required.

Schema export now uses `get_schema()` and always returns the server JSON schema.
`NeighborRankParameters` no longer requires an unsupported `label` field; edge labels belong to its steps, which also expose `skip_degree`.
Older servers may ignore `with_result=false` and return the result during task polling.

LLM and ML releases now require `hugegraph-python>=1.8.0,<2`. LLM backups write native JSON to `schema.json`; pre-existing Groovy backups remain historical files.
