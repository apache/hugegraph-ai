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

"""图状态检视 — Agent 连接后的首个推荐工具。

inspect_graph() 做尽力而为的状态检查：HugeGraph Server 连接、schema 摘要、
可选点边计数、HugeGraph-AI 可用性。默认不执行全图 count。任何环节失败都不抛异常，
而是作为 warning 包含在 ok 信封中返回。
"""

import time
from typing import Any

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import envelope_ok
from hugegraph_mcp.gremlin_tools import execute_gremlin_read
from hugegraph_mcp.hugegraph_ai_client import health_check
from hugegraph_mcp.schema_tools import get_live_schema


def _extract_count(result: dict[str, Any]) -> int | None:
    if result.get("ok") is False or result.get("success") is False:
        return None

    return _extract_count_value(result.get("data"))


def _extract_count_value(data: Any) -> int | None:
    if isinstance(data, dict) and "data" in data:
        return _extract_count_value(data.get("data"))
    if isinstance(data, list):
        if not data:
            return 0
        first = data[0]
        return first if isinstance(first, int) else None
    if isinstance(data, int):
        return data
    return None


def _count_indexes(raw_schema: dict[str, Any] | None) -> int | None:
    if raw_schema is None:
        return None
    index_labels = raw_schema.get("indexlabels")
    if isinstance(index_labels, list):
        return len(index_labels)
    return 0


def _has_graph_index_info(graph_index_info: Any) -> bool:
    if graph_index_info is None:
        return False
    if isinstance(graph_index_info, dict):
        if graph_index_info.get("health_endpoint") == "/openapi.json":
            return False
        explicit_values = (
            graph_index_info.get("vid_embedding"),
            graph_index_info.get("vid_embedding_status"),
            graph_index_info.get("vid_index"),
            graph_index_info.get("vid_index_status"),
            graph_index_info.get("embedding_index"),
            graph_index_info.get("embedding_index_status"),
            graph_index_info.get("index_status"),
        )
        return any(_is_ready_index_value(value) for value in explicit_values)
    return False


def _is_ready_index_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        if value.get("available") is True or value.get("ready") is True:
            return True
        status = value.get("status") or value.get("state")
        return _is_ready_index_value(status)
    if isinstance(value, str):
        return value.strip().lower() in {"available", "ready", "loaded", "enabled"}
    return False


def _warning_from_exception(prefix: str, exc: Exception) -> str:
    message = str(exc).strip()
    return f"{prefix}: {message}" if message else prefix


def _check_ai_status(cfg: MCPConfig) -> tuple[str, Any, list[str]]:
    """探测 HugeGraph-AI 是否可用 — 复用统一客户端的认证、超时和回退逻辑。"""

    result = health_check(cfg=cfg)
    warnings = list(result.get("warnings") or [])
    if result.get("ok"):
        return "available", result.get("data"), warnings

    error = result.get("error") or {}
    message = error.get("message", "HugeGraph-AI is unavailable")
    return "unavailable", None, [message, *warnings]


def inspect_graph(
    include_raw_schema: bool = False,
    include_counts: bool = False,
) -> dict[str, Any]:
    """检视 HugeGraph 服务器状态、schema 摘要和 AI 状态。

    这是 Agent 连接后的推荐第一个工具。默认不执行 g.V().count()/g.E().count()。
    include_counts=true 时才计数；失败时 vertex_count/edge_count 仍为 null 并附 warning。
    全部失败信息作为 warnings 包含在 ok 信封中，不会因为某个组件不可用而阻断整体返回。
    """

    start = time.time()
    cfg = MCPConfig.from_env()
    warnings: list[str] = []

    server_status = "available"
    schema_summary: dict[str, Any] | None = None
    raw_schema: dict[str, Any] | None = None
    simple_schema: dict[str, Any] | None = None
    readonly: bool | None = None
    vertex_count: int | None = None
    edge_count: int | None = None

    try:
        schema_result = get_live_schema()
        simple_schema = schema_result.get("simple_schema")
        schema_summary = simple_schema
        raw_schema = schema_result.get("schema")
        readonly = schema_result.get("readonly")
    except Exception as exc:  # noqa: BLE001 - inspect is best effort
        server_status = "unavailable"
        warnings.append(_warning_from_exception("HugeGraph Server is unavailable", exc))

    if include_counts and server_status == "available":
        vertex_count = _run_count_query("g.V().count()", "vertex", warnings)
        edge_count = _run_count_query("g.E().count()", "edge", warnings)

    ai_status, graph_index_info, ai_warnings = _check_ai_status(cfg)
    warnings.extend(ai_warnings)

    data: dict[str, Any] = {
        "graph": cfg.graph,
        "graphspace": cfg.graphspace,
        "hugegraph_server_status": server_status,
        "hugegraph_ai_status": ai_status,
        "vid_embedding_status": "available"
        if _has_graph_index_info(graph_index_info)
        else "unknown",
        "schema_summary": schema_summary,
        "vertex_count": vertex_count,
        "edge_count": edge_count,
        "index_status": {"total": _count_indexes(raw_schema)},
        "readonly": readonly if readonly is not None else cfg.is_readonly(),
    }
    if include_raw_schema:
        data["raw_schema"] = raw_schema
        data["simple_schema"] = simple_schema

    duration_ms = (time.time() - start) * 1000.0
    return envelope_ok(
        data,
        duration_ms=duration_ms,
        warnings=warnings,
        next_actions=_next_actions(data),
        readonly=data["readonly"],
    )


def _run_count_query(query: str, label: str, warnings: list[str]) -> int | None:
    try:
        result = execute_gremlin_read(query)
        count = _extract_count(result)
        if count is None:
            warnings.append(f"Failed to fetch {label} count")
        return count
    except Exception as exc:  # noqa: BLE001 - inspect is best effort
        warnings.append(_warning_from_exception(f"Failed to fetch {label} count", exc))
        return None


def _next_actions(data: dict[str, Any]) -> list[str]:
    """根据当前状态给出下一步建议，引导 Agent 使用正确的后续工具。"""
    actions = [
        "Use inspect_graph_tool with include_raw_schema=true for full schema details",
        "Use inspect_graph_tool with include_counts=true to fetch vertex/edge counts",
    ]
    if data.get("hugegraph_server_status") == "available":
        actions.append("Use execute_gremlin_read_tool for read-only graph exploration")
    else:
        actions.append("Check HugeGraph Server URL, graph name, and credentials")
    if data.get("hugegraph_ai_status") != "available":
        actions.append(
            "Check HugeGraph-AI URL if embedding or graph index features are needed"
        )
    return actions
