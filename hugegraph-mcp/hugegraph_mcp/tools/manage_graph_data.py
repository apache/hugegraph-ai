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


"""Graph data management orchestration layer.

manage_graph_data() keeps the V1 import/delete safety-chain entry point while
validation, Gremlin generation, and execution helpers live in focused modules.
"""

from typing import Any

from hugegraph_mcp import gremlin_tools, schema_tools
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.confirmable_workflow import (
    confirm_required_error,
    issue_plan,
    mark_readonly_preview,
    plan_hash_error,
    replayed_plan_error,
    verify_and_consume_plan,
)
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.plan_hash import (
    build_plan_context,
    compute_payload_digest,
    compute_plan_hash,
)
from hugegraph_mcp.tools import ingest_graph_data
from hugegraph_mcp.tools.graph_data_execute import (
    _fetch_live_schema,
    _mutation_summary,
    calculate_graph_change_plan_hash,
    dry_run_graph_change_plan,
    execute_graph_change_plan,
)
from hugegraph_mcp.tools.graph_data_mapping import (
    GraphChangePlan,
    _change_plan_from_operations,
    graph_data_to_change_plan,
)
from hugegraph_mcp.tools.graph_data_validate import (
    _operations,
    _schema_summary,
    _validate_mode_operations,
    validate_graph_change_plan,
)
from hugegraph_mcp.write_limits import (
    graph_data_operation_count,
    operation_count_from_list,
    write_limit_envelope,
)

# Only export public entry points; import private helpers from graph_data_* modules.
__all__ = [
    "GraphChangePlan",
    "calculate_graph_change_plan_hash",
    "dry_run_graph_change_plan",
    "execute_graph_change_plan",
    "graph_data_to_change_plan",
    "gremlin_tools",
    "manage_graph_data",
    "schema_tools",
    "validate_graph_change_plan",
]


# ---- Unified entry point ----


def manage_graph_data(
    mode: str,
    graph_data: dict[str, Any] | None = None,
    change_plan: dict[str, Any] | list[dict[str, Any]] | None = None,
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
    extra_hash_context: dict[str, Any] | None = None,
    plan_tool_name: str = "manage_graph_data",
) -> dict[str, Any]:
    """统一图数据管理入口。

    安全链：validate → dry_run → confirm check → plan_hash match → execute
    每个环节失败均返回结构化错误，不抛异常。
    """
    if mode == "import":
        if graph_data is None:
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                "graph_data is required for mode='import'",
            )
        if not isinstance(graph_data, dict):
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                "graph_data must be an object for mode='import'.",
                details={"received_type": type(graph_data).__name__},
            )
    elif mode == "delete":
        if change_plan is None:
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                f"change_plan is required for mode='{mode}'",
            )
        plan = (
            change_plan
            if isinstance(change_plan, dict)
            else _change_plan_from_operations(change_plan)
        )
    else:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"Unknown mode: {mode!r}. Use 'import' or 'delete'.",
            details={"mode": mode},
        )

    if mode == "import":
        limit_error = write_limit_envelope(
            graph_data_operation_count(graph_data),
            graph_data,
        )
    else:
        limit_error = write_limit_envelope(
            operation_count_from_list(_operations(plan)),
            plan,
        )
    if limit_error is not None:
        return limit_error

    if not dry_run and confirm:
        replay_error = replayed_plan_error(nonce)
        if replay_error is not None:
            return replay_error

    # Read the live schema before writing. Do not execute without it because
    # primary keys, endpoints, and property validity depend on the real schema.
    live_schema = _fetch_live_schema()
    if live_schema is None:
        return envelope_err(
            ErrorType.CONNECTION_FAILED,
            "Cannot read live schema from HugeGraph Server. Schema validation is required before graph data changes.",
            suggestion="Ensure HugeGraph Server is running and accessible, then retry.",
            retryable=True,
        )

    if mode == "import" and graph_data is not None:
        # import additionally validates the original graph_data for rules that
        # are difficult to express in change_plan: complete vertex keys,
        # resolvable edge endpoints, and duplicate identities in the payload.
        payload_validation = ingest_graph_data.validate_graph_payload(
            graph_data,
            live_schema=live_schema,
        )
        if not payload_validation["valid"]:
            return envelope_err(
                ErrorType.SCHEMA_MISMATCH,
                "Graph data does not match live schema.",
                details={"errors": payload_validation["errors"]},
            )
        # public import scalar source/target values require the live schema to
        # distinguish a single primary-key value from an explicit ID; outV/inV
        # always retain ID semantics.
        plan = graph_data_to_change_plan(graph_data, live_schema=live_schema)

    # The mode/op relationship is the first boundary: import permits only create,
    # while delete permits only deletion operations, preventing high-risk actions
    # from being routed through a lower-risk entry point.
    mode_validation = _validate_mode_operations(mode, plan)
    if not mode_validation["valid"]:
        return envelope_err(
            ErrorType.INVALID_GRAPH_DATA,
            "Graph change plan contains operations outside the selected mode.",
            details={"errors": mode_validation["errors"]},
        )

    dry_run_result = dry_run_graph_change_plan(
        plan, live_schema, extra_hash_context=extra_hash_context
    )
    if not dry_run_result["valid"]:
        errors = dry_run_result["errors"]
        error_type = next(
            (
                error["error_type"]
                for error in errors
                if isinstance(error, dict) and error.get("error_type")
            ),
            ErrorType.INVALID_GRAPH_DATA,
        )
        return envelope_err(
            error_type,
            "Graph change plan is invalid.",
            details={"errors": errors},
            warnings=dry_run_result.get("warnings", []),
        )

    plan_context, _ = _build_manage_graph_data_plan_context(
        tool_name=plan_tool_name,
        mode=mode,
        plan=plan,
        live_schema=live_schema,
        nonce=nonce,
        extra_hash_context=extra_hash_context,
    )
    target_bound_hash = compute_plan_hash(plan_context)
    dry_run_result["plan_hash"] = target_bound_hash
    dry_run_result["plan_context"] = _plan_context_payload(plan_context)
    dry_run_result["confirmable"] = True

    if dry_run:
        warnings = list(dry_run_result.get("warnings", []))
        next_actions: list[str] = []
        if MCPConfig.from_env().is_readonly():
            dry_run_result, readonly_warnings, readonly_next_actions = (
                mark_readonly_preview(
                    dry_run_result,
                    warning=(
                        "This dry-run was generated while HUGEGRAPH_MCP_READONLY=true. "
                        "Its plan_hash is preview-only; set HUGEGRAPH_MCP_READONLY=false "
                        "and rerun dry_run before confirming writes."
                    ),
                    next_action="Set HUGEGRAPH_MCP_READONLY=false and rerun dry_run before confirm.",
                )
            )
            warnings.extend(readonly_warnings)
            next_actions.extend(readonly_next_actions)
        else:
            issue_error = issue_plan(plan_context, target_bound_hash)
            if issue_error is not None:
                return issue_error
        return envelope_ok(
            dry_run_result,
            warnings=warnings,
            next_actions=next_actions,
        )

    # Recheck readonly at execution time instead of relying only on write tools
    # being hidden during server registration; long-running processes and tests
    # may change configuration or call internal functions directly.
    violation = guard(Capability.DATA_WRITE)
    if violation is not None:
        return violation

    if not confirm:
        return confirm_required_error(
            message="Graph data changes require confirm=True after a dry_run.",
            suggestion="Run dry_run=True, review preview and warnings, then pass confirm=True with the returned plan_hash.",
        )

    schema_summary = _schema_summary(live_schema)
    valid, error_type, details = verify_and_consume_plan(
        submitted_hash=plan_hash,
        tool_name=plan_tool_name,
        mode=mode,
        payload_digest=_manage_graph_data_payload_digest(
            plan,
            extra_hash_context=extra_hash_context,
        ),
        schema_hash=compute_payload_digest(schema_summary) if schema_summary else None,
        nonce=nonce,
        expires_at=expires_at,
        extra_context={"extra_hash_context": extra_hash_context or {}},
    )
    if not valid:
        return plan_hash_error(
            error_type=error_type,
            details=details,
            mismatch_message="Provided plan_hash does not match the current graph data change plan.",
            expired_message="Graph data change plan has expired.",
            suggestion="Run dry_run=True again and use the returned plan_hash.",
        )

    execute_result = execute_graph_change_plan(plan, live_schema=live_schema)
    if isinstance(execute_result, dict) and execute_result.get("ok") is False:
        return envelope_err(
            execute_result["error"]["type"],
            execute_result["error"]["message"],
            suggestion=execute_result["error"].get("suggestion"),
            # Confirmation has already been consumed and the executor may
            # have applied an unreported side effect. Require a fresh dry-run
            # before any retry instead of encouraging blind replay.
            retryable=False,
            details=_normalize_execute_result(execute_result, plan),
        )

    normalized = _normalize_execute_result(execute_result, plan)
    if normalized.get("success") is False or normalized.get("status") in {
        "partial",
        "error",
        "degraded",
    }:
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            "Graph change execution did not complete successfully.",
            retryable=bool(normalized.get("retryable")),
            details=normalized,
            warnings=normalized.get("warnings", []),
        )

    return envelope_ok(normalized)


def _build_manage_graph_data_plan_context(
    *,
    tool_name: str,
    mode: str,
    plan: Any,
    live_schema: dict[str, Any],
    nonce: str | None,
    extra_hash_context: dict[str, Any] | None,
):
    schema_summary = _schema_summary(live_schema)
    return build_plan_context(
        tool_name=tool_name,
        mode=mode,
        payload_digest=_manage_graph_data_payload_digest(
            plan,
            extra_hash_context=extra_hash_context,
        ),
        schema_hash=compute_payload_digest(schema_summary) if schema_summary else None,
        nonce=nonce,
        extra_context={"extra_hash_context": extra_hash_context or {}},
    )


def _manage_graph_data_payload_digest(
    plan: Any,
    *,
    extra_hash_context: dict[str, Any] | None,
) -> str:
    payload: dict[str, Any] = {"change_plan": plan}
    if extra_hash_context is not None:
        payload["extra_hash_context"] = extra_hash_context
    return compute_payload_digest(payload)


def _plan_context_payload(plan_context) -> dict[str, Any]:
    return {
        "nonce": plan_context.nonce,
        "expires_at": plan_context.expires_at,
        "graph_url": plan_context.graph_url,
        "graph_name": plan_context.graph_name,
        "graphspace": plan_context.graphspace,
        "principal": plan_context.principal,
        "readonly": plan_context.readonly,
    }


def _normalize_execute_result(execute_result: Any, plan: Any) -> dict[str, Any]:
    operations = _operations(plan)
    planned = _mutation_summary(operations)

    if isinstance(execute_result, dict) and execute_result.get("ok") is False:
        return {
            "status": "error",
            "success": False,
            "planned": planned,
            "written": {},
            "failed_items": [execute_result["error"]],
            "warnings": execute_result.get("warnings", []),
            "retryable": False,
            "compensation_suggestions": [],
            "results": [],
            "mutation_summary": planned,
        }

    if not isinstance(execute_result, dict):
        return {
            "status": "degraded",
            "success": False,
            "planned": planned,
            "written": {},
            "failed_items": [{"result": execute_result}],
            "warnings": ["Graph change execution returned an unrecognized result."],
            "retryable": False,
            "compensation_suggestions": ["Inspect graph state before retrying."],
            "results": [],
            "mutation_summary": planned,
        }

    raw_results = execute_result.get("results")
    results = raw_results if isinstance(raw_results, list) else []
    failed_items = execute_result.get("failed_items")
    if not isinstance(failed_items, list):
        failed_items = []

    if (
        execute_result.get("success") is True
        and len(results) == len(operations)
        and not failed_items
    ):
        status = "success"
    elif results:
        status = "partial"
    elif execute_result.get("success") is False or failed_items:
        status = "error"
    else:
        status = "degraded"

    written = _mutation_summary(
        [operation for operation, _result in zip(operations, results, strict=False)]
    )
    return {
        "status": status,
        "success": status == "success",
        "planned": planned,
        "written": written,
        "failed_items": failed_items,
        "warnings": execute_result.get("warnings", []),
        "retryable": False,
        "compensation_suggestions": (
            ["Inspect graph state before retrying remaining operations."]
            if status in ("partial", "degraded")
            else []
        ),
        "results": results,
        "mutation_summary": execute_result.get("mutation_summary", planned),
    }
