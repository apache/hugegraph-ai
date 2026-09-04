# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0.

"""Compile validated graph changes into the canonical durable write model."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from uuid import uuid4

from hugegraph_mcp.plan_hash import PlanContext
from hugegraph_mcp.tools.graph_data_validate import _operations
from hugegraph_mcp.tools.schema_utils import (
    normalized_schema_summary,
    primary_key_names,
    schema_payload,
)
from hugegraph_mcp.write_plan import (
    GraphTarget,
    OperationPlan,
    PlanStatus,
    WritePlan,
)

CREATE_VERTEX = "CREATE_VERTEX"
CREATE_EDGE = "CREATE_EDGE"
DELETE_VERTEX = "DELETE_VERTEX"
DELETE_EDGE = "DELETE_EDGE"
GRAPH_OPERATION_KINDS = (CREATE_VERTEX, CREATE_EDGE, DELETE_VERTEX, DELETE_EDGE)


def compile_graph_write_plan(
    change_plan: Any,
    *,
    plan_context: PlanContext,
    live_schema: dict[str, Any],
    tool_name: str = "manage_graph_data",
) -> WritePlan:
    """Return an ordered immutable plan from a validated compiled change plan."""

    plan_id = f"wp_{uuid4().hex}"
    operation_ids = [f"{plan_id}:op:{index:04d}" for index, _ in enumerate(_operations(change_plan))]
    canonical_operations: list[OperationPlan] = []
    for index, raw in enumerate(_operations(change_plan)):
        canonical_operations.append(
            _compile_operation(
                raw,
                operation_id=operation_ids[index],
                operation_ids=operation_ids,
                live_schema=live_schema,
            )
        )

    created_at = int(time.time())
    expires_at = max(created_at + 1, int(plan_context.expires_at))
    payload_digest = _digest(change_plan)
    return WritePlan(
        plan_id=plan_id,
        tool_name=tool_name,
        graph_target=GraphTarget(
            graph_url=plan_context.graph_url,
            graph_name=plan_context.graph_name,
            graphspace=plan_context.graphspace,
        ),
        principal=plan_context.principal,
        operations=tuple(canonical_operations),
        payload_digest=payload_digest,
        schema_fingerprint=_digest(normalized_schema_summary(live_schema)),
        status=PlanStatus.ISSUED,
        created_at=created_at,
        expires_at=expires_at,
    )


def _compile_operation(
    raw: dict[str, Any],
    *,
    operation_id: str,
    operation_ids: list[str],
    live_schema: dict[str, Any],
) -> OperationPlan:
    mutation = dict(raw)
    op = str(raw.get("op") or raw.get("type"))
    if op == "create_vertex":
        identity = _vertex_identity(raw, live_schema)
        desired = {
            "exists": True,
            "element_type": "vertex",
            "label": raw["label"],
            "identity": identity,
            "properties": dict(raw.get("properties") or {}),
        }
        return _operation(
            operation_id,
            CREATE_VERTEX,
            {"mutation": mutation, "identity": identity},
            {"exists": False},
            desired,
        )
    if op == "create_edge":
        source, source_dependencies = _endpoint_target(raw, "source", operation_ids)
        target, target_dependencies = _endpoint_target(raw, "target", operation_ids)
        identity_properties = _edge_identity_properties(raw, live_schema)
        desired = {
            "exists": True,
            "element_type": "edge",
            "label": raw["label"],
            "source": source,
            "target": target,
            "identity_properties": identity_properties,
            "properties": dict(raw.get("properties") or {}),
        }
        dependencies = tuple(dict.fromkeys(source_dependencies + target_dependencies))
        return _operation(
            operation_id,
            CREATE_EDGE,
            {
                "mutation": mutation,
                "source": source,
                "target": target,
                "identity_properties": identity_properties,
            },
            {"exists": False},
            desired,
            depends_on=dependencies,
        )
    if op in {"delete_vertex", "delete_edge"}:
        target_id = raw.get("target_id")
        if target_id in (None, ""):
            raise ValueError(f"{op} requires a compiled target_id")
        element_type = "vertex" if op == "delete_vertex" else "edge"
        kind = DELETE_VERTEX if op == "delete_vertex" else DELETE_EDGE
        return _operation(
            operation_id,
            kind,
            {"mutation": mutation, "id": target_id, "label": raw["label"]},
            {
                "exists": True,
                "element_type": element_type,
                "id": target_id,
                "label": raw["label"],
            },
            {"exists": False},
        )
    raise ValueError(f"unsupported graph operation: {op}")


def _operation(
    operation_id: str,
    kind: str,
    target: dict[str, Any],
    expected_state: dict[str, Any],
    desired_state: dict[str, Any],
    *,
    depends_on: tuple[str, ...] = (),
) -> OperationPlan:
    return OperationPlan(
        operation_id=operation_id,
        kind=kind,
        target=target,
        expected_state=expected_state,
        desired_state=desired_state,
        depends_on=depends_on,
        idempotency_key=_digest({"kind": kind, "target": target, "desired_state": desired_state}),
    )


def _endpoint_target(raw: dict[str, Any], endpoint: str, operation_ids: list[str]) -> tuple[dict[str, Any], list[str]]:
    dependency_index = raw.get(f"{endpoint}_operation_index")
    if dependency_index is not None:
        if not isinstance(dependency_index, int) or dependency_index < 0 or dependency_index >= len(operation_ids):
            raise ValueError(f"invalid {endpoint} dependency operation index")
        operation_id = operation_ids[dependency_index]
        return {"operation_id": operation_id}, [operation_id]
    endpoint_id = raw.get(f"{endpoint}_id")
    if endpoint_id in (None, ""):
        raise ValueError(f"create_edge requires compiled {endpoint}_id")
    return {"id": endpoint_id}, []


def _vertex_identity(operation: dict[str, Any], live_schema: dict[str, Any]) -> dict[str, Any]:
    explicit_id = operation.get("id")
    if explicit_id not in (None, ""):
        return {"id": explicit_id}
    label = _vertex_label(live_schema, str(operation["label"]))
    primary_keys = primary_key_names(label) if label is not None else []
    properties = operation.get("properties") or {}
    if not primary_keys or any(key not in properties for key in primary_keys):
        raise ValueError("create_vertex requires a stable ID or complete primary-key identity")
    return {"primary_keys": {key: properties[key] for key in primary_keys}}


def _edge_identity_properties(operation: dict[str, Any], live_schema: dict[str, Any]) -> dict[str, Any]:
    edge_label = _edge_label(live_schema, str(operation["label"]))
    if edge_label is None:
        raise ValueError(f"unknown edge label: {operation['label']}")
    sort_keys = edge_label.get("sort_keys") or edge_label.get("sortKeys") or []
    frequency = str(edge_label.get("frequency") or "SINGLE").upper()
    properties = operation.get("properties") or {}
    if frequency == "MULTIPLE" and not sort_keys:
        raise ValueError("MULTIPLE create_edge requires schema sort keys for stable identity")
    if any(key not in properties for key in sort_keys):
        raise ValueError("create_edge is missing a required sort-key identity value")
    return {key: properties[key] for key in sort_keys}


def _vertex_label(live_schema: dict[str, Any], name: str) -> dict[str, Any] | None:
    schema = schema_payload(live_schema) or {}
    return next(
        (item for item in schema.get("vertexlabels") or [] if isinstance(item, dict) and item.get("name") == name),
        None,
    )


def _edge_label(live_schema: dict[str, Any], name: str) -> dict[str, Any] | None:
    schema = schema_payload(live_schema) or {}
    return next(
        (item for item in schema.get("edgelabels") or [] if isinstance(item, dict) and item.get("name") == name),
        None,
    )


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
