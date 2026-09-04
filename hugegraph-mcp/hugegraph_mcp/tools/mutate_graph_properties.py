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

"""Controlled vertex/edge property append/eliminate tool for v2_core."""

from typing import Any
from uuid import uuid4

from pyhugegraph.client import PyHugeClient

from hugegraph_mcp.backend_capabilities import (
    BackendFeature,
    CapabilityEvidence,
    profile_for,
)
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.confirmable_workflow import (
    confirm_required_error,
    mark_readonly_preview,
)
from hugegraph_mcp.envelope import (
    ErrorType,
    envelope_err,
    envelope_ok,
)
from hugegraph_mcp.error_mapping import classify_hugegraph_exception
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.hugegraph_client import build_hugegraph_client
from hugegraph_mcp.plan_hash import (
    build_plan_context,
    compute_payload_digest,
    compute_plan_hash,
)
from hugegraph_mcp.tools.live_schema import current_live_schema
from hugegraph_mcp.tools.property_validation import property_specs, property_value_error
from hugegraph_mcp.tools.schema_utils import (
    normalized_schema_summary,
    property_cardinalities,
    property_names,
    schema_payload,
)
from hugegraph_mcp.write_plan import ApplyStatus, PlanStatus, aggregate_plan_status

TARGETS = frozenset({"vertex", "edge"})
OPERATIONS = frozenset({"append", "eliminate"})


def _graph_manager():
    return build_hugegraph_client(MCPConfig.from_env(), client_cls=PyHugeClient).graph()


def mutate_graph_properties(
    *,
    target: str,
    operation: str,
    id: Any,
    properties: dict[str, Any],
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> dict[str, Any]:
    """Append or eliminate properties on one vertex or edge.

    Capability: DATA_WRITE.

    target values: vertex, edge.
    operation values: append, eliminate. Both operations require:
    dry_run=True first -> review plan_hash/plan_context -> dry_run=False,
    confirm=True, same plan_hash, nonce, and expires_at.

    The dry-run reads live schema and the target object, validates property keys
    against the target label, previews before/after state, and binds a target
    snapshot digest into plan_hash. Applying a confirmed mutation is disabled
    until HugeGraph exposes a backend-enforced conditional property update. The
    current append/eliminate REST endpoints cannot provide atomic compare-and-set.
    """

    validation_error = _validate_inputs(
        target=target,
        operation=operation,
        id=id,
        properties=properties,
    )
    if validation_error is not None:
        return validation_error

    live_schema, target_item, read_error = _read_schema_and_target(target=target, id=id)
    if read_error is not None:
        return read_error

    cardinalities = property_cardinalities(live_schema)
    schema_error = _validate_properties_against_schema(
        target=target,
        target_item=target_item,
        operation=operation,
        properties=properties,
        live_schema=live_schema,
        cardinalities=cardinalities,
    )
    if schema_error is not None:
        return schema_error

    preview = _preview_mutation(
        target=target,
        operation=operation,
        id=id,
        properties=properties,
        before=target_item,
        cardinalities=cardinalities,
    )
    nonce = _nonce_with_snapshot(nonce, preview["target_snapshot_digest"])
    plan_context = _build_mutation_plan_context(
        target=target,
        operation=operation,
        id=id,
        properties=properties,
        live_schema=live_schema,
        target_snapshot_digest=preview["target_snapshot_digest"],
        nonce=nonce,
    )
    plan_hash_value = compute_plan_hash(plan_context)
    payload = {
        "target": target,
        "operation": operation,
        "id": id,
        "properties": properties,
        "mutation_summary": preview["mutation_summary"],
        "risk_level": "high" if operation == "eliminate" else "medium",
        "before": preview["before"],
        "after": preview["after"],
        "plan_hash": plan_hash_value,
        "plan_context": _plan_context_payload(plan_context),
        "status": PlanStatus.ISSUED.value,
        "confirmable": False,
        "cas_request": {
            "target_type": target,
            "target_id": id,
            "expected_properties": preview["before"].get("properties", {}),
            "desired_properties": preview["after"].get("properties", {}),
            "operation_id": f"property-cas:{plan_hash_value[:24]}",
        },
    }

    if dry_run:
        warnings = ["Preview only: HugeGraph does not expose an atomic conditional property update."]
        next_actions = ["Enable confirmation only after the backend provides compare-and-set for property replacement."]
        if MCPConfig.from_env().is_readonly():
            payload, warnings, next_actions = mark_readonly_preview(
                payload,
                warning=(
                    "This dry-run was generated while HUGEGRAPH_MCP_READONLY=true. "
                    "Set HUGEGRAPH_MCP_READONLY=false and rerun dry_run before confirming."
                ),
                next_action="Set HUGEGRAPH_MCP_READONLY=false and rerun dry_run before confirm.",
            )
        return envelope_ok(payload, warnings=warnings, next_actions=next_actions)

    violation = guard(Capability.DATA_WRITE)
    if violation is not None:
        return violation

    if not confirm:
        return confirm_required_error(
            message="Property mutations require confirm=True after dry_run.",
            suggestion=(
                "Run dry_run=True, review the preview, then pass confirm=True with plan_hash, nonce, and expires_at."
            ),
            source="mutate_graph_properties_tool",
        )

    evidence = _property_cas_evidence()
    return envelope_err(
        ErrorType.FEATURE_DISABLED,
        "Confirmed property mutation is disabled because HugeGraph does not expose atomic compare-and-set updates.",
        suggestion=(
            "Add a backend-enforced conditional property replacement API that compares "
            "the expected state and writes the desired state in one atomic operation."
        ),
        source="mutate_graph_properties_tool",
        details={
            "target": target,
            "id": id,
            "status": aggregate_plan_status([ApplyStatus.REJECTED]).value,
            "required_capability": "conditional_property_compare_and_set",
            "backend_capability": BackendFeature.PROPERTY_COMPARE_AND_SET.value,
            "capability_status": evidence.status.value,
            "capability_evidence": evidence.reason,
            "write_attempted": False,
        },
        next_actions=["Keep this plan as a preview; do not retry confirmation until backend CAS is available."],
    )


def _property_cas_evidence() -> CapabilityEvidence:
    """Return the locked capability evidence for the supported deployment."""

    return profile_for("1.7.0", "rocksdb").evidence_for(BackendFeature.PROPERTY_COMPARE_AND_SET)


def _validate_inputs(
    *,
    target: str,
    operation: str,
    id: Any,
    properties: dict[str, Any],
) -> dict[str, Any] | None:
    if target not in TARGETS:
        return _validation_error(
            f"Unsupported target: {target!r}.",
            "Use target='vertex' or target='edge'.",
            {"target": target},
        )
    if operation not in OPERATIONS:
        return _validation_error(
            f"Unsupported operation: {operation!r}.",
            "Use operation='append' or operation='eliminate'.",
            {"operation": operation},
        )
    if id is None or (isinstance(id, str) and id.strip() == ""):
        return _validation_error(
            "id is required for property mutation.",
            "Pass the exact vertex or edge id from query_graph_data_tool.",
            {"id": id},
        )
    if not isinstance(properties, dict) or not properties:
        return _validation_error(
            "properties must be a non-empty object.",
            "Pass the property keys and values to append or eliminate.",
            {"properties_type": type(properties).__name__},
        )
    blank_keys = [key for key in properties if not isinstance(key, str) or not key]
    if blank_keys:
        return _validation_error(
            "properties contains blank or non-string keys.",
            "Use only named schema property keys.",
            {"invalid_keys": blank_keys},
        )
    return None


def _read_schema_and_target(
    *,
    target: str,
    id: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    try:
        live_schema = current_live_schema()
    except Exception as exc:  # noqa: BLE001 - normalize external schema failure
        return (
            None,
            None,
            envelope_err(
                ErrorType.CONNECTION_FAILED,
                "Cannot read live schema before property mutation.",
                suggestion="Ensure HugeGraph Server is running and retry.",
                retryable=True,
                source="mutate_graph_properties_tool",
                details={"stage": "schema_fetch", "error": str(exc)},
            ),
        )

    try:
        manager = _graph_manager()
        raw_item = manager.getVertexById(id) if target == "vertex" else manager.getEdgeById(id)
    except Exception as exc:  # noqa: BLE001 - normalize external graph failure
        classification = classify_hugegraph_exception(exc)
        return (
            live_schema,
            None,
            envelope_err(
                classification.error_type,
                f"Cannot read target {target}: {exc!s}",
                suggestion=classification.suggestion,
                retryable=classification.retryable,
                source="mutate_graph_properties_tool",
                details={
                    "stage": "target_fetch",
                    "target": target,
                    "id": id,
                    "error": str(exc),
                    "reason": classification.reason,
                },
            ),
        )

    item = _plain_item(raw_item)
    if item is None:
        return (
            live_schema,
            None,
            envelope_err(
                ErrorType.NOT_FOUND,
                f"Target {target} not found: {id}",
                suggestion="Call query_graph_data_tool to verify the target id.",
                source="mutate_graph_properties_tool",
                details={"target": target, "id": id},
            ),
        )
    return live_schema, item, None


def _validate_properties_against_schema(
    *,
    target: str,
    target_item: dict[str, Any],
    operation: str,
    properties: dict[str, Any],
    live_schema: dict[str, Any] | None,
    cardinalities: dict[str, str],
) -> dict[str, Any] | None:
    raw_schema = schema_payload(live_schema)
    if raw_schema is None:
        return envelope_err(
            ErrorType.SCHEMA_MISMATCH,
            "Live schema response is not a schema object.",
            source="mutate_graph_properties_tool",
        )

    label = target_item.get("label")
    if not label:
        return envelope_err(
            ErrorType.SCHEMA_MISMATCH,
            "Target item has no label; cannot validate property keys.",
            source="mutate_graph_properties_tool",
            details={"target_item": target_item},
        )
    collection = "vertexlabels" if target == "vertex" else "edgelabels"
    label_schema = _find_label_schema(raw_schema.get(collection), label)
    if label_schema is None:
        return envelope_err(
            ErrorType.SCHEMA_MISMATCH,
            f"Target label is not present in live schema: {label}",
            source="mutate_graph_properties_tool",
            details={"label": label, "target": target},
        )
    allowed = property_names(label_schema.get("properties"))
    unknown = sorted(set(properties) - allowed)
    if unknown:
        return envelope_err(
            ErrorType.SCHEMA_MISMATCH,
            "Property mutation references keys not defined on the target label.",
            suggestion="Use only properties defined on the target vertex or edge label.",
            source="mutate_graph_properties_tool",
            details={"label": label, "unknown_properties": unknown},
        )
    if operation == "append":
        specs = property_specs(live_schema or {})
        for name, value in properties.items():
            spec = specs.get(name)
            value_error = property_value_error(
                item_kind=target,
                item_index=0,
                property_name=name,
                value=value,
                spec=spec,
            )
            if value_error is not None:
                data_type, cardinality = spec or (
                    None,
                    cardinalities.get(name, "SINGLE"),
                )
                suggestion = (
                    f"Pass a JSON array whose elements match {data_type} for {cardinality} property {name!r}."
                    if cardinality in {"LIST", "SET"}
                    else f"Pass a value matching HugeGraph data type {data_type}."
                )
                return _validation_error(
                    value_error,
                    suggestion,
                    {
                        "property": name,
                        "data_type": data_type,
                        "cardinality": cardinality,
                        "value_type": type(value).__name__,
                    },
                )
    return None


def _preview_mutation(
    *,
    target: str,
    operation: str,
    id: Any,
    properties: dict[str, Any],
    before: dict[str, Any],
    cardinalities: dict[str, str],
) -> dict[str, Any]:
    before_properties = dict(before.get("properties") or {})
    after_properties = _apply_property_preview(
        before_properties,
        operation,
        properties,
        cardinalities,
    )
    after = dict(before)
    after["properties"] = after_properties
    return {
        "before": before,
        "after": after,
        "target_snapshot_digest": compute_payload_digest(before),
        "mutation_summary": {
            "target": target,
            "operation": operation,
            "id": id,
            "property_keys": sorted(properties),
        },
    }


def _apply_property_preview(
    before: dict[str, Any],
    operation: str,
    properties: dict[str, Any],
    cardinalities: dict[str, str],
) -> dict[str, Any]:
    after = dict(before)
    if operation == "append":
        for name, value in properties.items():
            cardinality = cardinalities.get(name, "SINGLE")
            if cardinality == "LIST":
                after[name] = [*_existing_collection(after.get(name)), *value]
            elif cardinality == "SET":
                after[name] = _stable_unique([*_existing_collection(after.get(name)), *value])
            else:
                after[name] = value
        return after
    for key in properties:
        after.pop(key, None)
    return after


def _build_mutation_plan_context(
    *,
    target: str,
    operation: str,
    id: Any,
    properties: dict[str, Any],
    live_schema: dict[str, Any] | None,
    target_snapshot_digest: str,
    nonce: str | None,
):
    context, _ = build_plan_context(
        tool_name="mutate_graph_properties_tool",
        mode="mutate",
        payload_digest=_payload_digest(target, operation, id, properties),
        schema_hash=_schema_hash(live_schema),
        nonce=nonce,
        extra_context={
            "target": target,
            "operation": operation,
            "target_snapshot_digest": target_snapshot_digest,
        },
    )
    return context


def _nonce_with_snapshot(nonce: str | None, snapshot_digest: str) -> str:
    base = str(nonce).strip() if nonce else uuid4().hex[:12]
    if "|ts:" in base:
        return base
    return f"{base}|ts:{snapshot_digest[:16]}"


def _payload_digest(
    target: str,
    operation: str,
    id: Any,
    properties: dict[str, Any],
) -> str:
    return compute_payload_digest(
        {
            "target": target,
            "operation": operation,
            "id": id,
            "properties": properties,
        }
    )


def _schema_hash(live_schema: dict[str, Any] | None) -> str | None:
    summary = normalized_schema_summary(live_schema)
    return compute_payload_digest(summary) if summary else None


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


def _find_label_schema(labels: Any, label_name: str) -> dict[str, Any] | None:
    if not isinstance(labels, list):
        return None
    for item in labels:
        if isinstance(item, dict) and item.get("name") == label_name:
            return item
    return None


def _existing_collection(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _stable_unique(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if not any(existing == value for existing in result):
            result.append(value)
    return result


def _plain_item(item: Any) -> dict[str, Any] | None:
    if item is None:
        return None
    if isinstance(item, dict):
        return dict(item)
    result: dict[str, Any] = {}
    for name in (
        "id",
        "label",
        "type",
        "properties",
        "outV",
        "outVLabel",
        "inV",
        "inVLabel",
    ):
        if hasattr(item, name):
            result[name] = getattr(item, name)
    return result or {"value": item}


def _validation_error(
    message: str,
    suggestion: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return envelope_err(
        ErrorType.VALIDATION_ERROR,
        message,
        suggestion=suggestion,
        source="mutate_graph_properties_tool",
        details=details,
    )
