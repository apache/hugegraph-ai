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

"""Schema inspection tool for v2_core."""

from typing import Any

from pyhugegraph.client import PyHugeClient

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.hugegraph_client import build_hugegraph_client
from hugegraph_mcp.tools.schema_utils import (
    edge_schema_endpoint_label,
    primary_key_names,
    property_names,
    schema_name,
    schema_payload,
)

FILTER_KINDS = frozenset({"property_key", "vertex_label", "edge_label", "index_label"})


def _schema_manager():
    return build_hugegraph_client(
        MCPConfig.from_env(), client_cls=PyHugeClient
    ).schema()


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
        raw_schema = manager.getSchema()
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
        relations = _safe_get_relations(manager) if include_relations else []
    except Exception as exc:  # noqa: BLE001 - return structured dependency error
        return _schema_dependency_error(exc)

    raw_payload = schema_payload(raw_schema) or raw_schema
    summary = _build_summary(raw_payload, include_index_labels=include_index_labels)
    all_summary = (
        summary
        if include_index_labels
        else _build_summary(raw_payload, include_index_labels=True)
    )
    filtered = _filter_schema(raw_payload, filter_kind, filter_name, all_summary)
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

    data: dict[str, Any] = {
        "summary": summary,
        "relations": relations,
        "index_labels": summary["index_labels"] if include_index_labels else [],
        "filtered": filtered,
    }
    if include_raw_schema:
        data["raw_schema"] = raw_payload

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
            suggestion=(
                "Use one of: property_key, vertex_label, edge_label, index_label."
            ),
            source="inspect_schema_tool",
            details={"filter_kind": filter_kind},
        )
    return None


def _safe_get_relations(manager) -> list[str]:
    try:
        relations = manager.getRelations()
    except Exception:  # noqa: BLE001 - relations are optional
        return []
    return [str(item) for item in relations or []]


def _schema_dependency_error(exc: Exception) -> dict[str, Any]:
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
    property_keys = [
        _normalize_schema_item(item) for item in _items(raw_schema, "propertykeys")
    ]
    vertex_labels = [
        _normalize_vertex_label(item) for item in _items(raw_schema, "vertexlabels")
    ]
    edge_labels = [
        _normalize_edge_label(item) for item in _items(raw_schema, "edgelabels")
    ]
    index_labels = (
        [_normalize_schema_item(item) for item in _items(raw_schema, "indexlabels")]
        if include_index_labels
        else []
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
    normalized = [
        _normalize_kind_item(filter_kind, item) for item in _items(raw_schema, key)
    ]
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
