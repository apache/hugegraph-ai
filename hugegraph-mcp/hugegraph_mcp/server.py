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

"""FastMCP 服务器入口 — MCP 工具注册和轻量 mode 路由。

每个 @mcp.tool() 装饰的函数就是一个对外暴露的 MCP 工具。
server.py 只负责参数校验和 mode 分发，具体业务逻辑委托给 tools/ 下的模块。
"""

import logging
import logging.handlers
import os
import time
from typing import Any

# ---- Startup patch: prevent module-level pyhugegraph logging from writing files. ----
# pyhugegraph creates a RotatingFileHandler under 'logs/' during import. In MCP
# stdio mode this would corrupt the JSON protocol stream, so intercept makedirs
# and RotatingFileHandler.

_original_makedirs = os.makedirs


def _safe_makedirs(name, mode=0o777, exist_ok=False):
    if _is_logs_dir(name):
        return None
    return _original_makedirs(name, mode, exist_ok)


def _is_logs_dir(name) -> bool:
    try:
        path = os.fspath(name)
    except TypeError:
        return False
    return os.path.basename(os.path.normpath(path)).lower() == "logs"


_OriginalRotatingFileHandler = logging.handlers.RotatingFileHandler


class _NoOpFileHandler(logging.NullHandler):
    """无操作日志处理器 — 用于禁用文件日志记录。"""

    def __init__(self, *args, **kwargs):
        super().__init__()


def _patched_rotating_handler(filename, *args, **kwargs):
    if _is_logs_file(filename):
        return _NoOpFileHandler()
    return _OriginalRotatingFileHandler(filename, *args, **kwargs)


def _is_logs_file(filename) -> bool:
    try:
        path = os.path.normpath(os.fspath(filename))
    except TypeError:
        return False
    return any(part.lower() == "logs" for part in path.split(os.sep))


logging.handlers.RotatingFileHandler = _patched_rotating_handler

os.makedirs = _safe_makedirs

try:
    # ---- Safely import pyhugegraph-dependent modules within the patch scope. ----
    from fastmcp import FastMCP

    from hugegraph_mcp.config import MCPConfig
    from hugegraph_mcp.envelope import ErrorType, envelope_err
    from hugegraph_mcp.gremlin_tools import execute_gremlin_read, execute_gremlin_write
    from hugegraph_mcp.guard import Capability
    from hugegraph_mcp.tools.extract_graph_data import extract_graph_data
    from hugegraph_mcp.tools.generate_gremlin import generate_gremlin
    from hugegraph_mcp.tools.inspect_graph import inspect_graph
    from hugegraph_mcp.tools.inspect_schema import inspect_schema
    from hugegraph_mcp.tools.manage_graph_data import manage_graph_data
    from hugegraph_mcp.tools.manage_schema import manage_schema
    from hugegraph_mcp.tools.mutate_graph_properties import mutate_graph_properties
    from hugegraph_mcp.tools.query_graph_data import query_graph_data
    from hugegraph_mcp.tools.refresh_vid_embeddings import refresh_vid_embeddings
finally:
    os.makedirs = _original_makedirs
    logging.handlers.RotatingFileHandler = _OriginalRotatingFileHandler

READONLY = MCPConfig.from_env().is_readonly()
MCP_TOOL_CONTRACT_VERSION = "2.0"
DEFAULT_TOOLSET = "v2_core"

mcp = FastMCP("HugeGraph MCP")


def _active_toolset() -> str:
    value = os.getenv("HUGEGRAPH_MCP_TOOLSET", DEFAULT_TOOLSET).strip()
    return "v1" if value == "v1" else DEFAULT_TOOLSET


def _register_v2_core_tool(func):
    if _active_toolset() == "v1":
        return func
    return mcp.tool()(func)


def _align_public_tool_envelope(
    result: dict[str, Any],
    *,
    tool_name: str,
    duration_ms: float,
) -> dict[str, Any]:
    """Add public wrapper metadata without changing the inner tool payload."""
    aligned = dict(result)
    meta = dict(aligned.get("meta") or {})
    meta.setdefault("duration_ms", duration_ms)
    aligned["meta"] = meta

    if aligned.get("ok") is False and isinstance(aligned.get("error"), dict):
        error = dict(aligned["error"])
        error["source"] = tool_name
        aligned["error"] = error

    return aligned


def _call_public_tool(tool_name: str, func, *args, **kwargs) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        result = func(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - tool boundary returns an envelope
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            f"{tool_name} failed: {exc!s}",
            source=tool_name,
            details={"tool": tool_name},
            duration_ms=(time.perf_counter() - start) * 1000.0,
        )
    return _align_public_tool_envelope(
        result,
        tool_name=tool_name,
        duration_ms=(time.perf_counter() - start) * 1000.0,
    )


def _is_admin_mode_enabled() -> bool:
    return MCPConfig.from_env().admin_mode


def _admin_gate(tool_name: str, *, requires_write: bool = False) -> dict | None:
    """Return FEATURE_DISABLED envelope if admin mode is not enabled, else None."""
    if not _is_admin_mode_enabled():
        enable_env = {"admin_mode": "HUGEGRAPH_MCP_ADMIN_MODE"}
        required_env = {"HUGEGRAPH_MCP_ADMIN_MODE": "true"}
        suggestion = f"Set HUGEGRAPH_MCP_ADMIN_MODE=true to enable {tool_name}."
        if requires_write:
            enable_env["readonly"] = "HUGEGRAPH_MCP_READONLY"
            required_env["HUGEGRAPH_MCP_READONLY"] = "false"
            suggestion = (
                f"Set HUGEGRAPH_MCP_ADMIN_MODE=true and HUGEGRAPH_MCP_READONLY=false "
                f"to enable {tool_name}."
            )
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            f"{tool_name} is an admin/debug tool and is disabled by default.",
            suggestion=suggestion,
            source=tool_name,
            details={
                "tool": tool_name,
                "toolset": _active_toolset(),
                "enable_env": enable_env,
                "required_env": required_env,
            },
        )

    if requires_write and MCPConfig.from_env().is_readonly():
        return envelope_err(
            ErrorType.READONLY_VIOLATION,
            f"{tool_name} requires HUGEGRAPH_MCP_READONLY=false.",
            suggestion=(
                "Set HUGEGRAPH_MCP_ADMIN_MODE=true and HUGEGRAPH_MCP_READONLY=false "
                "before retrying this admin write tool."
            ),
            source=tool_name,
            details={
                "tool": tool_name,
                "required_env": {
                    "HUGEGRAPH_MCP_ADMIN_MODE": "true",
                    "HUGEGRAPH_MCP_READONLY": "false",
                },
            },
            readonly=True,
        )
    return None


# ========== Tool 1: inspect graph status and schema ==========


@mcp.tool()
def inspect_graph_tool(include_raw_schema: bool = False) -> dict:
    """检视 HugeGraph 服务器状态、schema 摘要、点边计数和 AI 状态。

    Capability: READ.
    推荐作为连接后第一个调用的工具。
    """
    result = _call_public_tool(
        "inspect_graph_tool",
        inspect_graph,
        include_raw_schema=include_raw_schema,
    )
    if result.get("ok") and isinstance(result.get("data"), dict):
        result["data"]["mcp_tool_contract_version"] = MCP_TOOL_CONTRACT_VERSION
        result["data"]["toolset"] = _active_toolset()
    meta = dict(result.get("meta") or {})
    meta["mcp_tool_contract_version"] = MCP_TOOL_CONTRACT_VERSION
    meta["toolset"] = _active_toolset()
    result["meta"] = meta
    return result


@_register_v2_core_tool
def inspect_schema_tool(
    include_raw_schema: bool = False,
    include_relations: bool = True,
    include_index_labels: bool = True,
    filter_kind: str | None = None,
    filter_name: str | None = None,
) -> dict:
    """Inspect HugeGraph schema objects and relations.

    Capability: READ.
    filter_kind values: property_key, vertex_label, edge_label, index_label.
    filter_name requires filter_kind and selects one schema object by name.
    include_raw_schema returns the raw HugeGraph schema; include_relations and
    include_index_labels control relation/index sections.
    """
    return _call_public_tool(
        "inspect_schema_tool",
        inspect_schema,
        include_raw_schema=include_raw_schema,
        include_relations=include_relations,
        include_index_labels=include_index_labels,
        filter_kind=filter_kind,
        filter_name=filter_name,
    )


@_register_v2_core_tool
def query_graph_data_tool(
    target: str,
    operation: str,
    id: Any = None,
    ids: list[Any] | None = None,
    label: str | None = None,
    properties: dict[str, Any] | None = None,
    limit: int | None = None,
    page: str | None = None,
    vertex_id: Any = None,
    direction: str | None = None,
) -> dict:
    """Query HugeGraph vertices or edges by typed GraphManager operations.

    Capability: READ.
    target values: vertex, edge.
    operation values and required fields:
    - get_by_id: requires id.
    - get_by_ids: requires non-empty ids.
    - page: vertex requires label; edge may use label and/or vertex_id+direction.
    - condition: exact-match properties only; no Gremlin full-scan fallback.
    limit defaults to 100 and rejects values above 500. For edge page/condition,
    direction is required when vertex_id is provided.
    """
    return _call_public_tool(
        "query_graph_data_tool",
        query_graph_data,
        target=target,
        operation=operation,
        id=id,
        ids=ids,
        label=label,
        properties=properties,
        limit=limit,
        page=page,
        vertex_id=vertex_id,
        direction=direction,
    )


# ========== V1 stable tools ==========


@mcp.tool()
def generate_gremlin_tool(
    query: str,
    execute: bool = False,
    output_types: list[str] | None = None,
    limit_policy: str = "warn",
) -> dict:
    """V1 稳定工具：自然语言 → Gremlin 生成。

    默认不执行（execute=false），返回生成的 Gremlin 查询。
    设置 execute=true 可执行生成的只读 Gremlin。Capability: GENERATE.
    limit_policy 仅在 execute=true 时传给只读执行：warn、reject_unbounded、
    auto_append。auto_append 会返回 original_gremlin/executed_gremlin/rewrite_reason。
    """
    return _call_public_tool(
        "generate_gremlin_tool",
        generate_gremlin,
        query=query,
        execute=execute,
        output_types=output_types,
        limit_policy=limit_policy,
    )


@mcp.tool()
def execute_gremlin_read_tool(gremlin_query: str, limit_policy: str = "warn") -> dict:
    """V1 稳定工具：执行只读 Gremlin 遍历查询。

    Capability: READ.
    经过 GremlinPolicy 安全检查后执行。
    limit_policy values:
    - warn: execute and return cost warnings for unbounded reads.
    - reject_unbounded: reject safe but unbounded reads before execution.
    - auto_append: append .limit(100) to simple unbounded g.V()/g.E() queries and
      return original_gremlin/executed_gremlin/rewrite_reason.
    """
    return _call_public_tool(
        "execute_gremlin_read_tool",
        execute_gremlin_read,
        gremlin_query,
        limit_policy=limit_policy,
    )


@mcp.tool()
def extract_graph_data_tool(
    text: str,
    graph_schema: dict | None = None,
    example_prompt: str | None = None,
) -> dict:
    """V1 稳定工具：自然语言文本 → 候选 graph_data（不写入）。

    返回提取的顶点和边数据，供后续导入使用。
    graph_schema 可传入 HugeGraph schema；为空时从当前 HugeGraph 读取 live schema，
    并在 schema_ref 中返回图目标和 schema fingerprint。
    """
    return _call_public_tool(
        "extract_graph_data_tool",
        extract_graph_data,
        text=text,
        schema=graph_schema,
        example_prompt=example_prompt,
    )


@mcp.tool()
def design_schema_tool(operations: list[dict] | None = None) -> dict:
    """V1 稳定工具：schema 设计指导。

    提供 schema 设计建议和最佳实践。
    """
    return _call_public_tool(
        "design_schema_tool",
        manage_schema,
        mode="design",
        operations=operations,
    )


@mcp.tool()
def apply_schema_tool(
    mode: str,
    operations: list[dict] | None = None,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> dict:
    """Schema design/validate/dry_run/apply entry point.

    Capability: SCHEMA_WRITE for mode=apply; READ-like validation for other modes.
    mode values:
    - design: schema design guidance; operations optional.
    - validate: validate operations against live schema.
    - dry_run: validate P0a create operations and return plan_hash/nonce/expires_at.
    - apply: P0a only. Requires confirm=true, plan_hash, nonce, expires_at from
      dry_run. Supports create_property_key, create_vertex_label, create_edge_label.
      Rejects create_index_label, schema append/eliminate, remove/drop.
    """
    start = time.perf_counter()
    if mode == "apply" and _active_toolset() == "v1":
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            "Schema apply is disabled in V1. Use validate or dry_run mode.",
            suggestion="Use mode='validate' or mode='dry_run' to preview schema changes.",
            source="apply_schema_tool",
            details={"mode": mode, "tool": "apply_schema_tool"},
            duration_ms=(time.perf_counter() - start) * 1000.0,
        )
    return _call_public_tool(
        "apply_schema_tool",
        manage_schema,
        mode=mode,
        operations=operations,
        confirm=confirm,
        plan_hash=plan_hash,
        nonce=nonce,
        expires_at=expires_at,
    )


@_register_v2_core_tool
def mutate_graph_properties_tool(
    target: str,
    operation: str,
    id: Any,
    properties: dict[str, Any],
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> dict:
    """Append or eliminate properties on one vertex or edge.

    Capability: DATA_WRITE.
    target values: vertex, edge.
    operation values: append, eliminate. Both require the same chain:
    dry_run=true -> review before/after and plan_hash -> dry_run=false,
    confirm=true with plan_hash, nonce, and expires_at.
    The confirm step re-reads schema and target; changed targets return
    TARGET_CHANGED and are not mutated.
    """
    return _call_public_tool(
        "mutate_graph_properties_tool",
        mutate_graph_properties,
        target=target,
        operation=operation,
        id=id,
        properties=properties,
        dry_run=dry_run,
        confirm=confirm,
        plan_hash=plan_hash,
        nonce=nonce,
        expires_at=expires_at,
    )


# ========== Graph data import entry point ==========


@mcp.tool()
def import_graph_data_tool(
    mode: str,
    text: str | None = None,
    graph_schema: dict | None = None,
    example_prompt: str | None = None,
    graph_data: dict | None = None,
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> dict:
    """V1 图数据导入入口。

    mode="extract": 自然语言文本 → 候选 graph_data
    mode="ingest": MCP 本地校验+dry_run/confirm+Gremlin 导入 graph_data
    mode="table": 当前 MCP contract 不支持（返回 FEATURE_DISABLED）
    """
    start = time.perf_counter()

    if mode == "extract":
        if not text:
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                "text is required for mode='extract'",
                source="import_graph_data_tool",
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
        return _call_public_tool(
            "import_graph_data_tool",
            extract_graph_data,
            text=text,
            schema=graph_schema,
            example_prompt=example_prompt,
        )

    if mode == "ingest":
        if graph_data is None:
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                "graph_data is required for mode='ingest'",
                source="import_graph_data_tool",
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
        return _call_public_tool(
            "import_graph_data_tool",
            manage_graph_data,
            mode="import",
            graph_data=graph_data,
            dry_run=dry_run,
            confirm=confirm,
            plan_hash=plan_hash,
            nonce=nonce,
            expires_at=expires_at,
            plan_tool_name="import_graph_data_tool",
        )

    if mode == "table":
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            "Table import is not supported by the current MCP contract.",
            suggestion=(
                "Use import_graph_data_tool(mode='extract') for text extraction, "
                "then import_graph_data_tool(mode='ingest') for validated graph_data."
            ),
            source="import_graph_data_tool",
            details={"mode": mode, "tool": "import_graph_data_tool"},
            duration_ms=(time.perf_counter() - start) * 1000.0,
        )

    return envelope_err(
        ErrorType.VALIDATION_ERROR,
        f"Unknown mode: {mode!r}. Use 'extract' or 'ingest'.",
        source="import_graph_data_tool",
        details={"mode": mode},
        duration_ms=(time.perf_counter() - start) * 1000.0,
    )


# ========== Controlled graph data deletion entry point ==========


@mcp.tool()
def delete_graph_data_tool(
    change_plan: dict,
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> dict:
    """V1 稳定工具：受控删除图数据。

    只支持精确 delete_vertex/delete_edge change_plan。
    必须经过 dry_run -> plan_hash -> confirm；不支持批量条件删除或级联删除。
    """
    return _call_public_tool(
        "delete_graph_data_tool",
        manage_graph_data,
        mode="delete",
        change_plan=change_plan,
        dry_run=dry_run,
        confirm=confirm,
        plan_hash=plan_hash,
        nonce=nonce,
        expires_at=expires_at,
        plan_tool_name="delete_graph_data_tool",
    )


# ========== Advanced debugging tools ==========


@mcp.tool()
def refresh_vid_embeddings_tool(confirm: bool = False) -> dict:
    """手动刷新 VID 嵌入 — 需 admin mode 且 readonly=false。"""
    blocked = _admin_gate("refresh_vid_embeddings_tool", requires_write=True)
    if blocked:
        return blocked
    return _call_public_tool(
        "refresh_vid_embeddings_tool",
        refresh_vid_embeddings,
        confirm=confirm,
    )


@mcp.tool()
def execute_gremlin_write_tool(gremlin_query: str) -> dict:
    """Break-glass direct Gremlin write for an isolated trusted admin transport.

    This is the sole write-safety-chain exception: it has no preview, dry-run,
    plan hash, or confirmation step. It requires admin mode and readonly=false.
    """
    blocked = _admin_gate("execute_gremlin_write_tool", requires_write=True)
    if blocked:
        return blocked
    return _call_public_tool(
        "execute_gremlin_write_tool",
        execute_gremlin_write,
        gremlin_query,
        capability=Capability.DEBUG_WRITE,
    )


def main() -> None:
    """CLI 入口 — 默认 stdio 模式。"""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover - manual launch
    main()
