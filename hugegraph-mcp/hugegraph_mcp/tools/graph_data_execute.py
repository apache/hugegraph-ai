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

"""Graph data change plan compilation and execution.

Dry-run resolves delete predicates to immutable backend IDs. Execution consumes
only those compiled IDs, preventing predicate drift between preview and apply.
"""

import hashlib
import json
from copy import deepcopy
from typing import Any

from hugegraph_mcp import gremlin_tools
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability
from hugegraph_mcp.tools.graph_data_gremlin import (
    _delete_target_query,
    _edge_match_query,
    _g,
    _source_vertex_match_query,
    _target_vertex_match_query,
    _vertex_match_query,
    _write_query,
)
from hugegraph_mcp.tools.graph_data_validate import (
    WRITE_OPS,
    ValidationError,
    _operations,
    _validation_error,
    validate_graph_change_plan,
)
from hugegraph_mcp.tools.live_schema import fetch_live_schema_or_none
from hugegraph_mcp.tools.schema_utils import (
    normalized_schema_summary,
    primary_key_names,
    schema_payload,
)
from hugegraph_mcp.write_limits import (
    collect_write_limit_errors,
    operation_count_from_list,
)
from hugegraph_mcp.write_plan import ApplyStatus, aggregate_plan_status

# ---- Gremlin execution helpers ----


def _read_count(gremlin_query: str) -> dict[str, Any]:
    result = gremlin_tools.execute_gremlin_read(f"{gremlin_query}.count()")
    # execute_gremlin_read is migrating to the unified envelope, but retain
    # the legacy success=false shape so lower-level format differences do not
    # break the dry-run safety chain.
    if isinstance(result, dict) and result.get("ok") is False:
        return result
    if isinstance(result, dict) and result.get("success") is False:
        return envelope_err(
            ErrorType.CONNECTION_FAILED,
            "HugeGraph read query failed during graph change dry run.",
            details=result,
            retryable=True,
        )
    data = result.get("data") if isinstance(result, dict) else result
    count = _extract_count_value(data)
    try:
        matched_count = int(count)
    except (TypeError, ValueError):
        return envelope_err(
            ErrorType.INVALID_GRAPH_DATA,
            "HugeGraph count query returned a non-numeric result.",
            details={"query": gremlin_query, "data": data},
        )
    return envelope_ok({"matched_count": matched_count})


def _extract_count_value(data: Any) -> Any:
    if isinstance(data, dict) and "data" in data:
        return _extract_count_value(data.get("data"))
    if isinstance(data, list):
        if not data:
            return 0
        return _extract_count_value(data[0])
    return data


def _read_values(gremlin_query: str) -> dict[str, Any]:
    result = gremlin_tools.execute_gremlin_read(gremlin_query)
    if isinstance(result, dict) and result.get("ok") is False:
        return result
    if isinstance(result, dict) and result.get("success") is False:
        return envelope_err(
            ErrorType.CONNECTION_FAILED,
            "HugeGraph read query failed during graph change dry run.",
            details=result,
            retryable=True,
        )
    data = result.get("data") if isinstance(result, dict) else result
    while isinstance(data, dict) and "data" in data:
        data = data["data"]
    if data is None:
        values = []
    elif isinstance(data, list):
        values = data
    else:
        values = [data]
    return envelope_ok({"values": values})


def _mutation_summary(operations: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for operation in operations:
        op = str(operation.get("op") or operation.get("type") or "unknown")
        counts[op] = counts.get(op, 0) + 1
    return counts


# ---- Plan hash calculation — tamper-resistance check ----


def calculate_graph_change_plan_hash(
    change_plan: Any,
    graph: str | None = None,
    graphspace: str | None = None,
    schema_summary: dict[str, Any] | None = None,
    extra_hash_context: dict[str, Any] | None = None,
) -> str:
    """基于 change_plan + graph/schema 上下文计算确定性哈希。

    用于防篡改安全链：dry_run 返回 plan_hash，执行时校验匹配。
    """
    cfg = MCPConfig.from_env()
    payload: dict[str, Any] = {
        "change_plan": change_plan,
        "graph": cfg.graph if graph is None else graph,
        "graphspace": cfg.graphspace if graphspace is None else graphspace,
    }
    if schema_summary is not None:
        payload["schema_summary"] = schema_summary
    if extra_hash_context is not None:
        # Upstream callers may include source summaries and mapping configuration
        # in the extra context so different sources do not reuse one confirmation hash.
        payload["extra_hash_context"] = extra_hash_context
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


# ---- Dry-run preview ----


def dry_run_graph_change_plan(
    change_plan: Any,
    live_schema: dict[str, Any],
    extra_hash_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """干跑 — 校验 + 预览每个操作的影响（matched_count），不执行写入。

    delete 操作通过一次有界 ID 查询解析唯一后端目标，
    并将 target_id 写入仅供服务端执行的 compiled_plan。
    """
    operations = _operations(change_plan)
    limit_errors = collect_write_limit_errors(
        operation_count_from_list(operations),
        change_plan,
    )
    if limit_errors:
        return {
            "valid": False,
            "errors": limit_errors,
            "warnings": [],
        }
    validation = validate_graph_change_plan(change_plan, live_schema)
    if not validation["valid"]:
        return validation
    preview: list[dict[str, Any]] = []
    errors: list[ValidationError] = []
    compiled_plan = deepcopy(change_plan)
    compiled_operations = _operations(compiled_plan)

    for idx, operation in enumerate(operations):
        op = str(operation.get("op") or operation.get("type"))
        item = {
            "operation_index": idx,
            "op": op,
            "label": operation.get("label"),
            "action": op,
        }
        if op == "create_edge":
            endpoint_failed = _append_edge_endpoint_counts(
                idx=idx,
                operation=operation,
                op=op,
                item=item,
                errors=errors,
                planned_operations=operations[:idx],
                compiled_operation=compiled_operations[idx],
            )
            preview.append(item)
            if endpoint_failed:
                continue
            item["matched_count"] = None
            continue

        if op == "create_vertex":
            _append_create_vertex_identity_counts(
                idx=idx,
                operation=operation,
                item=item,
                errors=errors,
                live_schema=live_schema,
            )
            item["matched_count"] = None
            preview.append(item)
            continue

        if op not in WRITE_OPS:
            # create operations do not need to match one existing record; schema
            # and payload validity was checked during validation, so dry-run only
            # displays the plan.
            item["matched_count"] = None
            preview.append(item)
            continue

        if op == "delete_edge":
            # For edge deletion, verify both endpoints are unique before verifying
            # the edge itself, so errors identify source/target rather than a vague
            # edge-matching failure.
            endpoint_failed = _append_edge_endpoint_counts(
                idx=idx,
                operation=operation,
                op=op,
                item=item,
                errors=errors,
            )
            if endpoint_failed:
                preview.append(item)
                continue

        match_query = _edge_match_query(operation) if op == "delete_edge" else _vertex_match_query(operation)
        id_result = _read_values(f"{match_query}.limit(2).id()")
        if not id_result.get("ok"):
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    "target id query failed",
                    "Verify HugeGraph Server is available and retry the dry run.",
                )
            )
            continue
        target_ids = id_result["data"]["values"]
        matched_count = len(target_ids)
        item["matched_count"] = matched_count

        if op in {"delete_vertex", "delete_edge"} and matched_count != 1:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"{op} matched_count must be 1, got {matched_count}",
                    "Narrow the match criteria so exactly one graph element is affected.",
                )
            )

        target_id = target_ids[0] if matched_count == 1 else None
        if target_id is not None:
            item["target_id"] = target_id
            compiled_operations[idx]["target_id"] = target_id

        if op == "delete_vertex" and operation.get("cascade", False) is False and matched_count == 1:
            # By default, refuse to delete vertices with incident edges to avoid
            # unpredictable data loss from HugeGraph-side cascading behavior.
            # Users must explicitly delete the incident edges first.
            edge_count_result = _read_count(f"g.V({_g(target_id)}).bothE()")
            if not edge_count_result.get("ok"):
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        "associated edge count query failed",
                        "Verify HugeGraph Server is available and retry the dry run.",
                    )
                )
            else:
                edge_count = edge_count_result["data"]["matched_count"]
                item["associated_edge_count"] = edge_count
                if edge_count > 0:
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            "delete_vertex cascade=false but vertex has associated edges",
                            "Set cascade=true or delete associated edges first.",
                            "BLOCKED_BY_RELATIONSHIPS",
                        )
                    )
        elif op == "delete_vertex" and operation.get("cascade", False) is True:
            edge_result = _read_values(f"g.V({_g(target_id)}).bothE().elementMap()")
            if not edge_result.get("ok"):
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        "associated edge preview query failed",
                        "Verify HugeGraph Server is available and retry the dry run.",
                    )
                )
            else:
                item["associated_edges"] = edge_result["data"]["values"]
                # cascade=true currently previews incident edges only and does not
                # perform cascading deletion. This conservative behavior is
                # intentional; real cascading deletion needs separate product
                # decisions and test coverage.
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        "delete_vertex cascade=true is not enabled in this phase",
                        "Delete associated edges explicitly, then delete the vertex with cascade=false.",
                        "CASCADE_NOT_ENABLED",
                    )
                )
        preview.append(item)

    if errors:
        return {
            "valid": False,
            "errors": errors,
            "warnings": validation.get("warnings", []),
            "preview": preview,
        }

    return {
        "valid": True,
        "plan_hash": calculate_graph_change_plan_hash(
            compiled_plan,
            schema_summary=normalized_schema_summary(live_schema),
            extra_hash_context=extra_hash_context,
        ),
        "compiled_plan": compiled_plan,
        "mutation_summary": _mutation_summary(operations),
        "preview": preview,
        "warnings": validation.get("warnings", []),
    }


def _append_edge_endpoint_counts(
    *,
    idx: int,
    operation: dict[str, Any],
    op: str,
    item: dict[str, Any],
    errors: list[ValidationError],
    planned_operations: list[Any] | None = None,
    compiled_operation: dict[str, Any] | None = None,
) -> bool:
    endpoint_failed = False
    for endpoint, endpoint_query in (
        ("source", _source_vertex_match_query(operation)),
        ("target", _target_vertex_match_query(operation)),
    ):
        if compiled_operation is None:
            endpoint_count_result = _read_count(endpoint_query)
            if not endpoint_count_result.get("ok"):
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"{endpoint} endpoint count query failed",
                        "Verify HugeGraph Server is available and retry the dry run.",
                    )
                )
                endpoint_failed = True
                continue
            endpoint_count = endpoint_count_result["data"]["matched_count"]
            item[f"{endpoint}_matched_count"] = endpoint_count
            if endpoint_count != 1:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"{op} {endpoint} endpoint matched_count must be 1, got {endpoint_count}",
                        "Narrow the endpoint match criteria so exactly one vertex is selected.",
                    )
                )
                endpoint_failed = True
            continue

        planned_ids, _has_unbound_planned_match = _planned_endpoint_ids(
            operation=operation,
            endpoint=endpoint,
            planned_operations=planned_operations,
        )
        planned_indexes = _planned_endpoint_indexes(
            operation=operation,
            endpoint=endpoint,
            planned_operations=planned_operations,
        )
        endpoint_id_result = _read_values(f"{endpoint_query}.limit(2).id()")
        if not endpoint_id_result.get("ok"):
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"{endpoint} endpoint id query failed",
                    "Verify HugeGraph Server is available and retry the dry run.",
                )
            )
            endpoint_failed = True
            continue
        live_ids = endpoint_id_result["data"]["values"]
        planned_count = len(planned_indexes)
        live_count = len(live_ids)
        total_count = planned_count + live_count
        item[f"{endpoint}_planned_count"] = planned_count
        item[f"{endpoint}_live_count"] = live_count
        item[f"{endpoint}_matched_count"] = total_count
        if total_count != 1:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"{op} {endpoint} endpoint matched_count must be 1, got {total_count}",
                    "Narrow the endpoint match criteria so exactly one vertex is selected.",
                )
            )
            endpoint_failed = True
            continue

        if planned_indexes:
            dependency_index = planned_indexes[0]
            item[f"{endpoint}_operation_index"] = dependency_index
            compiled_operation[f"{endpoint}_operation_index"] = dependency_index
            if planned_ids:
                # Keep the explicit ID for the one-release legacy executor. The
                # canonical executor still consumes the dependency receipt.
                endpoint_id = planned_ids[0]
                item[f"{endpoint}_id"] = endpoint_id
                compiled_operation[f"{endpoint}_id"] = endpoint_id
        else:
            endpoint_id = live_ids[0]
            item[f"{endpoint}_id"] = endpoint_id
            compiled_operation[f"{endpoint}_id"] = endpoint_id
    return endpoint_failed


def _planned_endpoint_ids(
    *,
    operation: dict[str, Any],
    endpoint: str,
    planned_operations: list[Any] | None,
) -> tuple[list[Any], bool]:
    if not planned_operations:
        return [], False

    if endpoint == "source":
        label = operation.get("source_label") or operation.get("outVLabel")
        match = operation.get("source_match")
    else:
        label = operation.get("target_label") or operation.get("inVLabel")
        match = operation.get("target_match")

    if not isinstance(label, str) or not isinstance(match, dict):
        return [], False

    stable_ids: list[Any] = []
    has_unbound_match = False
    for planned in planned_operations:
        if not isinstance(planned, dict):
            continue
        planned_op = str(planned.get("op") or planned.get("type") or "")
        if planned_op != "create_vertex" or planned.get("label") != label:
            continue
        if _planned_vertex_matches(planned, match):
            planned_id = planned.get("id")
            if planned_id is None or planned_id == "":
                has_unbound_match = True
            else:
                stable_ids.append(planned_id)
    return stable_ids, has_unbound_match


def _planned_endpoint_indexes(
    *,
    operation: dict[str, Any],
    endpoint: str,
    planned_operations: list[Any] | None,
) -> list[int]:
    if not planned_operations:
        return []
    if endpoint == "source":
        label = operation.get("source_label") or operation.get("outVLabel")
        match = operation.get("source_match")
    else:
        label = operation.get("target_label") or operation.get("inVLabel")
        match = operation.get("target_match")
    if not isinstance(label, str) or not isinstance(match, dict):
        return []
    return [
        index
        for index, planned in enumerate(planned_operations)
        if isinstance(planned, dict)
        and str(planned.get("op") or planned.get("type") or "") == "create_vertex"
        and planned.get("label") == label
        and _planned_vertex_matches(planned, match)
    ]


def _planned_vertex_matches(operation: dict[str, Any], match: dict[str, Any]) -> bool:
    for key, value in match.items():
        if key == "id":
            if operation.get("id") != value:
                return False
            continue
        properties = operation.get("properties")
        if not isinstance(properties, dict) or properties.get(key) != value:
            return False
    return bool(match)


# ---- Execute — recheck matched_count before writing ----


def execute_graph_change_plan(
    change_plan: Any,
    live_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行已编译的变更计划。

    delete 操作必须由 dry-run 编译出 target_id，执行阶段不再使用
    可变的属性谓词重新定位目标。
    """
    operations = _operations(change_plan)
    results: list[dict[str, Any]] = []
    for idx, operation in enumerate(operations):
        op = str(operation.get("op") or operation.get("type"))
        if op == "create_vertex":
            conflict = _create_vertex_identity_conflict(
                operation=operation,
                operation_index=idx,
                live_schema=live_schema,
            )
            if conflict is not None:
                return _execution_failure(conflict, operation, idx, results)

        if op == "create_edge":
            missing_ids = [
                endpoint
                for endpoint in ("source", "target")
                if operation.get(f"{endpoint}_id") is None or operation.get(f"{endpoint}_id") == ""
            ]
            if missing_ids:
                return _execution_failure(
                    envelope_err(
                        ErrorType.INVALID_GRAPH_DATA,
                        "create_edge requires dry-run compiled endpoint IDs.",
                        suggestion="Run dry_run again and execute the server-issued compiled plan.",
                        details={
                            "operation_index": idx,
                            "missing_endpoint_ids": missing_ids,
                        },
                    ),
                    operation,
                    idx,
                    results,
                )

        if op in WRITE_OPS:
            target_id = operation.get("target_id")
            if target_id is None or target_id == "":
                return _execution_failure(
                    envelope_err(
                        ErrorType.INVALID_GRAPH_DATA,
                        f"{op} requires a dry-run compiled target_id.",
                        suggestion="Run dry_run again and execute the server-issued compiled plan.",
                        details={"operation_index": idx},
                    ),
                    operation,
                    idx,
                    results,
                )
            target_query = _delete_target_query(operation)
            exists_result = _read_count(target_query)
            if not exists_result.get("ok"):
                return _execution_failure(exists_result, operation, idx, results)
            existing_count = exists_result["data"]["matched_count"]
            if existing_count == 0:
                results.append(
                    {
                        "operation_index": idx,
                        "op": op,
                        "label": operation.get("label"),
                        "target_id": target_id,
                        "status": ApplyStatus.ALREADY_APPLIED.value,
                        "result": None,
                    }
                )
                continue
            if existing_count != 1:
                return _execution_failure(
                    envelope_err(
                        ErrorType.WRITE_CONFLICT,
                        f"{op} compiled target_id resolved to an invalid count.",
                        details={
                            "operation_index": idx,
                            "target_id": target_id,
                            "matched_count": existing_count,
                        },
                    ),
                    operation,
                    idx,
                    results,
                )
            if op == "delete_vertex" and operation.get("cascade", False) is True:
                return _execution_failure(
                    envelope_err(
                        "CASCADE_NOT_ENABLED",
                        "delete_vertex cascade=true is not enabled in this phase.",
                        suggestion="Delete associated edges explicitly, then delete the vertex with cascade=false.",
                        details={"operation_index": idx},
                    ),
                    operation,
                    idx,
                    results,
                )
        write_result = gremlin_tools.execute_gremlin_write(
            _write_query(operation),
            capability=Capability.DATA_WRITE,
        )
        if isinstance(write_result, dict) and write_result.get("ok") is False:
            if write_result.get("error", {}).get("type") in {
                ErrorType.CONNECTION_FAILED.value,
                ErrorType.SERVER_ERROR.value,
                ErrorType.TIMEOUT.value,
            }:
                write_result = _unknown_write_outcome(
                    operation=operation,
                    operation_index=idx,
                    cause=write_result,
                )
            return _execution_failure(write_result, operation, idx, results)
        if isinstance(write_result, dict) and write_result.get("success") is False:
            legacy_error_type = str(write_result.get("error_type", "")).lower()
            if legacy_error_type in {
                "connection_error",
                "server_error",
                "timeout_error",
            }:
                return _execution_failure(
                    _unknown_write_outcome(
                        operation=operation,
                        operation_index=idx,
                        cause=write_result,
                    ),
                    operation,
                    idx,
                    results,
                )
            return _execution_failure(
                envelope_err(
                    ErrorType.CONNECTION_FAILED,
                    "HugeGraph write query failed during graph change execution.",
                    details=write_result,
                    retryable=True,
                ),
                operation,
                idx,
                results,
            )
        if op in {"create_vertex", "create_edge"}:
            affected = _write_affected_count(write_result)
            if affected != 1:
                if affected is not None:
                    return _execution_failure(
                        envelope_err(
                            ErrorType.FLOW_EXECUTION_FAILED,
                            f"{op} execution affected {affected} element(s), expected 1.",
                            retryable=False,
                            details={
                                "status": ApplyStatus.REJECTED.value,
                                "operation_index": idx,
                                "op": op,
                                "affected": affected,
                            },
                        ),
                        operation,
                        idx,
                        results,
                    )
                return _execution_failure(
                    _unknown_write_outcome(
                        operation=operation,
                        operation_index=idx,
                        cause={
                            "reason": "unexpected affected count",
                            "affected": affected,
                        },
                    ),
                    operation,
                    idx,
                    results,
                )
        if op in {"delete_vertex", "delete_edge"}:
            # Recheck immediately after deletion to ensure HugeGraph actually
            # removed the target. This catches silent backend failures and async
            # state anomalies instead of trusting only the write response.
            verify_query = _delete_target_query(operation)
            verify_result = _read_count(verify_query)
            if not verify_result.get("ok"):
                return _execution_failure(
                    _unknown_write_outcome(
                        operation=operation,
                        operation_index=idx,
                        cause=verify_result,
                    ),
                    operation,
                    idx,
                    results,
                )
            if verify_result["data"]["matched_count"] != 0:
                if op == "delete_vertex" and operation.get("cascade", False) is False:
                    edge_count_result = _read_count(f"{verify_query}.bothE()")
                    if not edge_count_result.get("ok"):
                        return _execution_failure(edge_count_result, operation, idx, results)
                    edge_count = edge_count_result["data"]["matched_count"]
                    if edge_count > 0:
                        return _execution_failure(
                            envelope_err(
                                "BLOCKED_BY_RELATIONSHIPS",
                                "delete_vertex cascade=false was blocked by associated edges.",
                                suggestion="Delete associated edges first, then retry the vertex delete.",
                                details={
                                    "operation_index": idx,
                                    "target_id": operation["target_id"],
                                    "associated_edge_count": edge_count,
                                },
                            ),
                            operation,
                            idx,
                            results,
                        )
                    return _execution_failure(
                        envelope_err(
                            ErrorType.WRITE_CONFLICT,
                            "delete_vertex conditional deletion did not remove the target.",
                            suggestion="Inspect the target state and create a new dry-run plan.",
                            details={
                                "operation_index": idx,
                                "target_id": operation["target_id"],
                            },
                        ),
                        operation,
                        idx,
                        results,
                    )
                return _execution_failure(
                    envelope_err(
                        "DELETE_VERIFY_FAILED",
                        f"{op} execution did not remove the matched element.",
                        suggestion="Inspect the graph state and retry after confirming the match criteria.",
                        details={
                            "operation_index": idx,
                            "op": op,
                            "matched_count": verify_result["data"]["matched_count"],
                        },
                    ),
                    operation,
                    idx,
                    results,
                )
        results.append(
            {
                "operation_index": idx,
                "op": op,
                "label": operation.get("label"),
                "status": ApplyStatus.APPLIED.value,
                "result": write_result,
            }
        )
    status = aggregate_plan_status([_result_apply_status(result) for result in results])
    return {
        "success": True,
        "status": status.value,
        "results": results,
        "mutation_summary": _mutation_summary(operations),
    }


def _unknown_write_outcome(
    *,
    operation: dict[str, Any],
    operation_index: int,
    cause: Any,
) -> dict[str, Any]:
    return envelope_err(
        ErrorType.WRITE_OUTCOME_UNKNOWN,
        "The write may have committed; reconcile the target state before retrying.",
        suggestion="Inspect the target by stable identity and do not replay this operation blindly.",
        retryable=False,
        details={
            "status": ApplyStatus.UNKNOWN.value,
            "reconciliation_required": True,
            "operation_index": operation_index,
            "operation": operation,
            "cause": cause,
        },
    )


def _write_affected_count(write_result: Any) -> int | None:
    data = write_result
    if isinstance(write_result, dict) and "ok" in write_result:
        data = write_result.get("data")
    if not isinstance(data, dict):
        return None
    for key in ("affected", "count"):
        if key not in data:
            continue
        try:
            return int(data.get(key))
        except (TypeError, ValueError):
            return None
    return None


def _append_create_vertex_identity_counts(
    *,
    idx: int,
    operation: dict[str, Any],
    item: dict[str, Any],
    errors: list[ValidationError],
    live_schema: dict[str, Any] | None,
) -> None:
    for identity_type, query in _create_vertex_identity_queries(
        operation,
        live_schema,
    ):
        count_result = _read_count(query)
        if not count_result.get("ok"):
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"create_vertex {identity_type} identity count query failed",
                    "Verify HugeGraph Server is available and retry the dry run.",
                )
            )
            continue
        live_count = count_result["data"]["matched_count"]
        item[f"{identity_type}_live_count"] = live_count
        if live_count > 0:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"create_vertex {identity_type} identity already exists in live graph",
                    "Use a new vertex identity or remove the existing vertex before importing.",
                    ErrorType.INVALID_GRAPH_DATA.value,
                )
            )


def _create_vertex_identity_conflict(
    *,
    operation: dict[str, Any],
    operation_index: int,
    live_schema: dict[str, Any] | None,
) -> dict[str, Any] | None:
    for identity_type, query in _create_vertex_identity_queries(
        operation,
        live_schema,
    ):
        count_result = _read_count(query)
        if not count_result.get("ok"):
            return count_result
        live_count = count_result["data"]["matched_count"]
        if live_count > 0:
            return envelope_err(
                ErrorType.INVALID_GRAPH_DATA,
                f"create_vertex {identity_type} identity already exists before execution.",
                details={
                    "operation_index": operation_index,
                    "identity_type": identity_type,
                    "matched_count": live_count,
                },
            )
    return None


def _create_vertex_identity_queries(
    operation: dict[str, Any],
    live_schema: dict[str, Any] | None,
) -> list[tuple[str, str]]:
    label = operation.get("label")
    if not isinstance(label, str) or not label:
        return []

    queries: list[tuple[str, str]] = []
    explicit_id = operation.get("id")
    if explicit_id not in (None, ""):
        queries.append(("id", f"g.V().hasLabel({_g(label)}).hasId({_g(explicit_id)})"))

    primary_keys = _create_vertex_primary_keys(label, live_schema)
    properties = operation.get("properties")
    if (
        primary_keys
        and isinstance(properties, dict)
        and all(pk in properties and properties.get(pk) not in (None, "") for pk in primary_keys)
    ):
        query = f"g.V().hasLabel({_g(label)})" + "".join(f".has({_g(pk)},{_g(properties[pk])})" for pk in primary_keys)
        queries.append(("primary_key", query))

    return queries


def _create_vertex_primary_keys(
    label: str,
    live_schema: dict[str, Any] | None,
) -> list[str]:
    raw_schema = schema_payload(live_schema) or {}
    for vertex_label in raw_schema.get("vertexlabels", []):
        if not isinstance(vertex_label, dict):
            continue
        if vertex_label.get("name") == label:
            return primary_key_names(vertex_label)
    return []


def _execution_failure(
    error_result: dict[str, Any],
    operation: dict[str, Any],
    operation_index: int,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    if not results:
        return error_result

    error = _extract_execution_error(error_result)
    operation_status = _error_apply_status(error)
    plan_status = aggregate_plan_status(
        [
            *(_result_apply_status(result) for result in results),
            operation_status,
        ]
    )
    return {
        "success": False,
        "status": plan_status.value,
        "results": results,
        "failed_items": [
            {
                "operation_index": operation_index,
                "op": operation.get("op") or operation.get("type"),
                "label": operation.get("label"),
                "status": operation_status.value,
                "error": error,
            }
        ],
        "warnings": ["Graph change execution stopped after a partial write."],
        "mutation_summary": _mutation_summary(_operations({"operations": results})),
    }


def _result_apply_status(result: dict[str, Any]) -> ApplyStatus:
    """Return the canonical operation status from an executor result."""

    try:
        return ApplyStatus(result.get("status", ApplyStatus.APPLIED.value))
    except ValueError:
        return ApplyStatus.UNKNOWN


def _error_apply_status(error: dict[str, Any]) -> ApplyStatus:
    """Classify a failed operation from the evidence carried by its error."""

    error_type = error.get("type")
    if error_type == ErrorType.WRITE_OUTCOME_UNKNOWN.value:
        return ApplyStatus.UNKNOWN
    if error_type in {
        ErrorType.WRITE_CONFLICT.value,
        "BLOCKED_BY_RELATIONSHIPS",
    }:
        return ApplyStatus.CONFLICT
    return ApplyStatus.REJECTED


def _extract_execution_error(error_result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(error_result, dict) and isinstance(error_result.get("error"), dict):
        return error_result["error"]
    return {
        "type": ErrorType.CONNECTION_FAILED.value,
        "message": "Graph change execution failed.",
        "details": error_result if isinstance(error_result, dict) else {},
    }


# ---- Fetch live schema ----


def _fetch_live_schema() -> dict[str, Any] | None:
    return fetch_live_schema_or_none()
