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

"""Schema inspection tool for core."""

from typing import Any

from pyhugegraph.client import PyHugeClient

from hugegraph_mcp.config import get_effective_config
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.hugegraph_client import build_hugegraph_client
from hugegraph_mcp.read_budget import read_budget_from_config
from hugegraph_mcp.schema_snapshot import bound_schema_payload
from hugegraph_mcp.tools.schema_utils import (
    edge_schema_endpoint_label,
    primary_key_names,
    property_names,
    schema_name,
    schema_payload,
)

FILTER_KINDS = frozenset({"property_key", "vertex_label", "edge_label", "index_label"})


def _schema_manager():
    return build_hugegraph_client(get_effective_config(), client_cls=PyHugeClient).schema()


def inspect_schema(
    *,
    include_raw_schema: bool = False,
    include_relations: bool = True,
    include_index_labels: bool = True,
    filter_kind: str | None = None,
    filter_name: str | None = None,
) -> dict[str, Any]:
    """Inspect HugeGraph schema objects and relations.

    Capability: READ.

    filter_kind values: property_key, vertex_label, edge_label, index_label.
    filter_name may be used only with filter_kind and must name one schema object.
    include_raw_schema controls whether the raw server schema is returned.
    """

    filter_kind = _normalize_optional_str(filter_kind)
    filter_name = _normalize_optional_str(filter_name)

    validation_error = _validate_filter(filter_kind, filter_name)
    if validation_error is not None:
        return validation_error

    try:
        manager = _schema_manager()
        budget = read_budget_from_config()
        with budget.request_guard(manager):
            raw_schema = manager.get_schema()
        if raw_schema is None:
            return envelope_err(
                ErrorType.CONNECTION_FAILED,
                "HugeGraph Server returned an empty schema response.",
                retryable=True,
                source="inspect_schema_tool",
                next_actions=[
                    "Check HugeGraph Server health and retry inspect_schema_tool.",
                ],
            )
        try:
            import json as _json

            budget.record_bytes(len(_json.dumps(raw_schema, default=str).encode("utf-8")))
        except Exception:
            pass
        if include_relations:
            with budget.request_guard(manager):
                relations = _safe_get_relations(manager)
        else:
            relations = []
    except Exception as exc:
        return _schema_dependency_error(exc)

    raw_payload = schema_payload(raw_schema) or raw_schema
    summary = _build_summary(raw_payload, include_index_labels=include_index_labels)
    filtered = _filter_schema(raw_payload, filter_kind, filter_name, summary)
    if filtered is None:
        return envelope_err(
            ErrorType.NOT_FOUND,
            f"{filter_kind} not found: {filter_name}",
            source="inspect_schema_tool",
            details={"filter_kind": filter_kind, "filter_name": filter_name},
            next_actions=[
                "Call inspect_schema_tool without filter_name to list available schema objects.",
            ],
        )

    summary_truncated = False
    max_summary_items = max(1, int(budget.max_items))
    for key in ("property_keys", "vertex_labels", "edge_labels", "index_labels"):
        items = summary.get(key)
        if isinstance(items, list) and len(items) > max_summary_items:
            summary[key] = items[:max_summary_items]
            summary_truncated = True
    if len(relations) > max_summary_items:
        relations = relations[:max_summary_items]
        summary_truncated = True

    data: dict[str, Any] = {
        "summary": summary,
        "relations": relations,
        "index_labels": summary["index_labels"] if include_index_labels else [],
        "filtered": filtered,
        "truncated": summary_truncated,
    }
    if summary_truncated:
        data["truncation_reason"] = "RESULT_BUDGET_ITEMS_EXCEEDED"
    if include_raw_schema:
        from hugegraph_mcp.schema_snapshot import compute_schema_fingerprint

        data["schema_fingerprint"] = compute_schema_fingerprint(
            raw_payload if isinstance(raw_payload, dict) else {"raw_schema": raw_payload}
        )
        bounded_raw, truncated, truncation_reason = bound_schema_payload(raw_payload)
        data["raw_schema"] = bounded_raw
        data["truncated"] = summary_truncated or truncated
        data["truncation_reason"] = truncation_reason or data.get("truncation_reason")

    return envelope_ok(
        data,
        next_actions=[
            "Use query_graph_data_tool to inspect data that uses this schema.",
            "Use apply_schema_tool(mode='dry_run') before creating new schema objects.",
        ],
    )


def _normalize_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _validate_filter(
    filter_kind: str | None,
    filter_name: str | None,
) -> dict[str, Any] | None:
    if filter_kind is None and filter_name is not None:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "filter_name requires filter_kind.",
            suggestion="Pass filter_kind together with filter_name.",
            source="inspect_schema_tool",
            details={"filter_name": filter_name},
        )

    if filter_kind is not None and filter_kind not in FILTER_KINDS:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"Unsupported filter_kind: {filter_kind!r}.",
            suggestion=("Use one of: property_key, vertex_label, edge_label, index_label."),
            source="inspect_schema_tool",
            details={"filter_kind": filter_kind},
        )
    return None


def _safe_get_relations(manager) -> list[str]:
    try:
        relations = manager.get_relations()
    except (AttributeError, NotImplementedError):
        return []
    return [str(item) for item in relations or []]


def _schema_dependency_error(exc: Exception) -> dict[str, Any]:
    from hugegraph_mcp.read_budget import ReadBudgetExceededError

    if isinstance(exc, ReadBudgetExceededError):
        is_deadline = exc.reason_code == "READ_DEADLINE_EXCEEDED"
        return envelope_err(
            ErrorType.TIMEOUT if is_deadline else ErrorType.VALIDATION_ERROR,
            f"Schema inspection exceeded read budget: {exc!s}",
            retryable=is_deadline,
            source="inspect_schema_tool",
            details={"error": str(exc), "reason_code": exc.reason_code},
        )
    return envelope_err(
        ErrorType.CONNECTION_FAILED,
        f"Cannot inspect HugeGraph schema: {exc!s}",
        suggestion="Verify HugeGraph Server URL, graph, graphspace, and credentials.",
        retryable=True,
        source="inspect_schema_tool",
        details={"error": str(exc)},
        next_actions=["Retry inspect_graph_tool to confirm server connectivity."],
    )


def _build_summary(
    raw_schema: dict[str, Any],
    *,
    include_index_labels: bool,
) -> dict[str, Any]:
    property_keys = [_normalize_schema_item(item) for item in _items(raw_schema, "propertykeys")]
    vertex_labels = [_normalize_vertex_label(item) for item in _items(raw_schema, "vertexlabels")]
    edge_labels = [_normalize_edge_label(item) for item in _items(raw_schema, "edgelabels")]
    index_labels = (
        [_normalize_schema_item(item) for item in _items(raw_schema, "indexlabels")] if include_index_labels else []
    )
    return {
        "property_key_count": len(property_keys),
        "vertex_label_count": len(vertex_labels),
        "edge_label_count": len(edge_labels),
        "index_label_count": len(_items(raw_schema, "indexlabels")),
        "property_keys": property_keys,
        "vertex_labels": vertex_labels,
        "edge_labels": edge_labels,
        "index_labels": index_labels,
    }


def _items(raw_schema: dict[str, Any], key: str) -> list[Any]:
    values = raw_schema.get(key)
    return values if isinstance(values, list) else []


def _filter_schema(
    raw_schema: dict[str, Any],
    filter_kind: str | None,
    filter_name: str | None,
    summary: dict[str, Any],
) -> dict[str, Any] | list[Any]:
    if filter_kind is None:
        return {
            "property_keys": summary["property_keys"],
            "vertex_labels": summary["vertex_labels"],
            "edge_labels": summary["edge_labels"],
            "index_labels": summary["index_labels"],
        }

    key = {
        "property_key": "propertykeys",
        "vertex_label": "vertexlabels",
        "edge_label": "edgelabels",
        "index_label": "indexlabels",
    }[filter_kind]
    normalized = [_normalize_kind_item(filter_kind, item) for item in _items(raw_schema, key)]
    if filter_name is None:
        return normalized
    for item in normalized:
        if item.get("name") == filter_name:
            return item
    return None


def _normalize_kind_item(filter_kind: str, item: Any) -> dict[str, Any]:
    if filter_kind == "vertex_label":
        return _normalize_vertex_label(item)
    if filter_kind == "edge_label":
        return _normalize_edge_label(item)
    return _normalize_schema_item(item)


def _normalize_vertex_label(item: Any) -> dict[str, Any]:
    normalized = _normalize_schema_item(item)
    if isinstance(item, dict):
        normalized["properties"] = sorted(property_names(item.get("properties")))
        normalized["primary_keys"] = primary_key_names(item)
        nullable_keys = item.get("nullable_keys") or item.get("nullableKeys")
        normalized["nullable_keys"] = _names(nullable_keys)
    return normalized


def _normalize_edge_label(item: Any) -> dict[str, Any]:
    normalized = _normalize_schema_item(item)
    if isinstance(item, dict):
        normalized["source_label"] = edge_schema_endpoint_label(item, "source")
        normalized["target_label"] = edge_schema_endpoint_label(item, "target")
        normalized["properties"] = sorted(property_names(item.get("properties")))
        nullable_keys = item.get("nullable_keys") or item.get("nullableKeys")
        normalized["nullable_keys"] = _names(nullable_keys)
    return normalized


def _normalize_schema_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    result: dict[str, Any] = {}
    for name in (
        "name",
        "dataType",
        "cardinality",
        "id",
        "baseType",
        "baseValue",
        "indexType",
        "fields",
    ):
        if hasattr(item, name):
            result[name] = getattr(item, name)
    if not result:
        result["value"] = str(item)
    return result


def _names(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted(name for value in values if (name := schema_name(value)))
