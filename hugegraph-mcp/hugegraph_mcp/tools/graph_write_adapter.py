# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0.

"""Canonical graph write adapters and read-only reconciliation readers."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from hugegraph_mcp import gremlin_tools
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.guard import Capability
from hugegraph_mcp.plan_store import PlanStore, plan_store_from_config
from hugegraph_mcp.tools.graph_data_gremlin import _g, _has_steps, _write_query
from hugegraph_mcp.tools.graph_write_plan import (
    CREATE_EDGE,
    CREATE_VERTEX,
    DELETE_EDGE,
    DELETE_VERTEX,
)
from hugegraph_mcp.write_plan import (
    ApplyReceipt,
    ApplyStatus,
    OperationPlan,
    WritePlan,
)

_AMBIGUOUS_ERRORS = {
    "CONNECTION_FAILED",
    "SERVER_ERROR",
    "TIMEOUT",
    "WRITE_OUTCOME_UNKNOWN",
}


def create_vertex_adapter(plan: WritePlan, operation: OperationPlan, attempt: int) -> ApplyReceipt:
    mismatch = _target_mismatch_receipt(plan, operation, attempt)
    if mismatch is not None:
        return mismatch
    before = _read_vertex(operation)
    classified = _classify_create(before, operation)
    if classified is not ApplyStatus.RETRYABLE_NOT_APPLIED:
        if classified is ApplyStatus.APPLIED:
            classified = ApplyStatus.ALREADY_APPLIED
        return _receipt(plan, operation, attempt, classified, before)

    write_result = gremlin_tools.execute_gremlin_write(
        _write_query(dict(operation.target["mutation"])),
        capability=Capability.DATA_WRITE,
    )
    after = _read_vertex(operation)
    after_status = _classify_create(after, operation)
    if after_status is ApplyStatus.APPLIED:
        return _receipt(
            plan,
            operation,
            attempt,
            ApplyStatus.APPLIED,
            after,
            committed=True,
        )
    return _post_write_receipt(plan, operation, attempt, write_result, after_status, after)


def create_edge_adapter(plan: WritePlan, operation: OperationPlan, attempt: int) -> ApplyReceipt:
    mismatch = _target_mismatch_receipt(plan, operation, attempt)
    if mismatch is not None:
        return mismatch
    source_id = _resolve_endpoint_id(plan, operation, "source")
    target_id = _resolve_endpoint_id(plan, operation, "target")
    endpoint_conflict = _validate_edge_endpoints(operation, source_id, target_id)
    if endpoint_conflict is not None:
        return _receipt(
            plan,
            operation,
            attempt,
            ApplyStatus.CONFLICT,
            endpoint_conflict,
            reason_code="ENDPOINT_STATE_CHANGED",
        )

    before = _read_edge(operation, source_id, target_id)
    classified = _classify_create(before, operation)
    if classified is not ApplyStatus.RETRYABLE_NOT_APPLIED:
        if classified is ApplyStatus.APPLIED:
            classified = ApplyStatus.ALREADY_APPLIED
        return _receipt(plan, operation, attempt, classified, before)

    mutation = dict(operation.target["mutation"])
    mutation["source_id"] = source_id
    mutation["target_id"] = target_id
    write_result = gremlin_tools.execute_gremlin_write(_write_query(mutation), capability=Capability.DATA_WRITE)
    after = _read_edge(operation, source_id, target_id)
    after_status = _classify_create(after, operation)
    if after_status is ApplyStatus.APPLIED:
        observed = dict(after)
        observed["source_id"] = source_id
        observed["target_id"] = target_id
        return _receipt(
            plan,
            operation,
            attempt,
            ApplyStatus.APPLIED,
            observed,
            committed=True,
        )
    return _post_write_receipt(plan, operation, attempt, write_result, after_status, after)


def delete_vertex_adapter(plan: WritePlan, operation: OperationPlan, attempt: int) -> ApplyReceipt:
    return _receipt(
        plan,
        operation,
        attempt,
        ApplyStatus.REJECTED,
        {"capability": "isolated_vertex_delete", "supported": False},
        reason_code="FEATURE_DISABLED",
    )


def delete_edge_adapter(plan: WritePlan, operation: OperationPlan, attempt: int) -> ApplyReceipt:
    return _delete_adapter(plan, operation, attempt)


def _delete_adapter(plan: WritePlan, operation: OperationPlan, attempt: int) -> ApplyReceipt:
    mismatch = _target_mismatch_receipt(plan, operation, attempt)
    if mismatch is not None:
        return mismatch
    before = _read_delete_target(operation)
    if before.get("exists") is False:
        return _receipt(plan, operation, attempt, ApplyStatus.ALREADY_APPLIED, before)
    if before != dict(operation.expected_state):
        return _receipt(
            plan,
            operation,
            attempt,
            ApplyStatus.CONFLICT,
            before,
            reason_code="DELETE_TARGET_CHANGED",
        )
    write_result = gremlin_tools.execute_gremlin_write(
        _write_query(dict(operation.target["mutation"])),
        capability=Capability.DATA_WRITE,
    )
    after = _read_delete_target(operation)
    if after.get("exists") is False:
        return _receipt(
            plan,
            operation,
            attempt,
            ApplyStatus.APPLIED,
            after,
            committed=True,
        )
    return _post_write_receipt(plan, operation, attempt, write_result, ApplyStatus.CONFLICT, after)


def create_vertex_reader(_plan: WritePlan, operation: OperationPlan) -> Mapping[str, Any]:
    return _reconcile_create_state(_read_vertex(operation), operation)


def create_edge_reader(plan: WritePlan, operation: OperationPlan) -> Mapping[str, Any]:
    source_id = _resolve_endpoint_id(plan, operation, "source")
    target_id = _resolve_endpoint_id(plan, operation, "target")
    return _reconcile_create_state(_read_edge(operation, source_id, target_id), operation)


def delete_reader(_plan: WritePlan, operation: OperationPlan) -> Mapping[str, Any]:
    return _read_delete_target(operation)


def register_graph_write_adapters(registry: Any) -> None:
    """Register only operations backed by verified HugeGraph 1.7 primitives."""

    registry.register(DELETE_EDGE, delete_edge_adapter)


def register_graph_reconcile_readers(registry: Any) -> None:
    registry.register(CREATE_VERTEX, create_vertex_reader)
    registry.register(CREATE_EDGE, create_edge_reader)
    registry.register(DELETE_VERTEX, delete_reader)
    registry.register(DELETE_EDGE, delete_reader)


def _read_vertex(operation: OperationPlan) -> dict[str, Any]:
    target = operation.target
    identity = dict(target["identity"])
    query = f"g.V().hasLabel({_g(operation.desired_state['label'])})"
    if "id" in identity:
        query += f".hasId({_g(identity['id'])})"
    else:
        query += _has_steps(dict(identity["primary_keys"]))
    elements = _read_elements(f"{query}.limit(2).elementMap()")
    return _create_observed_state(elements, operation)


def _read_edge(operation: OperationPlan, source_id: Any, target_id: Any) -> dict[str, Any]:
    query = (
        f"g.V({_g(source_id)}).outE({_g(operation.desired_state['label'])})"
        f".where(inV().hasId({_g(target_id)}))"
        f"{_has_steps(dict(operation.target['identity_properties']))}"
        ".limit(2).elementMap()"
    )
    elements = _read_elements(query)
    return _create_observed_state(elements, operation)


def _read_delete_target(operation: OperationPlan) -> dict[str, Any]:
    expected = dict(operation.expected_state)
    prefix = "g.V" if expected["element_type"] == "vertex" else "g.E"
    elements = _read_elements(f"{prefix}({_g(expected['id'])}).limit(2).elementMap()")
    if not elements:
        return {
            "exists": False,
            "element_type": expected["element_type"],
            "id": expected["id"],
            "label": expected["label"],
        }
    if len(elements) != 1:
        return {"exists": True, "ambiguous": True}
    element = _normalize_element(elements[0])
    return {
        "exists": True,
        "element_type": expected["element_type"],
        "id": element.get("id", expected["id"]),
        "label": element.get("label"),
    }


def _create_observed_state(elements: list[Any], operation: OperationPlan) -> dict[str, Any]:
    if not elements:
        return {"exists": False}
    if len(elements) != 1:
        return {"exists": True, "ambiguous": True, "matched_count": len(elements)}
    element = _normalize_element(elements[0])
    desired = dict(operation.desired_state)
    observed_properties = {key: value for key, value in element.items() if key not in {"id", "label"}}
    state: dict[str, Any] = {
        "exists": True,
        "element_type": desired["element_type"],
        "label": element.get("label"),
        "properties": observed_properties,
    }
    if "identity" in desired:
        state["identity"] = dict(desired["identity"])
    if "source" in desired:
        state["source"] = dict(desired["source"])
        state["target"] = dict(desired["target"])
        state["identity_properties"] = dict(desired["identity_properties"])
    if "id" in element:
        state["id"] = element["id"]
    return state


def _classify_create(observed: Mapping[str, Any], operation: OperationPlan) -> ApplyStatus:
    if observed.get("exists") is False:
        return ApplyStatus.RETRYABLE_NOT_APPLIED
    if observed.get("ambiguous"):
        return ApplyStatus.CONFLICT
    desired = dict(operation.desired_state)
    comparable = dict(observed)
    comparable.pop("id", None)
    return ApplyStatus.APPLIED if comparable == desired else ApplyStatus.CONFLICT


def _reconcile_create_state(observed: Mapping[str, Any], operation: OperationPlan) -> Mapping[str, Any]:
    status = _classify_create(observed, operation)
    if status is ApplyStatus.APPLIED:
        return dict(operation.desired_state)
    if status is ApplyStatus.RETRYABLE_NOT_APPLIED:
        return dict(operation.expected_state)
    return dict(observed)


def _validate_edge_endpoints(operation: OperationPlan, source_id: Any, target_id: Any) -> dict[str, Any] | None:
    mutation = operation.target["mutation"]
    checks = (
        ("source", source_id, mutation.get("source_label") or mutation.get("outVLabel")),
        ("target", target_id, mutation.get("target_label") or mutation.get("inVLabel")),
    )
    for endpoint, endpoint_id, label in checks:
        elements = _read_elements(f"g.V({_g(endpoint_id)}).hasLabel({_g(label)}).limit(2).elementMap()")
        if len(elements) != 1:
            return {
                "exists": True,
                "endpoint": endpoint,
                "id": endpoint_id,
                "label": label,
                "matched_count": len(elements),
            }
    return None


def _resolve_endpoint_id(
    plan: WritePlan,
    operation: OperationPlan,
    endpoint: str,
    *,
    store: PlanStore | None = None,
) -> Any:
    endpoint_target = dict(operation.target[endpoint])
    if "id" in endpoint_target:
        return endpoint_target["id"]
    dependency_id = endpoint_target["operation_id"]
    store = store or plan_store_from_config()
    record = store.get_plan_record(plan.plan_id)
    if record is None:
        raise RuntimeError("dependency plan is unavailable")
    dependency = next(
        (item for item in record["operations"] if item["operation_id"] == dependency_id),
        None,
    )
    receipt = dependency.get("receipt") if dependency is not None else None
    observed = receipt.get("observed_state") if isinstance(receipt, dict) else None
    endpoint_id = observed.get("id") if isinstance(observed, dict) else None
    if endpoint_id in (None, ""):
        raise RuntimeError("dependency receipt has no stable vertex ID")
    return endpoint_id


def _read_elements(query: str) -> list[Any]:
    result = gremlin_tools.execute_gremlin_read(query)
    if isinstance(result, dict) and result.get("ok") is False:
        raise RuntimeError(str(result.get("error", {}).get("type") or "READ_FAILED"))
    if isinstance(result, dict) and result.get("success") is False:
        raise RuntimeError(str(result.get("error_type") or "READ_FAILED"))
    value: Any = result.get("data") if isinstance(result, dict) else result
    while isinstance(value, dict) and "data" in value:
        value = value["data"]
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _normalize_element(element: Any) -> dict[str, Any]:
    if not isinstance(element, Mapping):
        return {"value": element}
    normalized: dict[str, Any] = {}
    for raw_key, value in element.items():
        key = str(raw_key)
        lowered = key.lower()
        if lowered in {"id", "t.id", "~id"} or lowered.endswith(" id"):
            normalized["id"] = value
        elif lowered in {"label", "t.label", "~label"} or lowered.endswith(" label"):
            normalized["label"] = value
        else:
            normalized[key] = value
    return normalized


def _post_write_receipt(
    plan: WritePlan,
    operation: OperationPlan,
    attempt: int,
    write_result: Any,
    observed_status: ApplyStatus,
    observed: Mapping[str, Any],
) -> ApplyReceipt:
    write_reported_success = isinstance(write_result, dict) and (
        write_result.get("ok") is True or write_result.get("success") is True
    )
    if (
        observed_status is ApplyStatus.CONFLICT
        and operation.kind in {CREATE_VERTEX, CREATE_EDGE}
        and write_reported_success
    ):
        status = ApplyStatus.UNKNOWN
        reason = "POST_CREATE_IDENTITY_AMBIGUOUS"
    elif observed_status is ApplyStatus.CONFLICT:
        status = ApplyStatus.CONFLICT
        reason = "POST_WRITE_STATE_CONFLICT"
    elif _is_ambiguous_write_result(write_result):
        status = ApplyStatus.UNKNOWN
        reason = "WRITE_RESULT_AMBIGUOUS"
    else:
        status = ApplyStatus.REJECTED
        reason = "WRITE_REJECTED_WITHOUT_SIDE_EFFECT"
    return _receipt(
        plan,
        operation,
        attempt,
        status,
        observed,
        reason_code=reason,
        reconciliation_required=status is ApplyStatus.UNKNOWN,
    )


def _is_ambiguous_write_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return True
    if result.get("ok") is False:
        return str(result.get("error", {}).get("type")) in _AMBIGUOUS_ERRORS
    if result.get("success") is False:
        return str(result.get("error_type", "")).upper() in _AMBIGUOUS_ERRORS
    return False


def _target_mismatch_receipt(plan: WritePlan, operation: OperationPlan, attempt: int) -> ApplyReceipt | None:
    cfg = MCPConfig.from_env()
    current = (cfg.url, cfg.graph, cfg.graphspace or "DEFAULT", cfg.user)
    planned = (
        plan.graph_target.graph_url,
        plan.graph_target.graph_name,
        plan.graph_target.graphspace or "DEFAULT",
        plan.principal,
    )
    if current == planned:
        return None
    return _receipt(
        plan,
        operation,
        attempt,
        ApplyStatus.REJECTED,
        {"target_matches": False},
        reason_code="TARGET_CHANGED",
    )


def _receipt(
    plan: WritePlan,
    operation: OperationPlan,
    attempt: int,
    status: ApplyStatus,
    observed_state: Mapping[str, Any],
    *,
    reason_code: str | None = None,
    reconciliation_required: bool = False,
    committed: bool = False,
) -> ApplyReceipt:
    if reason_code is None:
        reason_code = status.value
    return ApplyReceipt(
        plan_id=plan.plan_id,
        operation_id=operation.operation_id,
        status=status,
        observed_state=observed_state,
        reason_code=reason_code,
        attempt=attempt,
        reconciliation_required=reconciliation_required,
        committed_at=int(time.time()) if committed else None,
    )
