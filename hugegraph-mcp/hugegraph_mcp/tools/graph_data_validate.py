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

"""Graph data change plan validation.

Schema checks, property field validation, primary key match verification.
"""

from typing import Any

from hugegraph_mcp.tools.graph_data_mapping import GraphChangePlan
from hugegraph_mcp.tools.schema_utils import (
    edge_schema_endpoint_label as _edge_schema_endpoint_label,
)
from hugegraph_mcp.tools.schema_utils import (
    normalized_schema_summary,
    schema_name,
    schema_payload,
)
from hugegraph_mcp.tools.schema_utils import (
    primary_key_names as _primary_key_names,
)
from hugegraph_mcp.tools.schema_utils import (
    property_names as _property_names,
)

ALLOWED_OPS = frozenset(
    {
        "create_vertex",
        "create_edge",
        "delete_vertex",
        "delete_edge",
    }
)

VERTEX_OPS = frozenset({"create_vertex", "delete_vertex"})
EDGE_OPS = frozenset({"create_edge", "delete_edge"})
WRITE_OPS = frozenset({"delete_vertex", "delete_edge"})
# Each mode allows only specific operation types to prevent misuse.
MODE_OPS = {
    "import": frozenset({"create_vertex", "create_edge"}),
    "delete": frozenset({"delete_vertex", "delete_edge"}),
}

ValidationError = dict[str, Any]


# ---- Schema helpers ----


def _schema_payload(live_schema: dict[str, Any] | None) -> dict[str, Any]:
    # Keep compatibility with old tests that reference this private helper;
    # the actual implementation is centralized in schema_utils.
    return schema_payload(live_schema) or {}


def _schema_name(item: Any) -> str | None:
    # Support both string and object property representations in HugeGraph schemas.
    return schema_name(item)


def _vertex_labels(raw_schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for label in raw_schema.get("vertexlabels", []):
        if not isinstance(label, dict):
            continue
        name = label.get("name")
        if isinstance(name, str):
            labels[name] = label
    return labels


def _edge_labels(raw_schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for label in raw_schema.get("edgelabels", []):
        if not isinstance(label, dict):
            continue
        name = label.get("name")
        if isinstance(name, str):
            labels[name] = label
    return labels


def _schema_summary(live_schema: dict[str, Any] | None) -> dict[str, Any] | None:
    return normalized_schema_summary(live_schema)


def _operations(change_plan: Any) -> list[Any]:
    if isinstance(change_plan, list):
        return change_plan
    if not isinstance(change_plan, dict):
        return []
    operations = change_plan.get("operations")
    return operations if isinstance(operations, list) else []


def _validation_error(
    operation_index: int,
    operation: Any,
    reason: str,
    suggestion: str,
    error_type: str | None = None,
) -> ValidationError:
    error = {
        "operation_index": operation_index,
        "operation": operation,
        "reason": reason,
        "suggestion": suggestion,
    }
    if error_type is not None:
        error["error_type"] = error_type
    return error


# ---- Validation helpers ----


def _validate_field_map(
    *,
    idx: int,
    operation: dict[str, Any],
    field: str,
    allowed_properties: set[str],
    errors: list[ValidationError],
    allow_id: bool = False,
) -> None:
    values = operation.get(field)
    if values is None:
        return
    if not isinstance(values, dict):
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must be an object",
                f"Use an object mapping property names to values for {field}.",
            )
        )
        return
    allowed = set(allowed_properties)
    if allow_id:
        allowed.add("id")
    unknown = sorted(set(values) - allowed)
    if unknown:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} references property not on label: {', '.join(unknown)}",
                "Use only properties defined on the referenced label.",
            )
        )


def _validate_primary_key_match(
    *,
    idx: int,
    operation: dict[str, Any],
    field: str,
    primary_keys: list[str],
    errors: list[ValidationError],
) -> None:
    match = operation.get(field)
    if not isinstance(match, dict):
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must be an object",
                f"Use {field} to identify a vertex by its primary key.",
            )
        )
        return
    if match.get("id") not in (None, ""):
        return
    missing = [
        pk for pk in primary_keys if pk not in match or match.get(pk) in (None, "")
    ]
    if missing:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must contain primary key(s): {', '.join(missing)}",
                "Include every primary key from the referenced vertex label.",
            )
        )


# ---- Change-plan validation ----


def validate_graph_change_plan(
    change_plan: Any,
    live_schema: dict[str, Any],
) -> dict[str, Any]:
    """校验 change_plan 中的操作是否与 live schema 兼容。

    检查项：op 类型白名单、label 存在性、properties/match 字段合法性、
    主键匹配、边端点合法性。
    """
    errors: list[ValidationError] = []
    warnings: list[str] = []

    if not isinstance(change_plan, (dict, list)):
        return {
            "valid": False,
            "errors": [
                _validation_error(
                    -1,
                    change_plan,
                    "change_plan must be an object with operations",
                    "Pass {'operations': [...]} as the graph change plan.",
                )
            ],
            "warnings": [],
        }

    if isinstance(change_plan, dict) and not isinstance(
        change_plan.get("operations"), list
    ):
        return {
            "valid": False,
            "errors": [
                _validation_error(
                    -1,
                    change_plan,
                    "change_plan.operations must be a list",
                    "Pass graph change operations as a JSON array.",
                )
            ],
            "warnings": [],
        }

    operations = _operations(change_plan)
    raw_schema = _schema_payload(live_schema)
    # Index the live schema by label/name first so each operation uses O(1)
    # lookups, while ensuring validation always uses one schema snapshot.
    vertex_labels = _vertex_labels(raw_schema)
    edge_labels = _edge_labels(raw_schema)
    vertex_properties = {
        label: _property_names(schema.get("properties"))
        for label, schema in vertex_labels.items()
    }
    edge_properties = {
        label: _property_names(schema.get("properties"))
        for label, schema in edge_labels.items()
    }
    primary_keys = {
        label: _primary_key_names(schema) for label, schema in vertex_labels.items()
    }

    for idx, operation in enumerate(operations):
        if not isinstance(operation, dict):
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    "operation must be an object",
                    "Replace this item with a graph change operation object.",
                )
            )
            continue

        op = str(operation.get("op") or operation.get("type") or "")
        if op not in ALLOWED_OPS:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"unsupported op: {op}",
                    "Use one of: create_vertex, create_edge, delete_vertex, delete_edge.",
                )
            )
            continue

        label = operation.get("label")
        if not isinstance(label, str) or not label:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    "missing required field: label",
                    "Add the schema label targeted by this operation.",
                )
            )
            continue

        if "set" in operation:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    "set is not supported by V1 graph data operations",
                    "Use properties for create operations, or submit update support in a later V2 change.",
                )
            )

        if op in VERTEX_OPS:
            if label not in vertex_labels:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"label references undefined vertex label: {label}",
                        "Use an existing vertex label from the live schema.",
                    )
                )
                continue
            allowed = vertex_properties.get(label, set())
            pks = primary_keys.get(label, [])
            if not pks:
                warnings.append(
                    f"operation {idx} references vertex label '{label}' with no primary_keys"
                )
            # properties/match may reference only properties defined for the label.
            # First apply the field allowlist, then enforce stricter op constraints.
            _validate_field_map(
                idx=idx,
                operation=operation,
                field="properties",
                allowed_properties=allowed,
                errors=errors,
            )
            _validate_field_map(
                idx=idx,
                operation=operation,
                field="match",
                allowed_properties=allowed,
                errors=errors,
                allow_id=True,
            )
            if op == "delete_vertex":
                _validate_primary_key_match(
                    idx=idx,
                    operation=operation,
                    field="match",
                    primary_keys=pks,
                    errors=errors,
                )
        else:
            if label not in edge_labels:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"label references undefined edge label: {label}",
                        "Use an existing edge label from the live schema.",
                    )
                )
                continue
            edge_schema = edge_labels[label]
            source_label = operation.get("source_label") or operation.get("outVLabel")
            target_label = operation.get("target_label") or operation.get("inVLabel")
            # Edge operations must satisfy two constraints:
            # 1. The endpoint labels in the request exist.
            # 2. The endpoint direction matches the direction defined by the edge label.
            for endpoint_name, endpoint_label in (
                ("source_label", source_label),
                ("target_label", target_label),
            ):
                if (
                    not isinstance(endpoint_label, str)
                    or endpoint_label not in vertex_labels
                ):
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            f"{endpoint_name} references undefined vertex label: {endpoint_label}",
                            "Use existing source and target vertex labels from the live schema.",
                        )
                    )
            expected_source = _edge_schema_endpoint_label(edge_schema, "source")
            expected_target = _edge_schema_endpoint_label(edge_schema, "target")
            if expected_source and source_label and source_label != expected_source:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"source_label does not match edge label '{label}' source_label '{expected_source}'",
                        "Use the source label defined by the edge schema.",
                    )
                )
            if expected_target and target_label and target_label != expected_target:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"target_label does not match edge label '{label}' target_label '{expected_target}'",
                        "Use the target label defined by the edge schema.",
                    )
                )
            allowed = edge_properties.get(label, set())
            _validate_field_map(
                idx=idx,
                operation=operation,
                field="properties",
                allowed_properties=allowed,
                errors=errors,
            )
            if isinstance(source_label, str) and source_label in vertex_labels:
                _validate_primary_key_match(
                    idx=idx,
                    operation=operation,
                    field="source_match",
                    primary_keys=primary_keys.get(source_label, []),
                    errors=errors,
                )
                _validate_field_map(
                    idx=idx,
                    operation=operation,
                    field="source_match",
                    allowed_properties=vertex_properties.get(source_label, set()),
                    errors=errors,
                    allow_id=True,
                )
            if isinstance(target_label, str) and target_label in vertex_labels:
                _validate_primary_key_match(
                    idx=idx,
                    operation=operation,
                    field="target_match",
                    primary_keys=primary_keys.get(target_label, []),
                    errors=errors,
                )
                _validate_field_map(
                    idx=idx,
                    operation=operation,
                    field="target_match",
                    allowed_properties=vertex_properties.get(target_label, set()),
                    errors=errors,
                    allow_id=True,
                )

    return {"valid": not bool(errors), "errors": errors, "warnings": warnings}


# ---- Mode operation constraints ----


def _validate_mode_operations(
    mode: str, change_plan: GraphChangePlan
) -> dict[str, Any]:
    """确保 mode 下的所有操作类型匹配，例如 import 模式不允许删除。"""
    allowed = MODE_OPS.get(mode)
    if allowed is None:
        return {
            "valid": False,
            "errors": [
                _validation_error(
                    -1,
                    change_plan,
                    f"unknown mode: {mode}",
                    "Use mode='import' or mode='delete'.",
                )
            ],
            "warnings": [],
        }

    errors = []
    for idx, operation in enumerate(_operations(change_plan)):
        if not isinstance(operation, dict):
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    "operation must be an object",
                    "Replace this item with a graph change operation object.",
                )
            )
            continue
        op = str(operation.get("op") or operation.get("type") or "")
        if op not in allowed:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"op {op} is not allowed in mode='{mode}'",
                    f"Use only {', '.join(sorted(allowed))} operations for mode='{mode}'.",
                )
            )
    return {"valid": not bool(errors), "errors": errors, "warnings": []}
