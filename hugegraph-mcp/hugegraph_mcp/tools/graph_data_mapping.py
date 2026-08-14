# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""graph_data → change_plan 映射层 — 将用户输入的 {vertices, edges} 转为内部变更计划。

graph_data_to_change_plan() 是核心转换函数：
- 每个 vertex → create_vertex 操作
- 每个 edge → create_edge 操作（含端点匹配）
- 数字 id 和字符串 id 归一化处理

该模块不依赖 manage_graph_data.py，避免循环导入。
"""

from typing import Any

from hugegraph_mcp.tools.schema_utils import primary_key_names, schema_payload

GraphChangePlan = dict[str, list[dict[str, Any]]]


def _change_plan_from_operations(operations: list[dict[str, Any]]) -> GraphChangePlan:
    return {"operations": operations}


def graph_data_to_change_plan(
    graph_data: dict[str, Any],
    live_schema: dict[str, Any] | None = None,
) -> GraphChangePlan:
    """将图数据 {vertices, edges} 转为 change_plan {operations: [...]}。

    vertices 全部映射为 create_vertex，edges 全部映射为 create_edge。
    边端点优先保留 extract_graph_data 输出的 id 契约，避免退化成非唯一属性匹配。
    """
    operations: list[dict[str, Any]] = []
    vertex_ids = _vertex_ids_by_label(graph_data)
    single_primary_keys = _single_primary_keys_by_label(live_schema)
    primary_key_values = _vertex_primary_key_values(
        graph_data,
        single_primary_keys=single_primary_keys,
    )
    for vertex in graph_data.get("vertices") or []:
        if not isinstance(vertex, dict):
            continue
        operation = {
            "op": "create_vertex",
            "label": vertex.get("label"),
            "properties": vertex.get("properties") or {},
        }
        if vertex.get("id") not in (None, ""):
            operation["id"] = vertex.get("id")
        operations.append(operation)
    for edge in graph_data.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source_label = edge.get("source_label") or edge.get("outVLabel")
        target_label = edge.get("target_label") or edge.get("inVLabel")
        operations.append(
            {
                "op": "create_edge",
                "label": edge.get("label"),
                "source_label": source_label,
                "target_label": target_label,
                "source_match": _edge_endpoint_match(
                    edge=edge,
                    endpoint="source",
                    endpoint_label=source_label,
                    vertex_ids=vertex_ids,
                    single_primary_keys=single_primary_keys,
                    primary_key_values=primary_key_values,
                ),
                "target_match": _edge_endpoint_match(
                    edge=edge,
                    endpoint="target",
                    endpoint_label=target_label,
                    vertex_ids=vertex_ids,
                    single_primary_keys=single_primary_keys,
                    primary_key_values=primary_key_values,
                ),
                "properties": edge.get("properties") or {},
            }
        )
    return _change_plan_from_operations(operations)


def _vertex_ids_by_label(graph_data: dict[str, Any]) -> dict[tuple[str, str], Any]:
    ids: dict[tuple[str, str], Any] = {}
    for vertex in graph_data.get("vertices") or []:
        if not isinstance(vertex, dict):
            continue
        label = vertex.get("label")
        vertex_id = vertex.get("id")
        if isinstance(label, str) and vertex_id not in (None, ""):
            ids[(label, str(vertex_id))] = vertex_id
    return ids


def _single_primary_keys_by_label(
    live_schema: dict[str, Any] | None,
) -> dict[str, str]:
    raw_schema = schema_payload(live_schema)
    if raw_schema is None:
        return {}

    result: dict[str, str] = {}
    for vertex_label in raw_schema.get("vertexlabels") or []:
        if not isinstance(vertex_label, dict):
            continue
        label = vertex_label.get("name")
        primary_keys = primary_key_names(vertex_label)
        if isinstance(label, str) and len(primary_keys) == 1:
            result[label] = primary_keys[0]
    return result


def _vertex_primary_key_values(
    graph_data: dict[str, Any],
    *,
    single_primary_keys: dict[str, str],
) -> dict[tuple[str, str], Any]:
    values: dict[tuple[str, str], Any] = {}
    for vertex in graph_data.get("vertices") or []:
        if not isinstance(vertex, dict):
            continue
        label = vertex.get("label")
        if not isinstance(label, str):
            continue
        primary_key = single_primary_keys.get(label)
        properties = vertex.get("properties")
        if primary_key is None or not isinstance(properties, dict):
            continue
        value = properties.get(primary_key)
        if value not in (None, ""):
            values[(label, str(value))] = value
    return values


def _edge_endpoint_match(
    *,
    edge: dict[str, Any],
    endpoint: str,
    endpoint_label: str | None,
    vertex_ids: dict[tuple[str, str], Any],
    single_primary_keys: dict[str, str],
    primary_key_values: dict[tuple[str, str], Any],
) -> dict[str, Any]:
    """确定边端点的匹配条件。

    source/target 对象保持原样；scalar 在单主键 schema 下优先匹配主键，
    允许指向已存在顶点；显式 payload id 与 outV/inV 始终保持 id 语义。
    """
    explicit_endpoint = endpoint in edge
    if endpoint == "source":
        explicit = edge.get("source")
        vertex_id = edge.get("outV")
    else:
        explicit = edge.get("target")
        vertex_id = edge.get("inV")

    if isinstance(explicit, dict):
        return explicit
    fallback_id = explicit if explicit not in (None, "") else vertex_id
    if isinstance(endpoint_label, str) and fallback_id not in (None, ""):
        identity_key = (endpoint_label, str(fallback_id))
        matched_vertex_id = vertex_ids.get(identity_key)
        if matched_vertex_id is not None:
            return {"id": matched_vertex_id}

        if explicit_endpoint:
            primary_key = single_primary_keys.get(endpoint_label)
            primary_key_value = primary_key_values.get(identity_key)
            if (
                primary_key_value is None
                and isinstance(fallback_id, str)
                and ":" in fallback_id
            ):
                primary_key_value = primary_key_values.get(
                    (endpoint_label, fallback_id.split(":", 1)[1])
                )
            if primary_key is not None:
                return {
                    primary_key: primary_key_value
                    if primary_key_value is not None
                    else fallback_id
                }
    return {"id": fallback_id}
