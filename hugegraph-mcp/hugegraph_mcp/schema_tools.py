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

"""HugeGraph Schema 操作层 — schema 读取和设计指导。

get_live_schema() 从 HugeGraph 拉取全量 schema 并生成 LLM 精简版，
design_schema() 提供链式思维引导的 schema 设计框架。
"""

from typing import Any

from pyhugegraph.client import PyHugeClient

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.hugegraph_client import build_hugegraph_client


def _build_client() -> PyHugeClient:
    return build_hugegraph_client(MCPConfig.from_env(), client_cls=PyHugeClient)


def _simple_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """精简 schema 供 LLM 消费 — 去掉冗余字段，只保留 name/properties/source_label/target_label。

    与 hugegraph_llm.SchemaManager.simple_schema 行为一致。
    """

    mini_schema: dict[str, Any] = {}

    if schema.get("vertexlabels"):
        mini_schema["vertexlabels"] = []
        for vertex in schema["vertexlabels"]:
            new_vertex = {
                key: vertex[key]
                for key in ("id", "name", "properties")
                if key in vertex
            }
            mini_schema["vertexlabels"].append(new_vertex)

    if schema.get("edgelabels"):
        mini_schema["edgelabels"] = []
        for edge in schema["edgelabels"]:
            new_edge = {
                key: edge[key]
                for key in ("name", "source_label", "target_label", "properties")
                if key in edge
            }
            mini_schema["edgelabels"].append(new_edge)

    return mini_schema


def get_live_schema() -> dict[str, Any]:
    """从 HugeGraph 拉取活跃 schema，同时返回原始版和 LLM 精简版。

    返回: {schema, simple_schema, graphspace?, readonly}
    """

    client = _build_client()
    raw_schema = client.schema().getSchema()

    if raw_schema is None:
        raise ValueError("Failed to retrieve schema from HugeGraph server")

    result: dict[str, Any] = {
        "schema": raw_schema,
        "simple_schema": _simple_schema(raw_schema),
    }

    graphspace = MCPConfig.from_env().graphspace
    if graphspace:
        result["graphspace"] = graphspace

    result["readonly"] = MCPConfig.from_env().is_readonly()

    return result


def design_schema(
    thought: str,
    thought_number: int,
    total_thoughts: int = 4,
    next_thought_needed: bool = True,
    is_revision: bool = False,
    revision_of: int | None = None,
) -> dict:
    """Schema 设计引导工具 — 参考 Sequential Thinking 模式。

    HugeGraph 使用 schema-based 图模型，数据写入前必须先定义 PropertyKeys、
    VertexLabels、EdgeLabels、IndexLabels。本函数提供分步引导框架。

    Args:
        thought: reserved for future use (no-op, accepted for Sequential Thinking
            protocol compatibility)
        thought_number: current thought step number
        total_thoughts: estimated total thought steps
        next_thought_needed: whether the caller expects another step
        is_revision: reserved for future use (no-op)
        revision_of: reserved for future use (no-op)

    【最佳实践】
    1. 先定义 PropertyKeys — 所有属性必须在 VertexLabel/EdgeLabel 中预定义
    2. 选择合适的 DataType (TEXT/INT/DATE/DOUBLE) 和 Cardinality (SINGLE/SET/LIST)
    3. VertexLabel 需指定 primaryKeys 用于顶点唯一标识
    4. EdgeLabel 需指定 sourceLabel 和 targetLabel
    5. EdgeLabel 的 frequency 可选 SINGLE 或 MULTIPLE
    6. 使用 nullableKeys 允许属性为空
    7. 为常用查询字段创建 IndexLabels (secondary/range/search)
    """

    return {
        "thought_number": thought_number,
        "total_thoughts": total_thoughts,
        "next_thought_needed": next_thought_needed,
    }
