# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The closed schema-operation field contract.

The MCP schema tool has three independent boundaries which must agree:
validation, builder forwarding, and post-read verification.  This module is
the single source of truth for the field names, live-schema aliases, and value
shapes used by those boundaries (and by the schema portion of plan hashes).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FieldKind = Literal["identity", "enum", "list", "mapping", "boolean", "scalar"]


@dataclass(frozen=True)
class SchemaFieldSpec:
    """Canonical operation field metadata.

    ``aliases`` starts with the operation's snake-case spelling and then lists
    the names that HugeGraph may use in a live schema response.  ``kind`` is
    consumed by validation/matching/normalization; ``default`` is only used
    when the server applies a documented default for an omitted field.
    """

    aliases: tuple[str, ...]
    kind: FieldKind = "scalar"
    default: str | None = None
    include_in_summary: bool = True
    # ``none`` means the field is validate-only (for example an index-label
    # field while P0a apply is intentionally disabled).  Other values document
    # how the corresponding builder receives the field and let apply fail
    # closed if a new field is added without a forwarding path.
    apply_mode: Literal["none", "identity", "typed", "parameter", "link"] = "none"


def _field(
    *aliases: str,
    kind: FieldKind = "scalar",
    default: str | None = None,
    include_in_summary: bool = True,
    apply_mode: Literal["none", "identity", "typed", "parameter", "link"] = "none",
) -> SchemaFieldSpec:
    if not aliases:
        raise ValueError("a schema field needs at least one alias")
    return SchemaFieldSpec(
        aliases=tuple(dict.fromkeys(aliases)),
        kind=kind,
        default=default,
        include_in_summary=include_in_summary,
        apply_mode=apply_mode,
    )


# Keep the operation discriminator in the table as well.  It is accepted by
# validation but is not a field returned by HugeGraph's schema GET response.
SUPPORTED_FIELD_SPECS: dict[str, dict[str, SchemaFieldSpec]] = {
    "create_property_key": {
        "type": _field(
            "type", kind="identity", include_in_summary=False, apply_mode="identity"
        ),
        "name": _field(
            "name",
            "property_name",
            "propertyName",
            kind="identity",
            include_in_summary=False,
            apply_mode="identity",
        ),
        "data_type": _field("data_type", "dataType", kind="enum", apply_mode="typed"),
        "cardinality": _field(
            "cardinality",
            "cardinality_type",
            "cardinalityType",
            kind="enum",
            default="SINGLE",
            apply_mode="typed",
        ),
        "aggregate_type": _field(
            "aggregate_type", "aggregateType", kind="enum", apply_mode="typed"
        ),
        "user_data": _field(
            "user_data", "userData", "userdata", kind="mapping", apply_mode="parameter"
        ),
    },
    "create_vertex_label": {
        "type": _field(
            "type", kind="identity", include_in_summary=False, apply_mode="identity"
        ),
        "name": _field(
            "name", kind="identity", include_in_summary=False, apply_mode="identity"
        ),
        "id_strategy": _field(
            "id_strategy",
            "idStrategy",
            kind="enum",
            default="PRIMARY_KEY",
            apply_mode="typed",
        ),
        "properties": _field("properties", kind="list", apply_mode="typed"),
        "primary_keys": _field(
            "primary_keys", "primaryKeys", kind="list", apply_mode="typed"
        ),
        "nullable_keys": _field(
            "nullable_keys", "nullableKeys", kind="list", apply_mode="typed"
        ),
        "index_labels": _field(
            "index_labels", "indexLabels", kind="list", apply_mode="parameter"
        ),
        "enable_label_index": _field(
            "enable_label_index", "enableLabelIndex", kind="boolean", apply_mode="typed"
        ),
        "user_data": _field(
            "user_data", "userData", "userdata", kind="mapping", apply_mode="parameter"
        ),
    },
    "create_edge_label": {
        "type": _field(
            "type", kind="identity", include_in_summary=False, apply_mode="identity"
        ),
        "name": _field(
            "name", kind="identity", include_in_summary=False, apply_mode="identity"
        ),
        "source_label": _field(
            "source_label", "sourceLabel", kind="scalar", apply_mode="link"
        ),
        "target_label": _field(
            "target_label", "targetLabel", kind="scalar", apply_mode="link"
        ),
        "properties": _field("properties", kind="list", apply_mode="typed"),
        "nullable_keys": _field(
            "nullable_keys", "nullableKeys", kind="list", apply_mode="typed"
        ),
        "sort_keys": _field("sort_keys", "sortKeys", kind="list", apply_mode="typed"),
        "frequency": _field("frequency", kind="enum", apply_mode="typed"),
        "enable_label_index": _field(
            "enable_label_index", "enableLabelIndex", kind="boolean", apply_mode="typed"
        ),
        "user_data": _field(
            "user_data", "userData", "userdata", kind="mapping", apply_mode="parameter"
        ),
    },
    # Index creation is validate-only for P0a, but it still has a closed
    # validate/hash contract so fields cannot be silently accepted and dropped.
    "create_index_label": {
        "type": _field(
            "type", kind="identity", include_in_summary=False, apply_mode="identity"
        ),
        "name": _field(
            "name", kind="identity", include_in_summary=False, apply_mode="identity"
        ),
        "base_type": _field("base_type", "baseType", kind="enum"),
        "base_label": _field(
            "base_label", "baseLabel", "base_value", "baseValue", kind="scalar"
        ),
        "fields": _field("fields", kind="list"),
        "index_type": _field("index_type", "indexType", kind="enum"),
        "unique": _field("unique", kind="boolean"),
    },
}

# Preserve the compact field-set view exposed by the original manage_schema
# module while keeping the richer metadata in the same source table above.
SUPPORTED_FIELDS: dict[str, frozenset[str]] = {
    op_type: frozenset(specs) for op_type, specs in SUPPORTED_FIELD_SPECS.items()
}

OPERATION_KIND = {
    "create_property_key": "property_key",
    "create_vertex_label": "vertex_label",
    "create_edge_label": "edge_label",
    "create_index_label": "index_label",
}

SCHEMA_COLLECTIONS = {
    "property_key": "propertykeys",
    "vertex_label": "vertexlabels",
    "edge_label": "edgelabels",
    "index_label": "indexlabels",
}


def field_specs_for_operation(op_type: str) -> dict[str, SchemaFieldSpec]:
    """Return the contract fields for an operation type."""

    return SUPPORTED_FIELD_SPECS.get(op_type, {})


def field_specs_for_kind(kind: str) -> dict[str, SchemaFieldSpec]:
    """Return the contract fields for a live-schema collection kind."""

    for op_type, operation_kind in OPERATION_KIND.items():
        if operation_kind == kind:
            return SUPPORTED_FIELD_SPECS[op_type]
    return {}


def apply_fields_for_operation(op_type: str) -> frozenset[str]:
    """Return fields with an explicit builder-forwarding contract."""

    return frozenset(
        field
        for field, spec in field_specs_for_operation(op_type).items()
        if spec.apply_mode != "none"
    )


def schema_collection_for_operation(op_type: str) -> str | None:
    kind = OPERATION_KIND.get(op_type)
    return SCHEMA_COLLECTIONS.get(kind) if kind else None


__all__ = [
    "OPERATION_KIND",
    "SCHEMA_COLLECTIONS",
    "SUPPORTED_FIELDS",
    "SUPPORTED_FIELD_SPECS",
    "SchemaFieldSpec",
    "apply_fields_for_operation",
    "field_specs_for_kind",
    "field_specs_for_operation",
    "schema_collection_for_operation",
]
