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

"""Shared HugeGraph schema parsing and normalization helpers."""

from typing import Any

__all__ = [
    "edge_schema_endpoint_label",
    "normalized_schema_summary",
    "primary_key_names",
    "property_cardinalities",
    "property_names",
    "schema_name",
    "schema_payload",
]


def schema_name(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        name = item.get("name")
        return name if isinstance(name, str) else None
    return None


def property_names(properties: Any) -> set[str]:
    if not isinstance(properties, list):
        return set()
    return {name for prop in properties if (name := schema_name(prop))}


def property_cardinalities(
    live_schema: dict[str, Any] | None,
) -> dict[str, str]:
    """Return property-key cardinalities from supported live-schema shapes."""
    raw = schema_payload(live_schema)
    if raw is None:
        return {}
    property_keys = _property_key_items(raw)
    if not isinstance(property_keys, list):
        return {}

    cardinalities: dict[str, str] = {}
    for item in property_keys:
        if not isinstance(item, dict):
            continue
        name = _field_value(item, "name", "property_name", "propertyName")
        cardinality = _field_value(
            item,
            "cardinality",
            "cardinality_type",
            "cardinalityType",
        )
        if not isinstance(name, str):
            continue
        normalized = str(cardinality or "SINGLE").strip().upper()
        cardinalities[name] = normalized
    return cardinalities


def _property_key_items(raw_schema: dict[str, Any]) -> Any:
    return _field_value(raw_schema, "propertykeys", "property_keys", "propertyKeys")


def primary_key_names(vertex_label: dict[str, Any]) -> list[str]:
    primary_keys = vertex_label.get("primary_keys")
    if primary_keys is None:
        primary_keys = vertex_label.get("primaryKeys")
    if not isinstance(primary_keys, list):
        return []
    return [name for pk in primary_keys if (name := schema_name(pk))]


def schema_payload(live_schema: dict[str, Any] | None) -> dict[str, Any] | None:
    # inspect_graph/get_live_schema may return {"schema": {...}} or the schema
    # itself; unwrap it in one shared entry point instead of in each tool.
    if live_schema is None or not isinstance(live_schema, dict):
        return None
    if "schema" in live_schema:
        raw = live_schema.get("schema")
    else:
        raw = live_schema
    return raw if isinstance(raw, dict) else None


def edge_schema_endpoint_label(edge_schema: dict[str, Any], endpoint: str) -> Any:
    if endpoint == "source":
        return edge_schema.get("source_label") or edge_schema.get("sourceLabel")
    return edge_schema.get("target_label") or edge_schema.get("targetLabel")


def _field_value(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in item:
            return item.get(name)
    return None


def _normalize_named_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    names = [name for value in values if (name := schema_name(value))]
    return sorted(names)


def _normalize_schema_items(
    items: Any,
    field_aliases: list[tuple[str, tuple[str, ...]]],
    *,
    name_aliases: tuple[str, ...] = ("name",),
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return normalized

    for item in items:
        if not isinstance(item, dict):
            continue
        name = _field_value(item, *name_aliases)
        if not isinstance(name, str):
            continue
        result: dict[str, Any] = {"name": name}
        for output_name, aliases in field_aliases:
            value = _field_value(item, *aliases)
            if value is None:
                continue
            if output_name in {
                "fields",
                "index_labels",
                "nullable_keys",
                "primary_keys",
                "properties",
                "sort_keys",
            }:
                value = _normalize_named_list(value)
            result[output_name] = value
        normalized.append(result)

    return sorted(normalized, key=lambda value: value["name"])


def normalized_schema_summary(
    live_schema: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the security-relevant schema subset used for plan hashes."""
    raw = schema_payload(live_schema)
    if raw is None:
        return None

    # The plan hash only includes schema fields that affect write semantics:
    # property types, label properties/primary keys/endpoints, and index definitions.
    # Metadata such as IDs, status, and creation time is intentionally ignored
    # so unrelated changes do not cause a false rejection during confirmation.
    return {
        "propertykeys": _normalize_schema_items(
            _property_key_items(raw),
            [
                ("data_type", ("data_type", "dataType")),
                (
                    "cardinality",
                    ("cardinality", "cardinality_type", "cardinalityType"),
                ),
                ("aggregate_type", ("aggregate_type", "aggregateType")),
            ],
            name_aliases=("name", "property_name", "propertyName"),
        ),
        "vertexlabels": _normalize_schema_items(
            raw.get("vertexlabels"),
            [
                ("id_strategy", ("id_strategy", "idStrategy")),
                ("properties", ("properties",)),
                ("primary_keys", ("primary_keys", "primaryKeys")),
                ("nullable_keys", ("nullable_keys", "nullableKeys")),
                ("index_labels", ("index_labels", "indexLabels")),
                (
                    "enable_label_index",
                    ("enable_label_index", "enableLabelIndex"),
                ),
            ],
        ),
        "edgelabels": _normalize_schema_items(
            raw.get("edgelabels"),
            [
                ("source_label", ("source_label", "sourceLabel")),
                ("target_label", ("target_label", "targetLabel")),
                ("properties", ("properties",)),
                ("nullable_keys", ("nullable_keys", "nullableKeys")),
                ("sort_keys", ("sort_keys", "sortKeys")),
                ("frequency", ("frequency",)),
                (
                    "enable_label_index",
                    ("enable_label_index", "enableLabelIndex"),
                ),
            ],
        ),
        "indexlabels": _normalize_schema_items(
            raw.get("indexlabels"),
            [
                ("base_type", ("base_type", "baseType")),
                ("base_label", ("base_label", "baseLabel")),
                ("index_type", ("index_type", "indexType")),
                ("fields", ("fields",)),
                ("unique", ("unique",)),
            ],
        ),
    }
