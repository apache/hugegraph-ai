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

"""图数据导入 — 结构化 graph_data 校验和 legacy AI-backed 写入链路。

=== MCP V1 导入路径说明 ===

当前存在两条导入路径：

1. **Public V1 路径（推荐）**
   import_graph_data_tool(mode="ingest") 路由到 manage_graph_data()
   → graph_data_to_change_plan() → 本地 Gremlin 写入。
   此路径在 server.py:_import_graph_data() 中分发，不依赖
   HugeGraph-AI 服务。

2. **Legacy AI-backed 路径（兼容保留）**
   ingest_graph_data() 真实实现为 ingest_graph_data_via_ai()，
   通过 HugeGraph-AI /graph-import HTTP 接口写入。
   仅供需要 AI 辅助属性映射的内部/legacy 场景使用，
   不做为 MCP V1 公共工具的默认导入链路。

validate_graph_payload() 对 vertices/edges 做全面 schema 校验：
- label 是否存在于 live schema
- properties 字段是否在对应 label 中定义
- 主键是否提供
- 边端点是否可解析
- 类型匹配
"""

import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.confirmable_workflow import (
    issue_plan,
    mark_readonly_preview,
    plan_hash_error,
    replayed_plan_error,
    verify_and_consume_plan,
)
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.hugegraph_ai_client import post
from hugegraph_mcp.tools.live_schema import fetch_live_schema_or_none
from hugegraph_mcp.tools.schema_utils import (
    edge_schema_endpoint_label as _edge_schema_endpoint_label,
)
from hugegraph_mcp.tools.schema_utils import (
    normalized_schema_summary,
)
from hugegraph_mcp.tools.schema_utils import (
    primary_key_names as _primary_key_names,
)
from hugegraph_mcp.tools.schema_utils import (
    property_names as _property_names,
)
from hugegraph_mcp.tools.schema_utils import (
    schema_payload as _schema_payload,
)

_DATA_TYPE_ALIASES = {"INTEGER": "INT", "BOOL": "BOOLEAN"}
_SUPPORTED_DATA_TYPES = {
    "TEXT",
    "UUID",
    "INT",
    "LONG",
    "DOUBLE",
    "FLOAT",
    "BOOLEAN",
    "DATE",
    "BYTE",
    "BLOB",
    "OBJECT",
}
_SUPPORTED_CARDINALITIES = {"SINGLE", "LIST", "SET"}


def _property_specs(raw_schema: dict[str, Any]) -> dict[str, tuple[str, str]]:
    specs: dict[str, tuple[str, str]] = {}
    normalized_schema = normalized_schema_summary(raw_schema) or {}
    for prop in normalized_schema.get("propertykeys", []):
        if not isinstance(prop, dict):
            continue
        name = prop.get("name")
        data_type = prop.get("data_type")
        if isinstance(name, str) and isinstance(data_type, str):
            cardinality = prop.get("cardinality") or "SINGLE"
            normalized_data_type = data_type.strip().upper()
            specs[name] = (
                _DATA_TYPE_ALIASES.get(normalized_data_type, normalized_data_type),
                str(cardinality).strip().upper(),
            )
    return specs


def _value_matches_type(value: Any, data_type: str) -> bool:
    if value is None:
        return True
    if data_type in {"TEXT", "UUID"}:
        return isinstance(value, str)
    if data_type in {"INT", "LONG", "BYTE"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if data_type in {"FLOAT", "DOUBLE"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if data_type == "BOOLEAN":
        return isinstance(value, bool)
    if data_type in {"DATE", "BLOB"}:
        return isinstance(value, str)
    if data_type == "OBJECT":
        return isinstance(value, dict)
    return False


def _property_value_error(
    *,
    item_kind: str,
    item_index: int,
    property_name: str,
    value: Any,
    spec: tuple[str, str] | None,
) -> str | None:
    if spec is None:
        return None

    data_type, cardinality = spec
    prefix = f"{item_kind} {item_index} property '{property_name}'"
    if data_type not in _SUPPORTED_DATA_TYPES:
        return f"{prefix} unsupported data_type '{data_type}'"
    if cardinality not in _SUPPORTED_CARDINALITIES:
        return f"{prefix} unsupported cardinality '{cardinality}'"
    if cardinality in {"LIST", "SET"}:
        if value is None:
            return None
        if not isinstance(value, list):
            return (
                f"{prefix} expects {cardinality} of {data_type}, "
                f"got {type(value).__name__}"
            )
        for element_index, element in enumerate(value):
            if element is None or not _value_matches_type(element, data_type):
                return (
                    f"{prefix} element {element_index} expects {data_type}, "
                    f"got {type(element).__name__}"
                )
        return None

    if not _value_matches_type(value, data_type):
        return f"{prefix} expects {data_type}, got {type(value).__name__}"
    return None


def _indexed_labels(raw_schema: dict[str, Any]) -> dict[str, set[str]]:
    indexed = {"VERTEX": set(), "EDGE": set()}
    for index in raw_schema.get("indexlabels", []):
        if not isinstance(index, dict):
            continue
        base_label = index.get("base_label") or index.get("baseLabel")
        if not isinstance(base_label, str):
            continue
        base_type = str(index.get("base_type") or index.get("baseType") or "").upper()
        if base_type in {"VERTEX", "VERTEX_LABEL"}:
            indexed["VERTEX"].add(base_label)
        elif base_type in {"EDGE", "EDGE_LABEL"}:
            indexed["EDGE"].add(base_label)
    return indexed


def _edge_endpoint(edge: dict[str, Any], endpoint: str) -> tuple[Any, Any]:
    if endpoint == "source":
        label = edge.get("source_label") or edge.get("outVLabel")
        value = edge.get("source") if "source" in edge else edge.get("outV")
    else:
        label = edge.get("target_label") or edge.get("inVLabel")
        value = edge.get("target") if "target" in edge else edge.get("inV")
    return label, value


def _has_mixed_endpoint_forms(edge: dict[str, Any], endpoint: str) -> bool:
    if endpoint == "source":
        return "source" in edge and "outV" in edge
    return "target" in edge and "inV" in edge


def _identity_value_present(value: Any) -> bool:
    return value is not None and value != ""


def _format_endpoint_value(value: Any) -> str:
    return repr(value)


def _endpoint_identities(
    label: str,
    value: Any,
    schema_primary_keys: dict[str, list[str]],
) -> tuple[list[tuple[str, str, Any]], str | None]:
    # Edge endpoints support backend IDs or objects keyed by vertex primary keys.
    # Multiple candidate identities support both inputs such as "1:alice" and
    # {"name": "alice"}.
    identities: list[tuple[str, str, Any]] = []
    primary_keys = schema_primary_keys.get(label, [])

    if isinstance(value, dict):
        explicit_id = value.get("id")
        if _identity_value_present(explicit_id):
            identities.append((label, "id", explicit_id))
        if primary_keys:
            missing = [
                pk
                for pk in primary_keys
                if pk not in value or not _identity_value_present(value.get(pk))
            ]
            if missing:
                if identities:
                    return identities, None
                return identities, missing[0]
            identities.append(
                (label, "pk", tuple(value.get(pk) for pk in primary_keys))
            )
        return identities, None

    if _identity_value_present(value):
        identities.append((label, "id", value))
        if len(primary_keys) == 1:
            pk_value = value
            if isinstance(value, str) and ":" in value:
                pk_value = value.split(":", 1)[1]
            identities.append((label, "pk", (pk_value,)))
    return identities, None


def _schema_plan_summary(live_schema: dict[str, Any] | None) -> dict[str, Any] | None:
    raw = _schema_payload(live_schema)
    if raw is None:
        return None
    return {
        "vertexlabels": raw.get("vertexlabels", []),
        "edgelabels": raw.get("edgelabels", []),
        "propertykeys": raw.get("propertykeys", []),
        "indexlabels": raw.get("indexlabels", []),
    }


def _canonical_json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


def _vertex_sort_key(
    vertex: Any,
    schema_primary_keys: dict[str, list[str]],
) -> tuple[str, str]:
    if not isinstance(vertex, dict):
        return ("", _canonical_json_key(vertex))
    label = str(vertex.get("label") or "")
    if _identity_value_present(vertex.get("id")):
        identity = vertex.get("id")
    else:
        props = vertex.get("properties")
        primary_keys = schema_primary_keys.get(label, [])
        if isinstance(props, dict) and primary_keys:
            identity = props.get(primary_keys[0])
        elif isinstance(props, dict) and props:
            first_key = min(props, key=lambda item: str(item))
            identity = props.get(first_key)
        else:
            identity = None
    return (label, _canonical_json_key(identity))


def _edge_sort_key(edge: Any) -> tuple[str, str, str, str]:
    if not isinstance(edge, dict):
        return ("", "", "", _canonical_json_key(edge))
    source_label, source = _edge_endpoint(edge, "source")
    target_label, target = _edge_endpoint(edge, "target")
    return (
        str(edge.get("label") or ""),
        str(source_label or ""),
        str(target_label or ""),
        _canonical_json_key(
            {
                "source": source,
                "target": target,
                "properties": edge.get("properties", {}),
            }
        ),
    )


def _normalize_graph_data(
    graph_data: dict[str, Any],
    schema_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    # plan_hash must be independent of input order: the same vertices/edges should
    # produce the same hash even when JSON array order differs. Security-relevant
    # values such as properties and schema primary keys must still be included.
    normalized = _normalize_value(graph_data)
    if not isinstance(normalized, dict):
        return normalized

    schema_primary_keys: dict[str, list[str]] = {}
    if schema_summary:
        for vertex_label in schema_summary.get("vertexlabels", []):
            if isinstance(vertex_label, dict):
                name = vertex_label.get("name")
                primary_keys = vertex_label.get("primary_keys")
                if isinstance(name, str) and isinstance(primary_keys, list):
                    schema_primary_keys[name] = primary_keys

    vertices = normalized.get("vertices")
    if isinstance(vertices, list):
        normalized["vertices"] = sorted(
            vertices,
            key=lambda vertex: _vertex_sort_key(vertex, schema_primary_keys),
        )

    edges = normalized.get("edges")
    if isinstance(edges, list):
        normalized["edges"] = sorted(edges, key=_edge_sort_key)

    return normalized


def _schema_vertex_info(raw_schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    info: dict[str, dict[str, Any]] = {}
    for vertex_label in raw_schema.get("vertexlabels", []):
        if not isinstance(vertex_label, dict):
            continue
        name = vertex_label.get("name")
        if isinstance(name, str):
            info[name] = {
                "id": vertex_label.get("id"),
                "id_strategy": str(
                    vertex_label.get("id_strategy")
                    or vertex_label.get("idStrategy")
                    or "PRIMARY_KEY"
                ).upper(),
                "primary_keys": _primary_key_names(vertex_label),
            }
    return info


def _canonical_primary_key_id(
    label: str,
    values: tuple[Any, ...],
    vertex_info: dict[str, dict[str, Any]],
) -> str | None:
    label_id = vertex_info.get(label, {}).get("id")
    if label_id is None:
        return None
    return f"{label_id}:{'!'.join(str(value) for value in values)}"


def _vertex_backend_id(
    vertex: dict[str, Any],
    vertex_info: dict[str, dict[str, Any]],
) -> Any:
    # A HugeGraph PRIMARY_KEY vertex backend ID combines the label ID and primary-key
    # value. Filling in IDs before import lets endpoints reliably reference vertices
    # created in the same payload.
    explicit_id = vertex.get("id")
    if _identity_value_present(explicit_id):
        return explicit_id

    label = vertex.get("label")
    props = vertex.get("properties")
    if not isinstance(label, str) or not isinstance(props, dict):
        return None

    primary_keys = vertex_info.get(label, {}).get("primary_keys", [])
    if not primary_keys:
        return None
    if not all(
        pk in props and _identity_value_present(props.get(pk)) for pk in primary_keys
    ):
        return None

    values = tuple(props.get(pk) for pk in primary_keys)
    return _canonical_primary_key_id(label, values, vertex_info)


def _vertex_identity_map(
    vertices: list[Any],
    raw_schema: dict[str, Any],
) -> tuple[dict[tuple[str, str, Any], Any], dict[str, list[str]]]:
    # Build a mapping from user-expressible identities to HugeGraph backend IDs.
    # A vertex may have an explicit ID, a PRIMARY_KEY backend ID, and a primary-key
    # tuple; resolving any of them must target the same backend vertex.
    vertex_info = _schema_vertex_info(raw_schema)
    schema_primary_keys = {
        label: info.get("primary_keys", []) for label, info in vertex_info.items()
    }
    identities: dict[tuple[str, str, Any], Any] = {}

    for vertex in vertices:
        if not isinstance(vertex, dict):
            continue
        label = vertex.get("label")
        if not isinstance(label, str):
            continue

        backend_id = _vertex_backend_id(vertex, vertex_info)
        if _identity_value_present(backend_id):
            vertex.setdefault("id", backend_id)
            identities[(label, "id", backend_id)] = backend_id

        explicit_id = vertex.get("id")
        if _identity_value_present(explicit_id):
            identities[(label, "id", explicit_id)] = backend_id or explicit_id

        props = vertex.get("properties")
        primary_keys = schema_primary_keys.get(label, [])
        if (
            isinstance(props, dict)
            and primary_keys
            and all(
                pk in props and _identity_value_present(props.get(pk))
                for pk in primary_keys
            )
        ):
            values = tuple(props.get(pk) for pk in primary_keys)
            identities[(label, "pk", values)] = backend_id or explicit_id

    return identities, schema_primary_keys


def _endpoint_backend_id(
    label: str,
    value: Any,
    identities: dict[tuple[str, str, Any], Any],
    schema_primary_keys: dict[str, list[str]],
    vertex_info: dict[str, dict[str, Any]],
) -> Any:
    # Resolve endpoints against vertices in the current payload first, so batch
    # imports can create vertices before edges without requiring backend IDs upfront.
    endpoint_identities, _missing_pk = _endpoint_identities(
        label,
        value,
        schema_primary_keys,
    )
    for identity in endpoint_identities:
        if identity in identities:
            return identities[identity]

    if isinstance(value, dict):
        explicit_id = value.get("id")
        if _identity_value_present(explicit_id):
            return explicit_id

        primary_keys = schema_primary_keys.get(label, [])
        if primary_keys and all(
            pk in value and _identity_value_present(value.get(pk))
            for pk in primary_keys
        ):
            values = tuple(value.get(pk) for pk in primary_keys)
            return _canonical_primary_key_id(label, values, vertex_info)
        return None

    if _identity_value_present(value):
        return value
    return None


def _prepare_graph_import_data(
    graph_data: dict[str, Any],
    live_schema: dict[str, Any],
) -> dict[str, Any]:
    # HugeGraph-AI's graph-import endpoint requires outV/inV/outVLabel/inVLabel.
    # MCP exposes the friendlier source/target fields, so convert them before writing.
    prepared = deepcopy(graph_data)
    raw_schema = _schema_payload(live_schema) or {}
    vertex_info = _schema_vertex_info(raw_schema)
    vertices = prepared.get("vertices") or []
    edges = prepared.get("edges") or []
    identities, schema_primary_keys = _vertex_identity_map(vertices, raw_schema)

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src_label, source = _edge_endpoint(edge, "source")
        tgt_label, target = _edge_endpoint(edge, "target")
        edge.setdefault("properties", {})

        if isinstance(src_label, str):
            source_id = _endpoint_backend_id(
                src_label,
                source,
                identities,
                schema_primary_keys,
                vertex_info,
            )
            if _identity_value_present(source_id):
                edge["outV"] = source_id
            edge.setdefault("outVLabel", src_label)

        if isinstance(tgt_label, str):
            target_id = _endpoint_backend_id(
                tgt_label,
                target,
                identities,
                schema_primary_keys,
                vertex_info,
            )
            if _identity_value_present(target_id):
                edge["inV"] = target_id
            edge.setdefault("inVLabel", tgt_label)

    return prepared


def validate_graph_payload(
    graph_data: Any,
    live_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """校验 graph_data (vertices/edges) 与 live schema 的兼容性。

    覆盖：label 存在性、properties 字段合法性、主键完整性、
    边端点可解析性、类型匹配、重复检测、索引建议。
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(graph_data, dict):
        return {
            "valid": False,
            "errors": ["graph_data must be an object"],
            "warnings": warnings,
        }

    vertices = graph_data.get("vertices")
    edges = graph_data.get("edges")

    if not isinstance(vertices, list):
        errors.append("vertices must be a list")
    if not isinstance(edges, list):
        errors.append("edges must be a list")

    schema_vlabels: set[str] = set()
    schema_props: dict[str, set[str]] = {}
    schema_primary_keys: dict[str, list[str]] = {}
    schema_id_strategies: dict[str, str] = {}
    schema_property_specs: dict[str, tuple[str, str]] = {}
    schema_elabels: dict[str, dict[str, Any]] = {}
    schema_eprops: dict[str, set[str]] = {}
    indexed_labels = {"VERTEX": set(), "EDGE": set()}
    raw = _schema_payload(live_schema) if live_schema is not None else None
    schema_available = raw is not None
    if schema_available:
        # Reduce the live schema to a label -> properties/primary-keys/types table.
        # Later validation uses this snapshot to avoid inconsistent repeated reads.
        schema_property_specs = _property_specs(raw)
        for vl in raw.get("vertexlabels", []):
            if not isinstance(vl, dict):
                continue
            name = vl.get("name")
            if name:
                schema_vlabels.add(name)
                schema_props[name] = _property_names(vl.get("properties", []))
                schema_primary_keys[name] = _primary_key_names(vl)
                schema_id_strategies[name] = str(
                    vl.get("id_strategy") or vl.get("idStrategy") or "PRIMARY_KEY"
                ).upper()
        for el in raw.get("edgelabels", []):
            if not isinstance(el, dict):
                continue
            name = el.get("name")
            if isinstance(name, str):
                schema_elabels[name] = el
                schema_eprops[name] = _property_names(el.get("properties", []))
        indexed_labels = _indexed_labels(raw)

    vertex_labels: set[str] = set()
    vertex_identity_index: dict[tuple[str, str, Any], int] = {}
    if isinstance(vertices, list):
        for idx, vertex in enumerate(vertices):
            if not isinstance(vertex, dict):
                errors.append(f"vertex {idx} must be an object")
                continue
            label = vertex.get("label")
            if label in (None, ""):
                errors.append(f"vertex {idx} missing required field: label")
                continue
            vertex_labels.add(label)
            if schema_available and label not in schema_vlabels:
                errors.append(f"vertex {idx} label '{label}' does not exist in schema")

            props = vertex.get("properties")
            if isinstance(props, dict):
                schema_prop_names = schema_props.get(label, set())
                for prop_name, prop_value in props.items():
                    if prop_value is None or prop_value == "":
                        warnings.append(
                            f"vertex {idx} property '{prop_name}' has empty value"
                        )
                    if (
                        schema_available
                        and label in schema_props
                        and prop_name not in schema_prop_names
                    ):
                        errors.append(
                            f"vertex {idx} property '{prop_name}' does not exist on label '{label}'"
                        )
                    value_error = _property_value_error(
                        item_kind="vertex",
                        item_index=idx,
                        property_name=prop_name,
                        value=prop_value,
                        spec=schema_property_specs.get(prop_name),
                    )
                    if value_error:
                        errors.append(value_error)
            primary_keys = schema_primary_keys.get(label, [])
            id_strategy = schema_id_strategies.get(label)
            explicit_id = vertex.get("id")
            if id_strategy == "CUSTOMIZE_STRING":
                if not _identity_value_present(explicit_id):
                    errors.append(
                        f"vertex {idx} missing required id for CUSTOMIZE_STRING label '{label}'"
                    )
                elif not isinstance(explicit_id, str):
                    errors.append(
                        f"vertex {idx} id for CUSTOMIZE_STRING label '{label}' must be a string, "
                        f"got {type(explicit_id).__name__}"
                    )
            elif id_strategy == "CUSTOMIZE_NUMBER":
                if not _identity_value_present(explicit_id):
                    errors.append(
                        f"vertex {idx} missing required id for CUSTOMIZE_NUMBER label '{label}'"
                    )
                elif not isinstance(explicit_id, int) or isinstance(explicit_id, bool):
                    errors.append(
                        f"vertex {idx} id for CUSTOMIZE_NUMBER label '{label}' must be an integer, "
                        f"got {type(explicit_id).__name__}"
                    )
            if primary_keys:
                # PRIMARY_KEY labels must provide complete primary keys; otherwise HugeGraph
                # cannot construct a stable ID and later endpoint resolution may fail.
                if not isinstance(props, dict):
                    props = {}
                for pk in primary_keys:
                    if pk not in props or not _identity_value_present(props.get(pk)):
                        errors.append(
                            f"vertex {idx} missing primary key value for label '{label}': {pk}"
                        )
                if all(
                    pk in props and _identity_value_present(props.get(pk))
                    for pk in primary_keys
                ):
                    identity = (
                        label,
                        "pk",
                        tuple(props.get(pk) for pk in primary_keys),
                    )
                    if identity in vertex_identity_index:
                        errors.append(
                            f"vertex {idx} duplicate primary key identity for label '{label}': "
                            f"values={tuple(props.get(pk) for pk in primary_keys)} "
                            f"already used by vertex {vertex_identity_index[identity]}"
                        )
                    else:
                        vertex_identity_index[identity] = idx
            if _identity_value_present(explicit_id):
                # A payload must not contain duplicate IDs or primary-key identities, preventing
                # endpoint resolution from targeting an ambiguous vertex.
                identity = (label, "id", explicit_id)
                if identity in vertex_identity_index:
                    errors.append(
                        f"vertex {idx} duplicate id '{explicit_id}' for label '{label}' "
                        f"already used by vertex {vertex_identity_index[identity]}"
                    )
                else:
                    vertex_identity_index[identity] = idx

    edge_labels: set[str] = set()
    if isinstance(edges, list):
        for idx, edge in enumerate(edges):
            if not isinstance(edge, dict):
                errors.append(f"edge {idx} must be an object")
                continue
            label = edge.get("label")
            src_label, source = _edge_endpoint(edge, "source")
            tgt_label, target = _edge_endpoint(edge, "target")
            if _has_mixed_endpoint_forms(edge, "source"):
                errors.append(
                    f"edge {idx} mixes source and outV endpoint forms; use either source/source_label or outV/outVLabel, not both"
                )
            if _has_mixed_endpoint_forms(edge, "target"):
                errors.append(
                    f"edge {idx} mixes target and inV endpoint forms; use either target/target_label or inV/inVLabel, not both"
                )
            if label in (None, ""):
                errors.append(f"edge {idx} missing required field: label")
            if src_label in (None, ""):
                errors.append(f"edge {idx} missing required field: source_label")
            if tgt_label in (None, ""):
                errors.append(f"edge {idx} missing required field: target_label")
            if label:
                edge_labels.add(label)
                if schema_available and label not in schema_elabels:
                    errors.append(
                        f"edge {idx} label '{label}' does not exist in schema"
                    )
            if schema_available:
                if src_label and src_label not in schema_vlabels:
                    errors.append(
                        f"edge {idx} source_label '{src_label}' does not exist in schema"
                    )
                if tgt_label and tgt_label not in schema_vlabels:
                    errors.append(
                        f"edge {idx} target_label '{tgt_label}' does not exist in schema"
                    )
            if label and label in schema_elabels:
                schema_edge = schema_elabels[label]
                expected_src = _edge_schema_endpoint_label(schema_edge, "source")
                expected_tgt = _edge_schema_endpoint_label(schema_edge, "target")
                if src_label and expected_src and src_label != expected_src:
                    errors.append(
                        f"edge {idx} source_label '{src_label}' does not match edge label '{label}' source_label '{expected_src}'"
                    )
                if tgt_label and expected_tgt and tgt_label != expected_tgt:
                    errors.append(
                        f"edge {idx} target_label '{tgt_label}' does not match edge label '{label}' target_label '{expected_tgt}'"
                    )
            props = edge.get("properties")
            if isinstance(props, dict):
                schema_prop_names = schema_eprops.get(label, set())
                for prop_name, prop_value in props.items():
                    if prop_value is None or prop_value == "":
                        warnings.append(
                            f"edge {idx} property '{prop_name}' has empty value"
                        )
                    if (
                        schema_available
                        and label in schema_eprops
                        and prop_name not in schema_prop_names
                    ):
                        errors.append(
                            f"edge {idx} property '{prop_name}' does not exist on label '{label}'"
                        )
                    value_error = _property_value_error(
                        item_kind="edge",
                        item_index=idx,
                        property_name=prop_name,
                        value=prop_value,
                        spec=schema_property_specs.get(prop_name),
                    )
                    if value_error:
                        errors.append(value_error)
            if source is None and target is None:
                continue
            if source is None:
                errors.append(f"edge {idx} has target but missing source")
            if target is None:
                errors.append(f"edge {idx} has source but missing target")
            for endpoint_name, endpoint_label, endpoint_value in (
                ("source", src_label, source),
                ("target", tgt_label, target),
            ):
                if endpoint_value is None or not isinstance(endpoint_label, str):
                    continue
                identities, missing_pk = _endpoint_identities(
                    endpoint_label,
                    endpoint_value,
                    schema_primary_keys,
                )
                if missing_pk:
                    # Report an error when an endpoint object lacks a primary key; do not fall back
                    # to string matching, which could silently write invalid dangling edges.
                    errors.append(
                        f"edge {idx} {endpoint_name} endpoint missing primary key for label '{endpoint_label}': {missing_pk}"
                    )
                    continue
                if not identities:
                    # No missing_pk but no identities is a degraded state; report it explicitly
                    # instead of silently accepting it, such as when endpoint_value is {}.
                    errors.append(
                        f"edge {idx} {endpoint_name} endpoint has no resolvable identity "
                        f"for label '{endpoint_label}': {_format_endpoint_value(endpoint_value)}"
                    )
                    continue
                matched_vertex_indices = {
                    vertex_identity_index[identity]
                    for identity in identities
                    if identity in vertex_identity_index
                }
                if len(matched_vertex_indices) > 1:
                    errors.append(
                        f"edge {idx} {endpoint_name} scalar endpoint is ambiguous for "
                        f"label '{endpoint_label}': {_format_endpoint_value(endpoint_value)} "
                        "matches different vertices by id and primary key"
                    )

    if isinstance(edges, list):
        edge_pairs = []
        for e in edges:
            if isinstance(e, dict):
                edge_pairs.append(
                    (
                        e.get("label"),
                        e.get("source_label"),
                        e.get("target_label"),
                        e.get("source"),
                        e.get("target"),
                    )
                )
        if len(edge_pairs) > len({json.dumps(p, sort_keys=True) for p in edge_pairs}):
            warnings.append("potential duplicate edges detected")

    if indexed_labels["VERTEX"] or indexed_labels["EDGE"]:
        for label in sorted(vertex_labels - indexed_labels["VERTEX"]):
            warnings.append(f"no vertex index found in schema for label: {label}")
        for label in sorted(edge_labels - indexed_labels["EDGE"]):
            warnings.append(f"no edge index found in schema for label: {label}")
    elif vertex_labels or edge_labels:
        warnings.append("verify that appropriate indexes exist for queried properties")

    return {
        "valid": not bool(errors),
        "errors": errors,
        "warnings": warnings,
    }


def calculate_plan_hash(
    graph_data: dict[str, Any],
    live_schema: dict[str, Any] | None = None,
) -> str:
    """计算图数据导入的计划哈希（兼容旧接口）。"""
    from hugegraph_mcp.plan_hash import compute_payload_digest

    cfg = MCPConfig.from_env()
    schema_summary = normalized_schema_summary(live_schema)
    payload = {
        "graph_data": _normalize_graph_data(graph_data, schema_summary),
        "graph": cfg.graph,
        "graphspace": cfg.graphspace,
    }
    if schema_summary is not None:
        payload["schema_summary"] = schema_summary
    return compute_payload_digest(payload)


def _fetch_live_schema() -> dict[str, Any] | None:
    return fetch_live_schema_or_none()


def ingest_graph_data(
    graph_data: dict[str, Any],
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> dict[str, Any]:
    """兼容入口：通过 HugeGraph-AI /graph-import 导入图数据。

    Public MCP V1 `import_graph_data_tool(mode="ingest")` 不调用此函数；
    它使用 manage_graph_data() 的本地校验、dry-run/hash/confirm 和 direct Gremlin 写入。
    """

    return ingest_graph_data_via_ai(
        graph_data=graph_data,
        dry_run=dry_run,
        confirm=confirm,
        plan_hash=plan_hash,
        nonce=nonce,
        expires_at=expires_at,
    )


def ingest_graph_data_via_ai(
    graph_data: dict[str, Any],
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> dict[str, Any]:
    """AI-backed 图数据导入 — legacy/internal 安全链入口。

    dry_run=True: schema 校验 + plan_hash 生成，不写入
    dry_run=False + confirm=True + plan_hash 匹配: 执行写入
    nonce/expires_at: dry_run 返回的 plan_context 中的字段，confirm 时必须传回
    """
    if not dry_run and confirm:
        replay_error = replayed_plan_error(nonce)
        if replay_error is not None:
            return replay_error

    from hugegraph_mcp.write_limits import (
        graph_data_operation_count,
        write_limit_envelope,
    )

    limit_error = write_limit_envelope(
        graph_data_operation_count(graph_data),
        graph_data,
    )
    if limit_error is not None:
        return limit_error

    live_schema = _fetch_live_schema()
    if live_schema is None:
        return envelope_err(
            ErrorType.CONNECTION_FAILED,
            "Cannot read live schema from HugeGraph Server. Schema validation is required before import.",
            suggestion="Ensure HugeGraph Server is running and accessible, then retry.",
            retryable=True,
        )
    validation = validate_graph_payload(graph_data, live_schema=live_schema)
    if not validation["valid"]:
        return envelope_err(
            ErrorType.SCHEMA_MISMATCH,
            "Graph data does not match live schema.",
            details={"errors": validation["errors"]},
        )

    from hugegraph_mcp.plan_hash import (
        build_plan_context,
        compute_payload_digest,
        compute_plan_hash,
    )

    mutation_summary = _mutation_summary(graph_data)
    warnings = validation["warnings"]

    # Build the target-bound plan context, including url, user, readonly, nonce, and expires_at.
    cfg = MCPConfig.from_env()
    schema_summary = normalized_schema_summary(live_schema)
    payload_for_digest = {
        "graph_data": _normalize_graph_data(graph_data, schema_summary),
        "graph": cfg.graph,
        "graphspace": cfg.graphspace,
    }
    if schema_summary is not None:
        payload_for_digest["schema_summary"] = schema_summary

    payload_digest = compute_payload_digest(payload_for_digest)
    schema_hash = compute_payload_digest(schema_summary) if schema_summary else None
    plan_context, _ = build_plan_context(
        tool_name="ingest_graph_data",
        mode="import",
        payload_digest=payload_digest,
        schema_hash=schema_hash,
        nonce=nonce,
    )

    if dry_run:
        plan_hash_value = compute_plan_hash(plan_context)
        payload = {
            "plan_hash": plan_hash_value,
            "plan_context": {
                "nonce": plan_context.nonce,
                "expires_at": plan_context.expires_at,
                "graph_url": plan_context.graph_url,
                "graph_name": plan_context.graph_name,
                "graphspace": plan_context.graphspace,
                "principal": plan_context.principal,
                "readonly": plan_context.readonly,
            },
            "mutation_summary": mutation_summary,
            "warnings": warnings,
            "confirmable": True,
        }
        next_actions: list[str] = []
        if MCPConfig.from_env().is_readonly():
            payload, readonly_warnings, next_actions = mark_readonly_preview(
                payload,
                warning=(
                    "This dry-run was generated while HUGEGRAPH_MCP_READONLY=true. "
                    "Set HUGEGRAPH_MCP_READONLY=false and rerun dry_run before confirming."
                ),
                next_action=(
                    "Set HUGEGRAPH_MCP_READONLY=false and rerun dry_run before confirm."
                ),
            )
            warnings = list(warnings) + readonly_warnings
        else:
            issue_error = issue_plan(plan_context, plan_hash_value)
            if issue_error is not None:
                return issue_error
        return envelope_ok(payload, warnings=warnings, next_actions=next_actions)

    violation = guard(Capability.DATA_WRITE)
    if violation is not None:
        return violation

    if not confirm:
        return envelope_err(
            ErrorType.CONFIRM_REQUIRED,
            "Graph data import requires confirm=True after a dry_run.",
            suggestion="Run dry_run=True, review mutation_summary and warnings, then pass confirm=True with the returned plan_hash.",
        )

    # Validate against the target by rereading config and schema and recomputing the hash.
    # nonce must be returned from the plan_context produced by dry_run.
    valid, error_type, details = verify_and_consume_plan(
        submitted_hash=plan_hash,
        tool_name="ingest_graph_data",
        mode="import",
        payload_digest=payload_digest,
        schema_hash=schema_hash,
        nonce=nonce or plan_context.nonce,
        expires_at=expires_at,
    )
    if not valid:
        return plan_hash_error(
            error_type=error_type,
            details=details,
            mismatch_message=(
                "Plan hash mismatch: config, schema, or payload has changed since dry_run."
            ),
            expired_message=(
                "Plan has expired. Run dry_run=True again and use the returned plan_hash."
            ),
            suggestion="Run dry_run=True again and use the returned plan_hash.",
        )

    batch_id = f"batch-{uuid4().hex[:12]}"
    request_id = f"req-{uuid4().hex[:12]}"
    cfg = MCPConfig.from_env()
    planned = mutation_summary

    import_data = _prepare_graph_import_data(graph_data, live_schema)
    # Actual writes still use HugeGraph-AI's graph-import HTTP endpoint. MCP handles
    # schema validation, safety confirmation, and payload normalization rather than
    # invoking the hugegraph-llm import flow directly.
    try:
        ai_result = post(
            "/graph-import",
            json={"data": json.dumps(import_data, sort_keys=True), "schema": cfg.graph},
        )
    except Exception as exc:  # noqa: BLE001 - normalize import boundary failures
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            f"Import execution failed: {exc}",
            details=_import_error_result(
                planned=planned, batch_id=batch_id, request_id=request_id, cfg=cfg
            ),
        )

    if not ai_result.get("ok"):
        # M5: Normalize AI error responses instead of passing through raw results.
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            "HugeGraph-AI import returned an error.",
            details=_normalize_import_result(
                ai_result=None,
                planned=planned,
                batch_id=batch_id,
                request_id=request_id,
                cfg=cfg,
            ),
        )

    import_result = _unwrap_ai_payload(ai_result.get("data"))
    if isinstance(import_result, dict) and import_result.get("ok") is False:
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            "HugeGraph-AI import returned an error in payload.",
            details=_normalize_import_result(
                ai_result=None,
                planned=planned,
                batch_id=batch_id,
                request_id=request_id,
                cfg=cfg,
            ),
        )

    # M5: Normalize the import result.
    normalized = _normalize_import_result(
        ai_result=import_result,
        planned=planned,
        batch_id=batch_id,
        request_id=request_id,
        cfg=cfg,
    )

    if normalized.get("status") != "success":
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            "Graph data import did not complete successfully.",
            retryable=bool(normalized.get("retryable")),
            details=normalized,
            warnings=normalized.get("warnings", []),
        )

    return envelope_ok(normalized, warnings=normalized.get("warnings", []))


def _mutation_summary(graph_data: dict[str, Any]) -> dict[str, int]:
    return {
        "vertices": len(graph_data.get("vertices") or []),
        "edges": len(graph_data.get("edges") or []),
    }


def _unwrap_ai_payload(data: Any) -> Any:
    if isinstance(data, dict) and "ok" in data and "data" in data:
        if data.get("ok") is False:
            return data
        return data.get("data")
    return data


def _normalize_import_result(
    ai_result: Any,
    planned: dict[str, int],
    batch_id: str,
    request_id: str,
    cfg: MCPConfig,
) -> dict[str, Any]:
    """将 AI 导入结果规范化为 V1 标准格式。

    M5: success / partial / degraded / error
    """
    target = {
        "graph_url": cfg.url,
        "graph_name": cfg.graph,
        "graphspace": cfg.graphspace or "DEFAULT",
    }

    if ai_result is None or (
        isinstance(ai_result, dict) and ai_result.get("ok") is False
    ):
        return {
            "status": "error",
            "planned": planned,
            "written": {"vertices": 0, "edges": 0},
            "failed_items": [],
            "warnings": [],
            "retryable": False,
            "compensation_suggestions": ["Retry the import with dry_run first."],
            "target": target,
            "batch_id": batch_id,
            "request_id": request_id,
        }

    written, count_source = _extract_written_counts(ai_result, planned)
    failed_items = _extract_failed_items(ai_result)
    warnings = _extract_import_warnings(ai_result)
    remote_success = ai_result.get("success") if isinstance(ai_result, dict) else None
    remote_status = (
        str(ai_result.get("status")).lower()
        if isinstance(ai_result, dict) and ai_result.get("status") is not None
        else None
    )

    if written is None:
        if failed_items:
            written = {"vertices": 0, "edges": 0}
            status = "error" if remote_success is False else "degraded"
            warnings.append(
                "HugeGraph-AI import returned failures without explicit written counts."
            )
        elif remote_success is False:
            written = {"vertices": 0, "edges": 0}
            status = "error"
            warnings.append(
                "HugeGraph-AI import reported failure without explicit written counts."
            )
        else:
            written = {"vertices": 0, "edges": 0}
            status = (
                remote_status
                if remote_status in {"partial", "error", "degraded"}
                else "degraded"
            )
            warnings.append(
                "HugeGraph-AI import did not return explicit written counts; write outcome is unknown."
            )
    elif remote_success is False and (written["vertices"] > 0 or written["edges"] > 0):
        status = "partial"
    elif remote_success is False:
        status = "error"
    elif remote_status in {"partial", "error", "degraded"}:
        status = remote_status
    elif written == planned and not failed_items:
        status = "success"
    elif written["vertices"] > 0 or written["edges"] > 0:
        status = "partial"
    elif failed_items:
        status = "error"
    else:
        status = "degraded"

    if count_source == "total":
        warnings.append(
            "HugeGraph-AI import returned only a total written count; vertices/edges were estimated from the planned import order."
        )

    return {
        "status": status,
        "planned": planned,
        "written": written,
        "failed_items": failed_items,
        "warnings": warnings,
        "retryable": False,
        "compensation_suggestions": (
            ["Review failed_items, inspect graph state, and run a fresh dry-run."]
            if status in {"partial", "degraded", "error"}
            else []
        ),
        "target": target,
        "batch_id": batch_id,
        "request_id": request_id,
    }


def _extract_written_counts(
    ai_result: Any, planned: dict[str, int]
) -> tuple[dict[str, int] | None, str | None]:
    """从 AI 结果中提取写入计数。

    返回 (counts, source)，无法识别时 counts 为 None。source="total" 表示
    只有总数，vertices/edges 是按导入顺序估算出来的。
    """
    if not isinstance(ai_result, dict):
        return None, None

    # Common AI response formats.
    for key in ("written", "imported", "created", "result"):
        data = ai_result.get(key)
        if isinstance(data, dict):
            verts = data.get("vertices")
            if verts is None:
                verts = data.get("vertex_count")
            edges = data.get("edges")
            if edges is None:
                edges = data.get("edge_count")
            if verts is not None or edges is not None:
                return {
                    "vertices": _safe_int(verts),
                    "edges": _safe_int(edges),
                }, "explicit"

    # Counts provided directly at the top level.
    verts = ai_result.get("vertices_written")
    if verts is None:
        verts = ai_result.get("vertex_count")
    edges = ai_result.get("edges_written")
    if edges is None:
        edges = ai_result.get("edge_count")
    if verts is not None or edges is not None:
        return {
            "vertices": _safe_int(verts),
            "edges": _safe_int(edges),
        }, "explicit"

    for key in ("inserted", "total_inserted", "created_count", "imported_count"):
        if key in ai_result:
            return _split_total_written(_safe_int(ai_result.get(key)), planned), "total"

    return None, None


def _safe_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _split_total_written(total: int, planned: dict[str, int]) -> dict[str, int]:
    total = max(0, total)
    planned_vertices = max(0, int(planned.get("vertices", 0)))
    planned_edges = max(0, int(planned.get("edges", 0)))
    vertices = min(planned_vertices, total)
    edges = min(planned_edges, max(0, total - vertices))
    return {"vertices": vertices, "edges": edges}


def _extract_failed_items(ai_result: Any) -> list[dict[str, Any]]:
    """从 AI 结果中提取失败项，统一为对象数组。"""
    if not isinstance(ai_result, dict):
        return []

    for key in ("failed_items", "errors", "failures"):
        items = ai_result.get(key)
        if isinstance(items, list):
            normalized = []
            for item in items[:100]:
                if isinstance(item, dict):
                    normalized.append(item)
                elif isinstance(item, str):
                    normalized.append({"message": item})
                else:
                    normalized.append({"item": str(item)})
            return normalized

    return []


def _extract_import_warnings(ai_result: Any) -> list[str]:
    if not isinstance(ai_result, dict):
        return []
    raw_warnings = ai_result.get("warnings")
    if not isinstance(raw_warnings, list):
        return []
    return [str(warning) for warning in raw_warnings[:100]]


def _import_error_result(
    planned: dict[str, int],
    batch_id: str,
    request_id: str,
    cfg: MCPConfig,
) -> dict[str, Any]:
    """构建导入执行错误的规范化结果。"""
    return {
        "status": "error",
        "planned": planned,
        "written": {"vertices": 0, "edges": 0},
        "failed_items": [],
        "warnings": ["Import execution failed before any writes."],
        "retryable": False,
        "compensation_suggestions": ["Check HugeGraph-AI service availability."],
        "target": {
            "graph_url": cfg.url,
            "graph_name": cfg.graph,
            "graphspace": cfg.graphspace or "DEFAULT",
        },
        "batch_id": batch_id,
        "request_id": request_id,
    }
