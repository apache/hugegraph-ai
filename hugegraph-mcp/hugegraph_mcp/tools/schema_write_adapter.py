# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0.

"""Canonical plan compiler, executor adapter, and reader for schema creates."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from uuid import uuid4

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.plan_hash import PlanContext
from hugegraph_mcp.tools.schema_utils import normalized_schema_summary
from hugegraph_mcp.write_plan import (
    ApplyReceipt,
    ApplyStatus,
    GraphTarget,
    OperationPlan,
    PlanStatus,
    WritePlan,
)

CREATE_SCHEMA = "CREATE_SCHEMA"


def compile_schema_write_plan(
    operation: dict[str, Any],
    *,
    plan_context: PlanContext,
    live_schema: dict[str, Any],
) -> WritePlan:
    """Compile exactly one validated schema create into an immutable plan."""

    canonical_operation = deepcopy(operation)
    plan_id = f"wp_{uuid4().hex}"
    operation_id = f"{plan_id}:op:0000"
    schema_kind = str(canonical_operation["type"])
    name = str(canonical_operation["name"])
    target = {
        "schema_kind": schema_kind,
        "name": name,
        "operation": canonical_operation,
    }
    desired = {
        "exists": True,
        "schema_kind": schema_kind,
        "name": name,
        "operation": canonical_operation,
    }
    created_at = int(time.time())
    return WritePlan(
        plan_id=plan_id,
        tool_name="apply_schema_tool",
        graph_target=GraphTarget(
            graph_url=plan_context.graph_url,
            graph_name=plan_context.graph_name,
            graphspace=plan_context.graphspace,
        ),
        principal=plan_context.principal,
        operations=(
            OperationPlan(
                operation_id=operation_id,
                kind=CREATE_SCHEMA,
                target=target,
                expected_state={"exists": False},
                desired_state=desired,
                idempotency_key=_digest(target),
            ),
        ),
        payload_digest=_digest({"operations": [canonical_operation]}),
        schema_fingerprint=_digest(normalized_schema_summary(live_schema)),
        status=PlanStatus.ISSUED,
        created_at=created_at,
        expires_at=max(created_at + 1, int(plan_context.expires_at)),
    )


def schema_create_adapter(plan: WritePlan, operation: OperationPlan, attempt: int) -> ApplyReceipt:
    """Execute a persisted schema create through the shared safe boundary."""

    mismatch = _target_mismatch(plan, operation, attempt)
    if mismatch is not None:
        return mismatch
    if guard(Capability.SCHEMA_WRITE) is not None:
        return _receipt(
            plan,
            operation,
            attempt,
            ApplyStatus.REJECTED,
            {"write_allowed": False},
            reason_code="READONLY_VIOLATION",
        )

    # Delayed import prevents a module cycle: manage_schema imports the plan
    # compiler, while the default executor registry imports this adapter.
    from hugegraph_mcp.tools import manage_schema as schema_module

    raw_operation = operation.to_dict()["target"]["operation"]
    live_schema = schema_module.current_live_schema()
    result = schema_module.apply_schema_operations(
        [raw_operation],
        live_schema=live_schema,
    )
    status = ApplyStatus(result["status"])
    return _receipt(
        plan,
        operation,
        attempt,
        status,
        result.get("observed_state"),
        reason_code=_reason_code(status),
        reconciliation_required=status is ApplyStatus.UNKNOWN,
        committed=status is ApplyStatus.APPLIED,
    )


def schema_reconcile_reader(_plan: WritePlan, operation: OperationPlan) -> Mapping[str, Any]:
    """Read one schema object by kind and name without mutating it."""

    from hugegraph_mcp.tools import manage_schema as schema_module

    raw_operation = operation.to_dict()["target"]["operation"]
    state, observed = schema_module._schema_object_state(
        raw_operation,
        schema_module.current_live_schema(),
    )
    if state == "identical":
        return dict(operation.desired_state)
    if state == "missing":
        return dict(operation.expected_state)
    return {
        "exists": True,
        "schema_kind": operation.target["schema_kind"],
        "name": operation.target["name"],
        "conflicting_object": observed or {},
    }


def register_schema_write_adapters(registry: Any) -> None:
    registry.register(CREATE_SCHEMA, schema_create_adapter)


def register_schema_reconcile_readers(registry: Any) -> None:
    registry.register(CREATE_SCHEMA, schema_reconcile_reader)


def _target_mismatch(
    plan: WritePlan,
    operation: OperationPlan,
    attempt: int,
) -> ApplyReceipt | None:
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
    observed_state: Mapping[str, Any] | None,
    *,
    reason_code: str,
    reconciliation_required: bool = False,
    committed: bool = False,
) -> ApplyReceipt:
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


def _reason_code(status: ApplyStatus) -> str:
    return {
        ApplyStatus.APPLIED: "SCHEMA_CREATED",
        ApplyStatus.ALREADY_APPLIED: "SCHEMA_ALREADY_APPLIED",
        ApplyStatus.CONFLICT: "SCHEMA_OBJECT_CONFLICT",
        ApplyStatus.UNKNOWN: "SCHEMA_CREATE_OUTCOME_UNKNOWN",
    }.get(status, status.value)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
