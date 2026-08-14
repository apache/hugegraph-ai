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

"""Graph data change plan execution.

Dry-run preview, write execution, pre-execution matched_count verification,
and plan hash computation.
"""

import hashlib
import json
from typing import Any

from hugegraph_mcp import gremlin_tools
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability
from hugegraph_mcp.tools.graph_data_gremlin import (
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
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return envelope_ok({"values": data if isinstance(data, list) else [data]})


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

    delete 操作通过只读 Gremlin 查询验证 matched_count==1，
    delete_vertex cascade=false 时检查关联边。
    """
    validation = validate_graph_change_plan(change_plan, live_schema)
    if not validation["valid"]:
        return validation

    operations = _operations(change_plan)
    preview: list[dict[str, Any]] = []
    errors: list[ValidationError] = []

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
                planned_operations=operations,
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

        match_query = (
            _edge_match_query(operation)
            if op == "delete_edge"
            else _vertex_match_query(operation)
        )
        count_result = _read_count(match_query)
        if not count_result.get("ok"):
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    "matched_count query failed",
                    "Verify HugeGraph Server is available and retry the dry run.",
                )
            )
            continue
        matched_count = count_result["data"]["matched_count"]
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

        if (
            op == "delete_vertex"
            and operation.get("cascade", False) is False
            and matched_count == 1
        ):
            # By default, refuse to delete vertices with incident edges to avoid
            # unpredictable data loss from HugeGraph-side cascading behavior.
            # Users must explicitly delete the incident edges first.
            edge_count_result = _read_count(f"{match_query}.bothE()")
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
            edge_result = _read_values(f"{match_query}.bothE().elementMap()")
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
            change_plan,
            schema_summary=normalized_schema_summary(live_schema),
            extra_hash_context=extra_hash_context,
        ),
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
) -> bool:
    endpoint_failed = False
    for endpoint, endpoint_query in (
        ("source", _source_vertex_match_query(operation)),
        ("target", _target_vertex_match_query(operation)),
    ):
        planned_count = _planned_endpoint_match_count(
            operation=operation,
            endpoint=endpoint,
            planned_operations=planned_operations,
        )
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
        live_count = endpoint_count_result["data"]["matched_count"]
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
    return endpoint_failed


def _planned_endpoint_match_count(
    *,
    operation: dict[str, Any],
    endpoint: str,
    planned_operations: list[Any] | None,
) -> int:
    if not planned_operations:
        return 0

    if endpoint == "source":
        label = operation.get("source_label") or operation.get("outVLabel")
        match = operation.get("source_match")
    else:
        label = operation.get("target_label") or operation.get("inVLabel")
        match = operation.get("target_match")

    if not isinstance(label, str) or not isinstance(match, dict):
        return 0

    count = 0
    for planned in planned_operations:
        if not isinstance(planned, dict):
            continue
        planned_op = str(planned.get("op") or planned.get("type") or "")
        if planned_op != "create_vertex" or planned.get("label") != label:
            continue
        if _planned_vertex_matches(planned, match):
            count += 1
    return count


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
    """执行变更计划 — 写入前对每个操作再次校验 matched_count。

    防止 dry_run 和 execute 之间状态变化导致的误操作。
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
            for endpoint, endpoint_query in (
                ("source", _source_vertex_match_query(operation)),
                ("target", _target_vertex_match_query(operation)),
            ):
                endpoint_count_result = _read_count(endpoint_query)
                if not endpoint_count_result.get("ok"):
                    return _execution_failure(
                        endpoint_count_result, operation, idx, results
                    )
                endpoint_count = endpoint_count_result["data"]["matched_count"]
                if endpoint_count != 1:
                    return _execution_failure(
                        envelope_err(
                            ErrorType.INVALID_GRAPH_DATA,
                            f"{op} {endpoint} endpoint matched_count must be 1 before execution.",
                            details={
                                "operation_index": idx,
                                "matched_count": endpoint_count,
                            },
                        ),
                        operation,
                        idx,
                        results,
                    )

        if op in WRITE_OPS:
            # Read matched_count again before execution to handle graph changes
            # between dry-run and confirmation. If the match is no longer unique,
            # refuse the write to avoid TOCTOU issues.
            if op == "delete_edge":
                for endpoint, endpoint_query in (
                    ("source", _source_vertex_match_query(operation)),
                    ("target", _target_vertex_match_query(operation)),
                ):
                    endpoint_count_result = _read_count(endpoint_query)
                    if not endpoint_count_result.get("ok"):
                        return _execution_failure(
                            endpoint_count_result, operation, idx, results
                        )
                    endpoint_count = endpoint_count_result["data"]["matched_count"]
                    if endpoint_count != 1:
                        return _execution_failure(
                            envelope_err(
                                ErrorType.INVALID_GRAPH_DATA,
                                f"{op} {endpoint} endpoint matched_count must be 1 before execution.",
                                details={
                                    "operation_index": idx,
                                    "matched_count": endpoint_count,
                                },
                            ),
                            operation,
                            idx,
                            results,
                        )
            match_query = (
                _edge_match_query(operation)
                if op == "delete_edge"
                else _vertex_match_query(operation)
            )
            count_result = _read_count(match_query)
            if not count_result.get("ok"):
                return _execution_failure(count_result, operation, idx, results)
            matched_count = count_result["data"]["matched_count"]
            if matched_count != 1:
                return _execution_failure(
                    envelope_err(
                        ErrorType.INVALID_GRAPH_DATA,
                        f"{op} matched_count must be 1 before execution.",
                        details={
                            "operation_index": idx,
                            "matched_count": matched_count,
                        },
                    ),
                    operation,
                    idx,
                    results,
                )
            if op == "delete_vertex" and operation.get("cascade", False) is False:
                edge_count_result = _read_count(f"{match_query}.bothE()")
                if not edge_count_result.get("ok"):
                    return _execution_failure(
                        edge_count_result, operation, idx, results
                    )
                edge_count = edge_count_result["data"]["matched_count"]
                if edge_count > 0:
                    return _execution_failure(
                        envelope_err(
                            "BLOCKED_BY_RELATIONSHIPS",
                            "delete_vertex cascade=false but vertex has associated edges.",
                            suggestion="Delete associated edges first, then retry the vertex delete.",
                            details={
                                "operation_index": idx,
                                "associated_edge_count": edge_count,
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
            return _execution_failure(write_result, operation, idx, results)
        if isinstance(write_result, dict) and write_result.get("success") is False:
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
                return _execution_failure(
                    envelope_err(
                        ErrorType.FLOW_EXECUTION_FAILED,
                        f"{op} execution affected {affected if affected is not None else 'unknown'} element(s), expected 1.",
                        details={
                            "operation_index": idx,
                            "op": op,
                            "affected": affected,
                            "write_result": write_result,
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
            verify_query = (
                _edge_match_query(operation)
                if op == "delete_edge"
                else _vertex_match_query(operation)
            )
            verify_result = _read_count(verify_query)
            if not verify_result.get("ok"):
                return _execution_failure(verify_result, operation, idx, results)
            if verify_result["data"]["matched_count"] != 0:
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
                "result": write_result,
            }
        )
    return {
        "success": True,
        "results": results,
        "mutation_summary": _mutation_summary(operations),
    }


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
        and all(
            pk in properties and properties.get(pk) not in (None, "")
            for pk in primary_keys
        )
    ):
        query = f"g.V().hasLabel({_g(label)})" + "".join(
            f".has({_g(pk)},{_g(properties[pk])})" for pk in primary_keys
        )
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
    return {
        "success": False,
        "status": "partial",
        "results": results,
        "failed_items": [
            {
                "operation_index": operation_index,
                "op": operation.get("op") or operation.get("type"),
                "label": operation.get("label"),
                "error": error,
            }
        ],
        "warnings": ["Graph change execution stopped after a partial write."],
        "mutation_summary": _mutation_summary(_operations({"operations": results})),
    }


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
