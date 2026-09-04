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
import os
import time
from typing import Any

from fastmcp import FastMCP

from hugegraph_mcp.backend_capabilities import BackendFeature, profile_for
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err
from hugegraph_mcp.gremlin_tools import execute_gremlin_read, execute_gremlin_write
from hugegraph_mcp.guard import Capability
from hugegraph_mcp.reconciler import reconcile_write
from hugegraph_mcp.tools.extract_graph_data import extract_graph_data
from hugegraph_mcp.tools.generate_gremlin import generate_gremlin
from hugegraph_mcp.tools.inspect_graph import inspect_graph
from hugegraph_mcp.tools.inspect_schema import inspect_schema
from hugegraph_mcp.tools.manage_graph_data import manage_graph_data
from hugegraph_mcp.tools.manage_schema import manage_schema
from hugegraph_mcp.tools.mutate_graph_properties import mutate_graph_properties
from hugegraph_mcp.tools.query_graph_data import query_graph_data
from hugegraph_mcp.tools.refresh_vid_embeddings import refresh_vid_embeddings
from hugegraph_mcp.write_contract import resolve_optional_legacy_locator
from hugegraph_mcp.write_executor import confirm_write, get_write_status

READONLY = MCPConfig.from_env().is_readonly()
MCP_TOOL_CONTRACT_VERSION = "2.0"
DEFAULT_TOOLSET = "v2_core"
VALID_TOOLSETS = frozenset({"v1", DEFAULT_TOOLSET})
LOGGER = logging.getLogger("hugegraph_mcp.server")

mcp = FastMCP("HugeGraph MCP")


def _active_toolset() -> str:
    value = os.getenv("HUGEGRAPH_MCP_TOOLSET", DEFAULT_TOOLSET).strip()
    if value in VALID_TOOLSETS:
        return value
    LOGGER.error("Invalid HUGEGRAPH_MCP_TOOLSET value %r; falling back to v1", value)
    return "v1"


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


def _call_legacy_write_tool(
    tool_name: str,
    func,
    *args,
    plan_hash: str | None,
    nonce: str | None,
    expires_at: float | None,
    **kwargs,
) -> dict[str, Any]:
    """Validate the deprecated locator before delegating to a write workflow."""

    start = time.perf_counter()
    resolution, error = resolve_optional_legacy_locator(
        plan_hash=plan_hash,
        nonce=nonce,
        expires_at=expires_at,
    )
    if error is not None:
        return _align_public_tool_envelope(
            error,
            tool_name=tool_name,
            duration_ms=(time.perf_counter() - start) * 1000.0,
        )

    result = _call_public_tool(
        tool_name,
        func,
        *args,
        plan_hash=plan_hash,
        nonce=nonce,
        expires_at=expires_at,
        **kwargs,
    )
    if resolution is not None:
        result["warnings"] = [
            *(result.get("warnings") or []),
            *resolution.warnings,
        ]
    return result


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
            suggestion = f"Set HUGEGRAPH_MCP_ADMIN_MODE=true and HUGEGRAPH_MCP_READONLY=false to enable {tool_name}."
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


_RAW_GREMLIN_HARD_BUDGET_FEATURES = (
    BackendFeature.READONLY_PRINCIPAL,
    BackendFeature.GREMLIN_EVALUATION_TIMEOUT,
    BackendFeature.REST_GREMLIN_WAIT_TIMEOUT,
    BackendFeature.GREMLIN_RESULT_ITEM_LIMIT,
    BackendFeature.HTTP_STREAMING_RESPONSE_LIMIT,
)


def _raw_gremlin_hard_budget_gate(tool_name: str) -> dict | None:
    """Fail closed until the complete raw-query safety contract is verified.

    The only evidence-backed deployment profile currently supported by this
    package lacks both a general server result cap and a streaming client byte
    cap. Post-materialization output guards cannot substitute for either.
    """
    profile = profile_for("1.7.0", "rocksdb")
    evidence = {
        feature.value: {
            "status": profile.status_for(feature).value,
            "reason": profile.evidence_for(feature).reason,
        }
        for feature in _RAW_GREMLIN_HARD_BUDGET_FEATURES
    }
    return envelope_err(
        ErrorType.FEATURE_DISABLED,
        f"{tool_name} is disabled because the raw Gremlin hard-budget contract is incomplete.",
        suggestion="Use structured MCP query tools; generating Gremlin with execute=false remains available.",
        source=tool_name,
        details={
            "tool": tool_name,
            "required_capabilities": evidence,
            "integration_contract_verified": False,
            "post_materialization_limits_are_hard_budgets": False,
        },
        duration_ms=0.0,
    )


# ========== Tool 1: inspect graph status and schema ==========


@mcp.tool()
def inspect_graph_tool(
    include_raw_schema: bool = False,
    include_counts: bool = False,
) -> dict:
    """检视 HugeGraph 服务器状态、schema 摘要和 AI 状态。

    Capability: READ.
    推荐作为连接后第一个调用的工具。默认不执行全图 count；
    include_counts=true 时才返回 vertex_count/edge_count 数值，
    否则这两个字段保留为 null。
    """
    result = _call_public_tool(
        "inspect_graph_tool",
        inspect_graph,
        include_raw_schema=include_raw_schema,
        include_counts=include_counts,
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
def get_write_status_tool(plan_id: str) -> dict:
    """Return the durable plan, operation, and receipt outcome by plan_id."""
    return _call_public_tool(
        "get_write_status_tool",
        get_write_status,
        plan_id=plan_id,
    )


@_register_v2_core_tool
def confirm_write_tool(plan_id: str) -> dict:
    """Confirm exactly one immutable server-persisted plan by plan_id only."""
    return _call_public_tool(
        "confirm_write_tool",
        confirm_write,
        plan_id=plan_id,
    )


@_register_v2_core_tool
def reconcile_write_tool(plan_id: str) -> dict:
    """Reconcile an UNKNOWN or PARTIAL plan by plan_id using read-only checks."""
    return _call_public_tool(
        "reconcile_write_tool",
        reconcile_write,
        plan_id=plan_id,
    )


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
    limit_policy: str = "reject_unbounded",
) -> dict:
    """Generate Gremlin without executing it. Capability: GENERATE.

    Every public raw Gremlin execution path is disabled until the hard resource
    budget contract is verified, so execute=true currently returns
    FEATURE_DISABLED. limit_policy remains as a compatibility parameter.
    """
    if execute:
        blocked = _raw_gremlin_hard_budget_gate("generate_gremlin_tool(execute=true)")
        if blocked:
            return blocked
        blocked = _admin_gate("generate_gremlin_tool(execute=true)")
        if blocked:
            return blocked
    return _call_public_tool(
        "generate_gremlin_tool",
        generate_gremlin,
        query=query,
        execute=execute,
        output_types=output_types,
        limit_policy=limit_policy,
    )


@mcp.tool()
def execute_gremlin_read_tool(gremlin_query: str, limit_policy: str = "reject_unbounded") -> dict:
    """Registered compatibility tool; raw read execution is currently disabled.

    Public raw Gremlin remains FEATURE_DISABLED until the deployment proves the
    complete server timeout/result cap, streaming byte cap, and readonly-principal
    contract. Use query_graph_data_tool for executable bounded reads.
    """
    blocked = _raw_gremlin_hard_budget_gate("execute_gremlin_read_tool")
    if blocked:
        return blocked
    blocked = _admin_gate("execute_gremlin_read_tool")
    if blocked:
        return blocked
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
    - dry_run: validate exactly one P0a create operation and issue a persisted plan.
    - apply: deprecated compatibility confirmation for one create operation.
      New clients confirm the returned plan_id with confirm_write_tool.
      Supports create_property_key, create_vertex_label, create_edge_label.
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
    return _call_legacy_write_tool(
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
    operation values: append, eliminate. Dry-run returns a before/after preview
    with confirmable=false. Confirmed mutation returns FEATURE_DISABLED because
    HugeGraph 1.7.0 lacks a backend-enforced atomic compare-and-set update.
    """
    return _call_legacy_write_tool(
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
    """Extract or plan structured graph data import.

    mode="extract" returns candidate graph_data without writing.
    mode="ingest" validates locally and issues an immutable plan_id; confirm it
    with confirm_write_tool. mode="table" returns FEATURE_DISABLED.
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
        return _call_legacy_write_tool(
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
    """Preview exact delete_vertex or delete_edge operations.

    An exact edge delete can be confirmed by plan_id after dry-run. Isolated
    vertex deletion is preview-only and confirmation returns FEATURE_DISABLED
    because the backend lacks an atomic no-incident-edge condition. Bulk
    conditional and cascade deletion are unsupported.
    """
    return _call_legacy_write_tool(
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
    """Disabled direct Gremlin write pending a verified hard-budget contract.

    Admin mode and readonly=false remain necessary but are not sufficient.
    """
    blocked = _raw_gremlin_hard_budget_gate("execute_gremlin_write_tool")
    if blocked:
        return blocked
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
