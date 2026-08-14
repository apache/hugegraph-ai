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

"""Schema 管理统一入口 — design / validate / dry_run / apply 模式。

v2_core 解锁最窄 schema apply：create_property_key、create_vertex_label、
create_edge_label。index/rebuild、schema remove/drop、schema append/eliminate
仍不在 P0a 范围内。
"""

from copy import deepcopy
from dataclasses import replace
from typing import Any

from pyhugegraph.client import PyHugeClient

from hugegraph_mcp import schema_tools
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.confirmable_workflow import (
    confirm_required_error,
    issue_plan,
    plan_hash_error,
    replayed_plan_error,
    verify_and_consume_plan,
)
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.hugegraph_client import build_hugegraph_client
from hugegraph_mcp.plan_hash import (
    PlanContext,
    build_plan_context,
    compute_payload_digest,
    compute_plan_hash,
)
from hugegraph_mcp.tools.live_schema import current_live_schema
from hugegraph_mcp.tools.schema_utils import normalized_schema_summary

ALLOWED_OPERATION_TYPES = frozenset(
    {
        "create_property_key",
        "create_vertex_label",
        "create_edge_label",
        "create_index_label",
    }
)
P0A_APPLY_OPERATION_TYPES = frozenset(
    {
        "create_property_key",
        "create_vertex_label",
        "create_edge_label",
    }
)

REQUIRED_FIELDS = {
    "create_property_key": ("name", "data_type"),
    "create_vertex_label": ("name",),
    "create_edge_label": ("name", "source_label", "target_label"),
    "create_index_label": ("name", "base_type", "base_label"),
}

IDENTIFIER_FIELDS = {
    "create_property_key": ("name",),
    "create_vertex_label": ("name",),
    "create_edge_label": ("name", "source_label", "target_label"),
    "create_index_label": ("name", "base_label"),
}

UNSUPPORTED_EDGE_LABEL_FIELDS = frozenset(
    {"parent_label", "parentLabel", "edgelabel_type", "edgeLabelType"}
)

PROPERTY_KEY_DATA_TYPES = frozenset(
    {
        "TEXT",
        "INT",
        "INTEGER",
        "LONG",
        "DOUBLE",
        "FLOAT",
        "BOOLEAN",
        "BOOL",
        "DATE",
        "BYTE",
        "BLOB",
        "OBJECT",
    }
)
PROPERTY_KEY_CARDINALITIES = frozenset({"SINGLE", "SET", "LIST"})
PROPERTY_KEY_AGGREGATE_TYPES = frozenset(
    {"NONE", "OLD", "SUM", "MIN", "MAX", "SET", "LIST"}
)
VERTEX_LABEL_ID_STRATEGIES = frozenset(
    {"PRIMARY_KEY", "CUSTOMIZE_STRING", "CUSTOMIZE_NUMBER", "AUTOMATIC"}
)
EDGE_LABEL_FREQUENCIES = frozenset({"SINGLE", "MULTIPLE"})

PROPERTY_KEY_DATA_TYPE_METHODS = {
    "TEXT": "asText",
    "INT": "asInt",
    "INTEGER": "asInt",
    "LONG": "asLong",
    "DOUBLE": "asDouble",
    "FLOAT": "asFloat",
    "BOOLEAN": "asBool",
    "BOOL": "asBool",
    "DATE": "asDate",
    "BYTE": "asByte",
    "BLOB": "asBlob",
    "OBJECT": "asObject",
}
PROPERTY_KEY_CARDINALITY_METHODS = {
    "SINGLE": "valueSingle",
    "SET": "valueSet",
    "LIST": "valueList",
}
PROPERTY_KEY_AGGREGATE_METHODS = {
    "OLD": "calcOld",
    "SUM": "calcSum",
    "MIN": "calcMin",
    "MAX": "calcMax",
}
PROPERTY_KEY_DIRECT_AGGREGATE_TYPES = frozenset({"NONE", "SET", "LIST"})
PROPERTY_KEY_AGGREGATE_CARDINALITIES = {
    "NONE": frozenset({"SINGLE", "SET", "LIST"}),
    "OLD": frozenset({"SINGLE"}),
    "SUM": frozenset({"SINGLE"}),
    "MIN": frozenset({"SINGLE"}),
    "MAX": frozenset({"SINGLE"}),
    "SET": frozenset({"SET"}),
    "LIST": frozenset({"LIST"}),
}
PROPERTY_KEY_DATA_TYPE_CANONICAL = {
    "INTEGER": "INT",
    "BOOL": "BOOLEAN",
}
VERTEX_LABEL_ID_STRATEGY_METHODS = {
    "PRIMARY_KEY": "usePrimaryKeyId",
    "CUSTOMIZE_STRING": "useCustomizeStringId",
    "CUSTOMIZE_NUMBER": "useCustomizeNumberId",
    "AUTOMATIC": "useAutomaticId",
}
EDGE_LABEL_FREQUENCY_METHODS = {
    "SINGLE": "singleTime",
    "MULTIPLE": "multiTimes",
}


ValidationError = dict[str, Any]


def _operation_type(operation: dict[str, Any]) -> str:
    return str(operation.get("type", ""))


def _is_delete_operation(op_type: str) -> bool:
    lowered = op_type.lower()
    return "delete" in lowered or "drop" in lowered


def _validation_error(
    operation_index: int,
    operation: Any,
    reason: str,
    suggestion: str,
) -> ValidationError:
    return {
        "operation_index": operation_index,
        "operation": operation,
        "reason": reason,
        "suggestion": suggestion,
    }


def _schema_items(live_schema: dict[str, Any], key: str) -> set[str]:
    schema = live_schema.get("schema", {})
    return {
        item.get("name")
        for item in schema.get(key, [])
        if isinstance(item, dict) and item.get("name")
    }


def _collect_planned_creates(
    operations: list[dict[str, Any]],
) -> tuple[dict[str, set[str]], list[ValidationError]]:
    planned = {
        "property_keys": set(),
        "vertex_labels": set(),
        "edge_labels": set(),
        "index_labels": set(),
    }
    errors: list[ValidationError] = []
    create_type_to_key = {
        "create_property_key": "property_keys",
        "create_vertex_label": "vertex_labels",
        "create_edge_label": "edge_labels",
        "create_index_label": "index_labels",
    }
    create_type_to_label = {
        "create_property_key": "property_key",
        "create_vertex_label": "vertex_label",
        "create_edge_label": "edge_label",
        "create_index_label": "index_label",
    }

    for idx, operation in enumerate(operations):
        if not isinstance(operation, dict):
            continue

        op_type = _operation_type(operation)
        planned_key = create_type_to_key.get(op_type)
        if planned_key is None:
            continue

        name = operation.get("name")
        if not name:
            continue

        if name in planned[planned_key]:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"duplicate {op_type} name {name} within the same batch",
                    (
                        f"Define each {create_type_to_label[op_type]} only once "
                        "per schema operation batch."
                    ),
                )
            )
            continue

        planned[planned_key].add(name)

    return planned, errors


def _validate_property_references(
    *,
    idx: int,
    operation: dict[str, Any],
    field: str,
    property_keys: set[str],
    errors: list[ValidationError],
) -> None:
    values = operation.get(field, [])
    if values in (None, ""):
        return
    if not isinstance(values, list):
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must be a list",
                f"Use an array of existing property key names for {field}.",
            )
        )
        return

    invalid_names = _invalid_schema_names(values)
    if invalid_names:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must contain non-empty string names",
                f"Use only non-empty schema property key names for {field}.",
            )
        )
        return

    duplicate_names = _duplicate_names(values)
    if duplicate_names:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} contains duplicate name(s): {', '.join(duplicate_names)}",
                f"Remove duplicate property key names from {field}.",
            )
        )
        return

    missing_properties = [name for name in values if name not in property_keys]
    if missing_properties:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} references undefined property key(s): {', '.join(missing_properties)}",
                "Create these property keys first and rerun validation after they exist in the live schema.",
            )
        )


def _validate_property_subset_references(
    *,
    idx: int,
    operation: dict[str, Any],
    field: str,
    property_keys: set[str],
    errors: list[ValidationError],
) -> None:
    values = operation.get(field)
    if values is None:
        return
    if not isinstance(values, list):
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must be a list",
                f"Use an array of existing property key names for {field}.",
            )
        )
        return

    if not values:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must be a non-empty list",
                f"Use one or more existing property key names for {field}.",
            )
        )
        return

    invalid_names = _invalid_schema_names(values)
    if invalid_names:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must contain non-empty string names",
                f"Use only non-empty schema property key names for {field}.",
            )
        )
        return

    duplicate_names = _duplicate_names(values)
    if duplicate_names:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} contains duplicate name(s): {', '.join(duplicate_names)}",
                f"Remove duplicate property key names from {field}.",
            )
        )
        return

    missing_properties = [name for name in values if name not in property_keys]
    if missing_properties:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} references undefined property key(s): {', '.join(missing_properties)}",
                "Create these property keys first and rerun validation after they exist in the live schema.",
            )
        )

    properties = operation.get("properties") or []
    if not isinstance(properties, list):
        return

    missing_from_label = [name for name in values if name not in properties]
    if missing_from_label:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must be included in properties: {', '.join(missing_from_label)}",
                f"Add each {field} entry to properties before using it in {field}.",
            )
        )


def _validate_enum_field(
    *,
    idx: int,
    operation: dict[str, Any],
    field: str,
    allowed_values: frozenset[str],
    errors: list[ValidationError],
    required: bool,
    default: str | None = None,
) -> str | None:
    raw_value = operation.get(field)
    if raw_value in (None, ""):
        if default is not None:
            return default
        if not required:
            return None

    if not isinstance(raw_value, str):
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must be a string, got {type(raw_value).__name__}",
                f"Use one of: {', '.join(sorted(allowed_values))} for {field}.",
            )
        )
        return None

    normalized = raw_value.upper()
    if normalized not in allowed_values:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"unsupported {field}: {raw_value!r}",
                f"Use one of: {', '.join(sorted(allowed_values))} for {field}.",
            )
        )
        return None

    return _canonical_enum_value(field, normalized)


def _validate_property_key_aggregate_cardinality(
    *,
    idx: int,
    operation: dict[str, Any],
    cardinality: str | None,
    aggregate_type: str | None,
    errors: list[ValidationError],
) -> None:
    if aggregate_type is None:
        return
    allowed_cardinalities = PROPERTY_KEY_AGGREGATE_CARDINALITIES.get(aggregate_type)
    if allowed_cardinalities is None or cardinality in allowed_cardinalities:
        return
    errors.append(
        _validation_error(
            idx,
            operation,
            (
                f"aggregate_type {aggregate_type!r} is not allowed with "
                f"cardinality {cardinality!r}"
            ),
            (
                f"Use cardinality in {sorted(allowed_cardinalities)} for "
                f"aggregate_type {aggregate_type!r}."
            ),
        )
    )


def _validate_identifier_field(
    *,
    idx: int,
    operation: dict[str, Any],
    field: str,
    errors: list[ValidationError],
) -> bool:
    value = operation.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(
            _validation_error(
                idx,
                operation,
                f"{field} must be a non-empty string, got {value!r}",
                f"Provide {field} as a non-empty string identifier.",
            )
        )
        return False
    return True


def _validate_vertex_primary_keys(
    *,
    idx: int,
    operation: dict[str, Any],
    id_strategy: str | None,
    property_keys: set[str],
    errors: list[ValidationError],
) -> None:
    if id_strategy is None:
        return
    if id_strategy != "PRIMARY_KEY":
        return

    primary_keys = operation.get("primary_keys")
    if not primary_keys:
        errors.append(
            _validation_error(
                idx,
                operation,
                "primary_keys is required when id_strategy is PRIMARY_KEY",
                "Add non-empty primary_keys or set id_strategy to AUTOMATIC/CUSTOMIZE_STRING/CUSTOMIZE_NUMBER.",
            )
        )
        return

    if not isinstance(primary_keys, list):
        errors.append(
            _validation_error(
                idx,
                operation,
                "primary_keys must be a list",
                "Use an array of property key names for primary_keys.",
            )
        )
        return

    invalid_names = _invalid_schema_names(primary_keys)
    if invalid_names:
        errors.append(
            _validation_error(
                idx,
                operation,
                "primary_keys must contain non-empty string names",
                "Use only non-empty property key names for primary_keys.",
            )
        )
        return

    duplicate_names = _duplicate_names(primary_keys)
    if duplicate_names:
        errors.append(
            _validation_error(
                idx,
                operation,
                f"primary_keys contains duplicate name(s): {', '.join(duplicate_names)}",
                "Remove duplicate names from primary_keys.",
            )
        )
        return

    properties = operation.get("properties") or []
    if not isinstance(properties, list):
        return

    missing_from_properties = [name for name in primary_keys if name not in properties]
    if missing_from_properties:
        errors.append(
            _validation_error(
                idx,
                operation,
                "primary_keys must be included in properties: "
                + ", ".join(missing_from_properties),
                "Add each primary key to properties before using it as a primary key.",
            )
        )

    missing_property_keys = [name for name in primary_keys if name not in property_keys]
    if missing_property_keys:
        errors.append(
            _validation_error(
                idx,
                operation,
                "primary_keys references undefined property key(s): "
                + ", ".join(missing_property_keys),
                "Create these property keys first and rerun validation after they exist in the live schema.",
            )
        )


def _invalid_schema_names(values: list[Any]) -> list[Any]:
    return [value for value in values if not isinstance(value, str) or not value]


def _duplicate_names(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _validation_warnings(operations: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for idx, operation in enumerate(operations):
        if not isinstance(operation, dict):
            continue
        id_strategy = str(operation.get("id_strategy", "PRIMARY_KEY")).upper()
        if (
            operation.get("type") == "create_vertex_label"
            and id_strategy != "PRIMARY_KEY"
            and not operation.get("primary_keys")
        ):
            warnings.append(
                f"operation {idx} (create_vertex_label) has no primary_keys definition"
            )
    return warnings


def validate_schema_operations(
    operations: list[dict[str, Any]], live_schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    """校验 schema 操作与 live schema 的兼容性。

    检查操作类型白名单、必填字段、property key 存在性、
    边端点 label 存在性、索引 base_label 存在性、重复定义检测。
    """
    errors: list[ValidationError] = []

    if not isinstance(operations, list):
        return {
            "valid": False,
            "errors": [
                _validation_error(
                    -1,
                    operations,
                    "operations must be a list",
                    "Pass schema operations as a JSON array.",
                )
            ],
            "warnings": [],
        }

    live_schema = current_live_schema(live_schema)
    live_property_keys = _schema_items(live_schema, "propertykeys")
    live_vertex_labels = _schema_items(live_schema, "vertexlabels")
    live_edge_labels = _schema_items(live_schema, "edgelabels")
    live_index_labels = _schema_items(live_schema, "indexlabels")
    planned_creates, duplicate_errors = _collect_planned_creates(operations)
    errors.extend(duplicate_errors)

    # Validation mirrors apply order: an operation may reference live schema and
    # earlier creates in the same batch, but not later creates that would fail at
    # apply time and potentially leave a partial schema behind.
    available_property_keys = set(live_property_keys)
    available_vertex_labels = set(live_vertex_labels)
    available_edge_labels = set(live_edge_labels)

    for idx, operation in enumerate(operations):
        if not isinstance(operation, dict):
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    "operation must be an object",
                    "Replace this item with a schema operation object.",
                )
            )
            continue

        op_type = _operation_type(operation)
        if _is_delete_operation(op_type):
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"unsupported delete/drop type: {op_type}",
                    "Use create-only schema operations; destructive schema changes are not supported.",
                )
            )
            continue

        if op_type not in ALLOWED_OPERATION_TYPES:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"unsupported type: {op_type}",
                    "Use one of: create_property_key, create_vertex_label, create_edge_label, create_index_label.",
                )
            )
            continue

        for field in REQUIRED_FIELDS[op_type]:
            if field not in operation or operation[field] in (None, ""):
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"missing required field: {field}",
                        f"Add {field} to the {op_type} operation.",
                    )
                )
        if any(
            field not in operation or operation[field] in (None, "")
            for field in REQUIRED_FIELDS[op_type]
        ):
            continue

        identifier_ok = all(
            _validate_identifier_field(
                idx=idx, operation=operation, field=field, errors=errors
            )
            for field in IDENTIFIER_FIELDS.get(op_type, ())
        )
        if not identifier_ok:
            continue

        name = operation.get("name")
        if op_type == "create_property_key":
            if name in live_property_keys:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"property key already exists: {name}",
                        "Use a new property key name or remove this create_property_key operation.",
                    )
                )
            _validate_enum_field(
                idx=idx,
                operation=operation,
                field="data_type",
                allowed_values=PROPERTY_KEY_DATA_TYPES,
                errors=errors,
                required=True,
                default="TEXT",
            )
            cardinality = _validate_enum_field(
                idx=idx,
                operation=operation,
                field="cardinality",
                allowed_values=PROPERTY_KEY_CARDINALITIES,
                errors=errors,
                required=False,
                default="SINGLE",
            )
            aggregate_type = None
            if operation.get("aggregate_type") not in (None, ""):
                aggregate_type = _validate_enum_field(
                    idx=idx,
                    operation=operation,
                    field="aggregate_type",
                    allowed_values=PROPERTY_KEY_AGGREGATE_TYPES,
                    errors=errors,
                    required=False,
                )
            _validate_property_key_aggregate_cardinality(
                idx=idx,
                operation=operation,
                cardinality=cardinality,
                aggregate_type=aggregate_type,
                errors=errors,
            )
        elif op_type == "create_vertex_label":
            if name in live_vertex_labels:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"vertex label already exists: {name}",
                        "Use a new vertex label name or remove this create_vertex_label operation.",
                    )
                )
            id_strategy = _validate_enum_field(
                idx=idx,
                operation=operation,
                field="id_strategy",
                allowed_values=VERTEX_LABEL_ID_STRATEGIES,
                errors=errors,
                required=False,
                default="PRIMARY_KEY",
            )
            _validate_property_references(
                idx=idx,
                operation=operation,
                field="properties",
                property_keys=available_property_keys,
                errors=errors,
            )
            _validate_vertex_primary_keys(
                idx=idx,
                operation=operation,
                id_strategy=id_strategy,
                property_keys=available_property_keys,
                errors=errors,
            )
            _validate_property_subset_references(
                idx=idx,
                operation=operation,
                field="nullable_keys",
                property_keys=available_property_keys,
                errors=errors,
            )
        elif op_type == "create_edge_label":
            if name in live_edge_labels:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"edge label already exists: {name}",
                        "Use a new edge label name or remove this create_edge_label operation.",
                    )
                )
            unsupported_fields = sorted(
                field for field in UNSUPPORTED_EDGE_LABEL_FIELDS if field in operation
            )
            if unsupported_fields:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        (
                            "unsupported parent/sub edge label field(s): "
                            f"{', '.join(unsupported_fields)}"
                        ),
                        (
                            "Parent/sub edge labels are not supported by manage_schema; "
                            "remove these fields."
                        ),
                    )
                )
            for field in ("source_label", "target_label"):
                label = operation[field]
                if label not in available_vertex_labels:
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            f"{field} references undefined vertex label: {label}",
                            "Create the referenced vertex label first and rerun validation after it exists in the live schema.",
                        )
                    )
            if operation.get("frequency") not in (None, ""):
                _validate_enum_field(
                    idx=idx,
                    operation=operation,
                    field="frequency",
                    allowed_values=EDGE_LABEL_FREQUENCIES,
                    errors=errors,
                    required=False,
                )
            _validate_property_references(
                idx=idx,
                operation=operation,
                field="properties",
                property_keys=available_property_keys,
                errors=errors,
            )
            _validate_property_subset_references(
                idx=idx,
                operation=operation,
                field="nullable_keys",
                property_keys=available_property_keys,
                errors=errors,
            )
            _validate_property_subset_references(
                idx=idx,
                operation=operation,
                field="sort_keys",
                property_keys=available_property_keys,
                errors=errors,
            )
        elif op_type == "create_index_label":
            if name in live_index_labels:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"index label already exists: {name}",
                        "Use a new index label name or remove this create_index_label operation.",
                    )
                )
            base_type = str(operation.get("base_type", "")).upper()
            base_label = operation["base_label"]
            if base_type == "VERTEX":
                if base_label not in available_vertex_labels:
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            f"base_label references undefined vertex label: {base_label}",
                            "Create the referenced vertex label first and rerun validation after it exists in the live schema.",
                        )
                    )
            elif base_type == "EDGE":
                if base_label not in available_edge_labels:
                    errors.append(
                        _validation_error(
                            idx,
                            operation,
                            f"base_label references undefined edge label: {base_label}",
                            "Create the referenced edge label first and rerun validation after it exists in the live schema.",
                        )
                    )
            else:
                errors.append(
                    _validation_error(
                        idx,
                        operation,
                        f"unsupported base_type for index label: {base_type}",
                        "Use base_type='VERTEX' or base_type='EDGE'.",
                    )
                )
            _validate_property_references(
                idx=idx,
                operation=operation,
                field="fields",
                property_keys=available_property_keys,
                errors=errors,
            )

        if (
            op_type == "create_property_key"
            and name in planned_creates["property_keys"]
        ):
            available_property_keys.add(name)
        elif (
            op_type == "create_vertex_label"
            and name in planned_creates["vertex_labels"]
        ):
            available_vertex_labels.add(name)
        elif op_type == "create_edge_label" and name in planned_creates["edge_labels"]:
            available_edge_labels.add(name)

    return {
        "valid": not bool(errors),
        "errors": errors,
        "warnings": _validation_warnings(operations),
    }


def _schema_summary(live_schema: dict[str, Any] | None) -> dict[str, Any] | None:
    return normalized_schema_summary(live_schema)


def _schema_hash(live_schema: dict[str, Any] | None) -> str | None:
    summary = _schema_summary(live_schema)
    return compute_payload_digest(summary) if summary else None


def _schema_payload_digest(operations: list[dict[str, Any]]) -> str:
    return compute_payload_digest({"operations": deepcopy(operations)})


def _build_schema_plan_context(
    *,
    operations: list[dict[str, Any]],
    live_schema: dict[str, Any] | None,
    nonce: str | None,
) -> PlanContext:
    live_schema = current_live_schema(live_schema)
    context, _ = build_plan_context(
        tool_name="apply_schema_tool",
        mode="apply",
        payload_digest=_schema_payload_digest(operations),
        schema_hash=_schema_hash(live_schema),
        nonce=nonce,
    )
    return context


def calculate_plan_hash(
    operations: list[dict[str, Any]], live_schema: dict[str, Any] | None = None
) -> str:
    """Compatibility wrapper backed by the unified target-bound PlanContext."""

    return compute_plan_hash(
        _build_schema_plan_context(
            operations=operations,
            live_schema=live_schema,
            nonce="compat",
        )
    )


def _plan_context_payload(plan_context: PlanContext) -> dict[str, Any]:
    return {
        "nonce": plan_context.nonce,
        "expires_at": plan_context.expires_at,
        "graph_url": plan_context.graph_url,
        "graph_name": plan_context.graph_name,
        "graphspace": plan_context.graphspace,
        "principal": plan_context.principal,
        "readonly": plan_context.readonly,
    }


def _risk_warnings(
    operations: list[dict[str, Any]], live_schema: dict[str, Any] | None = None
) -> list[str]:
    warnings: list[str] = []
    live_schema = current_live_schema(live_schema)
    property_keys = _schema_items(live_schema, "propertykeys")
    vertex_labels = _schema_items(live_schema, "vertexlabels")
    edge_labels = _schema_items(live_schema, "edgelabels")
    index_labels = _schema_items(live_schema, "indexlabels")
    planned_creates, _ = _collect_planned_creates(operations)

    created_vertex_labels = planned_creates["vertex_labels"]
    created_edge_labels = planned_creates["edge_labels"]
    indexed_labels = {
        op.get("base_label")
        for op in operations
        if op.get("type") == "create_index_label" and op.get("base_label")
    }

    for operation in operations:
        op_type = operation.get("type")
        name = operation.get("name")
        if op_type == "create_property_key" and name in property_keys:
            warnings.append(f"property key already exists: {name}")
        elif op_type == "create_vertex_label" and name in vertex_labels:
            warnings.append(f"vertex label already exists: {name}")
        elif op_type == "create_edge_label" and name in edge_labels:
            warnings.append(f"edge label already exists: {name}")
        elif op_type == "create_index_label" and name in index_labels:
            warnings.append(f"index label already exists: {name}")

    for label in created_vertex_labels | created_edge_labels:
        if label not in indexed_labels:
            warnings.append(f"no index operation included for label: {label}")

    return warnings


def _validate_apply_scope(operations: list[dict[str, Any]]) -> list[ValidationError]:
    errors: list[ValidationError] = []
    for idx, operation in enumerate(operations):
        if not isinstance(operation, dict):
            continue
        op_type = _operation_type(operation)
        if op_type not in P0A_APPLY_OPERATION_TYPES:
            errors.append(
                _validation_error(
                    idx,
                    operation,
                    f"schema apply operation is outside P0a scope: {op_type}",
                    (
                        "P0a apply supports only create_property_key, "
                        "create_vertex_label, and create_edge_label. "
                        "Index/rebuild and destructive schema changes are out of scope."
                    ),
                )
            )
    return errors


def _mutation_summary(operations: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for operation in operations:
        op_type = operation.get("type", "unknown")
        counts[op_type] = counts.get(op_type, 0) + 1

    if not counts:
        return "No schema operations planned."

    parts = [f"{op_type}={count}" for op_type, count in sorted(counts.items())]
    return "Schema operations planned: " + ", ".join(parts)


def _safe_fetch_live_schema() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        return current_live_schema(), None
    except Exception as exc:  # noqa: BLE001 - return structured schema error
        return None, envelope_err(
            ErrorType.CONNECTION_FAILED,
            "Cannot read live schema from HugeGraph Server for schema validation.",
            suggestion=(
                "Ensure HugeGraph Server is running and credentials/graphspace are "
                "correct, then retry."
            ),
            retryable=True,
            details={"stage": "schema_fetch", "error": str(exc)},
        )


def dry_run_schema_operations(
    operations: list[dict[str, Any]],
    live_schema: dict[str, Any] | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    live_schema = current_live_schema(live_schema)
    validation = validate_schema_operations(operations, live_schema)
    if not validation["valid"]:
        return validation
    apply_scope_errors = _validate_apply_scope(operations)
    if apply_scope_errors:
        return {
            "valid": False,
            "errors": apply_scope_errors,
            "warnings": validation.get("warnings", []),
        }

    plan_context = _build_schema_plan_context(
        operations=operations,
        live_schema=live_schema,
        nonce=nonce,
    )

    return {
        "valid": True,
        "plan_hash": compute_plan_hash(plan_context),
        "plan_context": _plan_context_payload(plan_context),
        "confirmable": True,
        "mutation_summary": _mutation_summary(operations),
        "warnings": validation.get("warnings", [])
        + _risk_warnings(operations, live_schema),
    }


def _design_from_operations(operations: list[dict[str, Any]]) -> dict[str, Any]:
    params = operations[0] if operations else {}
    return schema_tools.design_schema(
        thought=params.get("thought", ""),
        thought_number=params.get("thought_number", 1),
        total_thoughts=params.get("total_thoughts", 4),
        next_thought_needed=params.get("next_thought_needed", True),
        is_revision=params.get("is_revision", False),
        revision_of=params.get("revision_of"),
    )


def _schema_manager():
    return build_hugegraph_client(
        MCPConfig.from_env(), client_cls=PyHugeClient
    ).schema()


def apply_schema_operations(
    operations: list[dict[str, Any]],
    *,
    live_schema: dict[str, Any],
    stop_on_first_error: bool = True,
) -> dict[str, Any]:
    """Apply P0a create operations and verify each operation by post-read schema."""

    manager = _schema_manager()
    applied_operations: list[dict[str, Any]] = []
    operation_results: list[dict[str, Any]] = []

    for idx, operation in enumerate(operations):
        try:
            _apply_one_operation(manager, operation)
            observed_schema = current_live_schema()
        except Exception as exc:  # noqa: BLE001 - preserve partial-apply result
            return _partial_apply_result(
                operations=operations,
                applied_operations=applied_operations,
                operation_results=operation_results,
                failed_operation=operation,
                failed_operation_index=idx,
                error=str(exc),
            )

        if not _operation_observed(operation, observed_schema):
            failed = _partial_apply_result(
                operations=operations,
                applied_operations=applied_operations,
                operation_results=operation_results,
                failed_operation=operation,
                failed_operation_index=idx,
                error="post-read schema did not contain the created object",
            )
            if stop_on_first_error:
                return failed

        applied_operations.append(operation)
        operation_results.append(
            {
                "operation_index": idx,
                "operation": operation,
                "status": "applied",
            }
        )
        live_schema = observed_schema

    return {
        "status": "applied",
        "valid": True,
        "applied_operations": applied_operations,
        "operation_results": operation_results,
        "mutation_summary": _mutation_summary(applied_operations),
        "schema_summary": normalized_schema_summary(live_schema),
    }


def _apply_one_operation(manager, operation: dict[str, Any]) -> None:
    op_type = _operation_type(operation)
    if op_type == "create_property_key":
        builder = manager.propertyKey(operation["name"])
        _apply_property_key_options(builder, operation)
        builder.create()
        return
    if op_type == "create_vertex_label":
        builder = manager.vertexLabel(operation["name"])
        _apply_vertex_label_options(builder, operation)
        builder.create()
        return
    if op_type == "create_edge_label":
        builder = manager.edgeLabel(operation["name"])
        _apply_edge_label_options(builder, operation)
        builder.create()
        return
    raise ValueError(f"Unsupported P0a schema apply operation: {op_type}")


def _apply_property_key_options(builder, operation: dict[str, Any]) -> None:
    data_type = str(operation.get("data_type", "TEXT")).upper()
    method_name = PROPERTY_KEY_DATA_TYPE_METHODS.get(data_type)
    if method_name is None:
        raise ValueError(f"Unsupported property key data_type: {data_type}")
    getattr(builder, method_name)()

    cardinality = str(operation.get("cardinality", "SINGLE")).upper()
    method_name = PROPERTY_KEY_CARDINALITY_METHODS.get(cardinality)
    if method_name is None:
        raise ValueError(f"Unsupported property key cardinality: {cardinality}")
    getattr(builder, method_name)()

    aggregate_type = operation.get("aggregate_type")
    if aggregate_type:
        normalized = str(aggregate_type).upper()
        if normalized in PROPERTY_KEY_DIRECT_AGGREGATE_TYPES:
            if not hasattr(builder, "add_parameter"):
                raise ValueError(
                    f"Property key aggregate_type {normalized} requires a builder "
                    "that supports direct schema parameters."
                )
            builder.add_parameter("aggregate_type", normalized)
            return

        method_name = PROPERTY_KEY_AGGREGATE_METHODS.get(normalized)
        if method_name is None:
            raise ValueError(
                f"Unsupported property key aggregate_type: {aggregate_type}"
            )
        getattr(builder, method_name)()


def _apply_vertex_label_options(builder, operation: dict[str, Any]) -> None:
    id_strategy = str(operation.get("id_strategy", "PRIMARY_KEY")).upper()
    method_name = VERTEX_LABEL_ID_STRATEGY_METHODS.get(id_strategy)
    if method_name is None:
        raise ValueError(f"Unsupported vertex label id_strategy: {id_strategy}")
    getattr(builder, method_name)()

    if operation.get("properties"):
        builder.properties(*operation["properties"])
    if operation.get("primary_keys"):
        builder.primaryKeys(*operation["primary_keys"])
    if operation.get("nullable_keys"):
        builder.nullableKeys(*operation["nullable_keys"])


def _apply_edge_label_options(builder, operation: dict[str, Any]) -> None:
    builder.link(operation["source_label"], operation["target_label"])
    if operation.get("properties"):
        builder.properties(*operation["properties"])
    if operation.get("nullable_keys"):
        builder.nullableKeys(*operation["nullable_keys"])
    if operation.get("sort_keys"):
        builder.sortKeys(*operation["sort_keys"])

    frequency = operation.get("frequency")
    if frequency:
        normalized = str(frequency).upper()
        method_name = EDGE_LABEL_FREQUENCY_METHODS.get(normalized)
        if method_name is None:
            raise ValueError(f"Unsupported edge label frequency: {frequency}")
        getattr(builder, method_name)()


def _operation_observed(
    operation: dict[str, Any],
    live_schema: dict[str, Any] | None,
) -> bool:
    schema = (
        (live_schema or {}).get("schema") if isinstance(live_schema, dict) else None
    )
    if not isinstance(schema, dict):
        schema = live_schema if isinstance(live_schema, dict) else {}
    collection = {
        "create_property_key": "propertykeys",
        "create_vertex_label": "vertexlabels",
        "create_edge_label": "edgelabels",
    }.get(_operation_type(operation))
    if collection is None:
        return False

    observed = _find_schema_item(schema, collection, operation.get("name"))
    if observed is None:
        return False
    return _operation_fields_match(operation, observed)


def _find_schema_item(
    schema: dict[str, Any], collection: str, name: Any
) -> dict[str, Any] | None:
    if not isinstance(name, str):
        return None
    for item in schema.get(collection, []):
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def _field_value(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in item:
            return item[name]
    return None


def _canonical_enum_value(field: str, value: str) -> str:
    if field == "data_type":
        return PROPERTY_KEY_DATA_TYPE_CANONICAL.get(value, value)
    return value


def _normalize_enum_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.upper()


def _normalize_name_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    names: list[str] = []
    for item in value:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
        else:
            return None
    return names


def _list_field_matches(
    observed: dict[str, Any], operation: dict[str, Any], field: str
) -> bool:
    if field not in operation:
        return True
    observed_values = _normalize_name_list(
        _field_value(observed, field, _camel_case_schema_field(field))
    )
    if observed_values is None:
        return False
    return observed_values == operation[field]


def _enum_field_matches(
    observed: dict[str, Any],
    operation: dict[str, Any],
    field: str,
    *,
    default: str | None = None,
) -> bool:
    expected = operation.get(field, default)
    if expected is None:
        return True
    observed_value = _normalize_enum_value(
        _field_value(observed, field, _camel_case_schema_field(field))
    )
    if observed_value is None:
        return False
    return _canonical_enum_value(field, observed_value) == _canonical_enum_value(
        field, str(expected).upper()
    )


def _string_field_matches(
    observed: dict[str, Any], operation: dict[str, Any], field: str
) -> bool:
    if field not in operation:
        return True
    return (
        _field_value(observed, field, _camel_case_schema_field(field))
        == operation[field]
    )


def _camel_case_schema_field(field: str) -> str:
    parts = field.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])


def _operation_fields_match(
    operation: dict[str, Any], observed: dict[str, Any]
) -> bool:
    op_type = _operation_type(operation)
    if op_type == "create_property_key":
        return (
            _enum_field_matches(observed, operation, "data_type")
            and _enum_field_matches(
                observed, operation, "cardinality", default="SINGLE"
            )
            and _enum_field_matches(observed, operation, "aggregate_type")
        )

    if op_type == "create_vertex_label":
        return (
            _enum_field_matches(
                observed, operation, "id_strategy", default="PRIMARY_KEY"
            )
            and _list_field_matches(observed, operation, "properties")
            and _list_field_matches(observed, operation, "primary_keys")
            and _list_field_matches(observed, operation, "nullable_keys")
        )

    if op_type == "create_edge_label":
        return (
            _string_field_matches(observed, operation, "source_label")
            and _string_field_matches(observed, operation, "target_label")
            and _list_field_matches(observed, operation, "properties")
            and _list_field_matches(observed, operation, "nullable_keys")
            and _list_field_matches(observed, operation, "sort_keys")
            and _enum_field_matches(observed, operation, "frequency")
        )

    return False


def _partial_apply_result(
    *,
    operations: list[dict[str, Any]],
    applied_operations: list[dict[str, Any]],
    operation_results: list[dict[str, Any]],
    failed_operation: dict[str, Any],
    failed_operation_index: int,
    error: str,
) -> dict[str, Any]:
    remaining_operations = operations[failed_operation_index:]
    return {
        "status": "partial" if applied_operations else "failed",
        "valid": False,
        "applied_operations": applied_operations,
        "operation_results": operation_results,
        "failed_operation": failed_operation,
        "failed_operation_index": failed_operation_index,
        "error": error,
        "remaining_operations": remaining_operations,
        "recovery_suggestions": _recovery_suggestions(),
        "mutation_summary": _mutation_summary(applied_operations),
    }


def _recovery_suggestions() -> list[str]:
    return [
        "Call inspect_schema_tool to observe the current schema state.",
        "Remove already-applied operations and dry-run the remaining operations again.",
        "Do not retry the original full batch without checking which operations were applied.",
    ]


def manage_schema(
    mode: str,
    operations: list[dict[str, Any]] | None = None,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> dict[str, Any]:
    """统一 schema 管理入口。

    - design: 获取分步 schema 设计引导
    - validate: 基于 live schema 校验操作合法性
    - dry_run: 校验 + 生成 target-bound plan_hash + 风险警告
    - apply: P0a create_property_key/create_vertex_label/create_edge_label

    Args:
        mode: 操作模式 ("design" / "validate" / "dry_run" / "apply")
        operations: schema 操作列表
        confirm: apply requires True after dry_run
        plan_hash: dry_run returned plan_hash
        nonce: dry_run returned plan_context.nonce
        expires_at: dry_run returned plan_context.expires_at
    """
    operations = operations or []

    if mode == "design":
        return envelope_ok(_design_from_operations(operations))

    if mode == "validate":
        live_schema, error = _safe_fetch_live_schema()
        if error:
            return error
        return envelope_ok(validate_schema_operations(operations, live_schema))

    if mode == "dry_run":
        live_schema, error = _safe_fetch_live_schema()
        if error:
            return error
        result = dry_run_schema_operations(operations, live_schema, nonce=nonce)
        if result.get("valid") and not MCPConfig.from_env().is_readonly():
            plan_context = _build_schema_plan_context(
                operations=operations,
                live_schema=live_schema,
                nonce=result["plan_context"]["nonce"],
            )
            plan_context = replace(
                plan_context,
                expires_at=int(result["plan_context"]["expires_at"]),
            )
            issue_error = issue_plan(plan_context, result["plan_hash"])
            if issue_error is not None:
                return issue_error
        if result.get("valid") and MCPConfig.from_env().is_readonly():
            result["confirmable"] = False
            result["readonly_preview_only"] = True
            return envelope_ok(
                result,
                warnings=list(result.get("warnings", []))
                + [
                    (
                        "This dry-run was generated while HUGEGRAPH_MCP_READONLY=true. "
                        "Set HUGEGRAPH_MCP_READONLY=false and rerun dry_run before confirming writes."
                    )
                ],
                next_actions=[
                    "Set HUGEGRAPH_MCP_READONLY=false and rerun dry_run before confirm."
                ],
            )
        return envelope_ok(
            result,
            next_actions=[
                "Review schema preview, then call apply_schema_tool(mode='apply', confirm=true, plan_hash, nonce, expires_at)."
            ]
            if result.get("valid")
            else ["Fix validation errors and rerun apply_schema_tool(mode='dry_run')."],
        )

    if mode == "apply":
        if confirm:
            replay_error = replayed_plan_error(nonce)
            if replay_error is not None:
                return replay_error
        live_schema, error = _safe_fetch_live_schema()
        if error:
            return error
        dry_run_result = dry_run_schema_operations(operations, live_schema, nonce=nonce)
        if not dry_run_result.get("valid"):
            return envelope_err(
                ErrorType.SCHEMA_MISMATCH,
                "Schema operations are not valid for P0a apply.",
                details={"errors": dry_run_result.get("errors", [])},
                warnings=dry_run_result.get("warnings", []),
                next_actions=[
                    "Fix validation errors and rerun apply_schema_tool(mode='dry_run')."
                ],
            )
        violation = guard(Capability.SCHEMA_WRITE)
        if violation is not None:
            return violation
        if not confirm:
            return confirm_required_error(
                message="Schema apply requires confirm=True after dry_run.",
                suggestion=(
                    "Run mode='dry_run', review the plan, then pass confirm=True "
                    "with plan_hash, nonce, and expires_at."
                ),
            )
        valid, error_type, details = verify_and_consume_plan(
            submitted_hash=plan_hash,
            tool_name="apply_schema_tool",
            mode="apply",
            payload_digest=_schema_payload_digest(operations),
            schema_hash=_schema_hash(live_schema),
            nonce=nonce,
            expires_at=expires_at,
        )
        if not valid:
            return plan_hash_error(
                error_type=error_type,
                details=details,
                mismatch_message="Provided plan_hash does not match the current schema apply plan.",
                suggestion="Run mode='dry_run' again and use the returned plan_hash.",
            )

        apply_result = apply_schema_operations(operations, live_schema=live_schema)
        if apply_result.get("status") in {"failed", "partial"}:
            return envelope_err(
                ErrorType.PARTIAL_APPLY,
                "Schema apply did not complete all operations.",
                details=apply_result,
                next_actions=apply_result.get("recovery_suggestions", []),
            )
        return envelope_ok(
            apply_result,
            next_actions=["Call inspect_schema_tool to verify the applied schema."],
        )

    return envelope_err(
        ErrorType.VALIDATION_ERROR,
        f"Unsupported manage_schema mode: {mode}",
        suggestion="Use one of: design, validate, dry_run, apply.",
    )
