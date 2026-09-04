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

"""Typed graph data query tool for v2_core."""

import json
from typing import Any

from pyhugegraph.client import PyHugeClient
from pyhugegraph.utils.id_format import format_vertex_id

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.error_mapping import classify_hugegraph_exception
from hugegraph_mcp.hugegraph_client import build_hugegraph_client

TARGETS = frozenset({"vertex", "edge"})
OPERATIONS = frozenset({"get_by_id", "get_by_ids", "page", "condition"})
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
VALID_DIRECTIONS = frozenset({"OUT", "IN", "BOTH"})


def _graph_manager():
    return build_hugegraph_client(MCPConfig.from_env(), client_cls=PyHugeClient).graph()


def query_graph_data(
    *,
    target: str,
    operation: str,
    id: Any = None,
    ids: list[Any] | None = None,
    label: str | None = None,
    properties: dict[str, Any] | None = None,
    limit: int | None = None,
    page: str | None = None,
    vertex_id: Any = None,
    direction: str | None = None,
) -> dict[str, Any]:
    """Query vertices or edges through HugeGraph GraphManager.

    Capability: READ.

    target values: vertex, edge.
    operation values:
    - get_by_id: requires id.
    - get_by_ids: requires non-empty ids, duplicates are ignored with a warning.
    - page: vertex requires label; edge may use label and/or vertex_id+direction.
    - condition: exact-match properties only; no full graph Gremlin fallback.

    limit defaults to 100 and rejects values above 500.
    Edge page/condition with vertex_id must also pass direction=OUT|IN|BOTH.
    """

    warnings: list[str] = []
    validation_error = _validate_inputs(
        target=target,
        operation=operation,
        id=id,
        ids=ids,
        label=label,
        properties=properties,
        limit=limit,
        page=page,
        vertex_id=vertex_id,
        direction=direction,
    )
    if validation_error is not None:
        return validation_error

    bounded_limit = DEFAULT_LIMIT if limit is None else int(limit)
    normalized_direction = _normalize_direction(direction)

    try:
        normalized_ids = _normalize_ids(ids, warnings, target=target) if operation == "get_by_ids" else []
        manager = _graph_manager()
        result, next_page = _execute_query(
            manager=manager,
            target=target,
            operation=operation,
            id=id,
            ids=normalized_ids,
            label=label,
            properties=properties,
            limit=bounded_limit,
            page=page,
            vertex_id=vertex_id,
            direction=normalized_direction,
        )
    except Exception as exc:
        return _query_error(exc)

    items = _normalize_items(result)
    return envelope_ok(
        {
            "target": target,
            "operation": operation,
            "items": items,
            "count": len(items),
            "page": page,
            "next_page": next_page,
            "limit": bounded_limit,
        },
        warnings=warnings,
        next_actions=[
            "Use mutate_graph_properties_tool dry_run before changing returned items.",
            "If HugeGraph reports no index for condition queries, create indexes in the P0b index workflow.",
        ],
    )


def _validate_inputs(
    *,
    target: str,
    operation: str,
    id: Any,
    ids: list[Any] | None,
    label: str | None,
    properties: dict[str, Any] | None,
    limit: int | None,
    page: str | None,
    vertex_id: Any,
    direction: str | None,
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
            "Use one of: get_by_id, get_by_ids, page, condition.",
            {"operation": operation},
        )
    limit_error = _validate_limit(limit)
    if limit_error is not None:
        return limit_error
    if operation == "get_by_id" and _is_blank(id):
        return _validation_error(
            "id is required for operation='get_by_id'.",
            "Pass the exact vertex or edge id.",
            {"operation": operation},
        )
    if target == "vertex" and operation == "get_by_id":
        id_error = _validate_vertex_id(id, field="id")
        if id_error is not None:
            return id_error
    if operation == "get_by_ids":
        if not isinstance(ids, list) or not ids:
            return _validation_error(
                "ids must be a non-empty list for operation='get_by_ids'.",
                "Pass one or more exact vertex or edge ids.",
                {"operation": operation},
            )
        if any(_is_blank(item) for item in ids):
            return _validation_error(
                "ids cannot contain empty values.",
                "Remove null or empty ids before querying.",
                {"ids": ids},
            )
        if len(ids) > MAX_LIMIT:
            return _validation_error(
                f"ids length exceeds maximum {MAX_LIMIT}.",
                "Split the request into smaller batches.",
                {"ids_length": len(ids), "max": MAX_LIMIT},
            )
        if target == "vertex":
            for index, item in enumerate(ids):
                id_error = _validate_vertex_id(item, field=f"ids[{index}]")
                if id_error is not None:
                    return id_error
    if operation == "page" and target == "vertex" and _is_blank(label):
        return _validation_error(
            "label is required for vertex page queries.",
            "Pass a vertex label or use operation='condition'.",
            {"target": target, "operation": operation},
        )
    if properties is not None and not isinstance(properties, dict):
        return _validation_error(
            "properties must be an object when provided.",
            "Pass exact-match property filters as a JSON object.",
            {"properties_type": type(properties).__name__},
        )
    if operation == "condition" and not properties:
        return _validation_error(
            "properties is required for operation='condition'.",
            "Pass exact-match property filters, or use operation='page' for bounded scans.",
            {"operation": operation, "properties": properties},
        )
    if target == "edge" and operation in {"page", "condition"}:
        if operation == "page" and vertex_id is not None and not _is_blank(page):
            return _validation_error(
                "vertex_id and page cannot be combined for edge page queries.",
                (
                    "For a vertex-scoped query, pass vertex_id and direction without "
                    "page. For ordinary pagination, pass page without vertex_id."
                ),
                {"vertex_id": vertex_id, "page": page},
            )
        if vertex_id is not None and direction is None:
            return _validation_error(
                "direction is required when querying edges by vertex_id.",
                "Pass direction='OUT', 'IN', or 'BOTH'.",
                {"vertex_id": vertex_id, "direction": direction},
            )
        if vertex_id is not None and _normalize_direction(direction) is None:
            return _validation_error(
                f"Unsupported direction: {direction!r}.",
                "Pass direction='OUT', 'IN', or 'BOTH'.",
                {"vertex_id": vertex_id, "direction": direction},
            )
        if vertex_id is None and direction is not None:
            return _validation_error(
                "direction requires vertex_id for edge queries.",
                "Pass vertex_id together with direction, or omit direction.",
                {"direction": direction},
            )
    return None


def _validate_vertex_id(value: Any, *, field: str) -> dict[str, Any] | None:
    try:
        format_vertex_id(value)
    except (TypeError, ValueError) as exc:
        return _validation_error(
            f"Invalid vertex id in {field}: {exc!s}",
            "Pass a HugeGraph vertex id as a string, UUID, or Java signed 64-bit integer.",
            {
                "field": field,
                "id_type": type(value).__name__,
                "reason": str(exc),
            },
        )
    return None


def _validate_limit(limit: int | None) -> dict[str, Any] | None:
    if limit is None:
        return None
    try:
        parsed = int(limit)
    except (TypeError, ValueError):
        return _validation_error(
            "limit must be an integer.",
            f"Pass an integer from 1 to {MAX_LIMIT}.",
            {"limit": limit},
        )
    if parsed < 1:
        return _validation_error(
            "limit must be at least 1.",
            f"Pass an integer from 1 to {MAX_LIMIT}.",
            {"limit": limit},
        )
    if parsed > MAX_LIMIT:
        return _validation_error(
            f"limit exceeds maximum {MAX_LIMIT}.",
            "Reduce limit or use page to continue reading.",
            {"limit": limit, "max": MAX_LIMIT},
        )
    return None


def _execute_query(
    *,
    manager,
    target: str,
    operation: str,
    id: Any,
    ids: list[Any],
    label: str | None,
    properties: dict[str, Any] | None,
    limit: int,
    page: str | None,
    vertex_id: Any,
    direction: str | None,
) -> tuple[Any, str | None]:
    if target == "vertex":
        return _execute_vertex_query(
            manager=manager,
            operation=operation,
            id=id,
            ids=ids,
            label=label,
            properties=properties,
            limit=limit,
            page=page,
        )
    return _execute_edge_query(
        manager=manager,
        operation=operation,
        id=id,
        ids=ids,
        label=label,
        properties=properties,
        limit=limit,
        page=page,
        vertex_id=vertex_id,
        direction=direction,
    )


def _execute_vertex_query(
    *,
    manager,
    operation: str,
    id: Any,
    ids: list[Any],
    label: str | None,
    properties: dict[str, Any] | None,
    limit: int,
    page: str | None,
) -> tuple[Any, str | None]:
    if operation == "get_by_id":
        return manager.getVertexById(id), None
    if operation == "get_by_ids":
        return manager.getVerticesById(ids), None
    if operation == "page":
        items, next_page = manager.getVertexByPage(
            label=label,
            limit=limit,
            page=page,
            properties=properties,
        )
        return items, next_page
    get_by_condition = getattr(manager, "getVertexByConditionWithPage", None)
    if get_by_condition is None:
        get_by_condition = manager.getVertexByCondition
    result = get_by_condition(
        label=label or "",
        limit=limit,
        page=page,
        properties=properties,
    )
    if isinstance(result, tuple) and len(result) == 2:
        items, next_page = result
    else:
        items, next_page = result, None
    return items, next_page


def _execute_edge_query(
    *,
    manager,
    operation: str,
    id: Any,
    ids: list[Any],
    label: str | None,
    properties: dict[str, Any] | None,
    limit: int,
    page: str | None,
    vertex_id: Any,
    direction: str | None,
) -> tuple[Any, str | None]:
    if operation == "get_by_id":
        return manager.getEdgeById(id), None
    if operation == "get_by_ids":
        return manager.getEdgesById(ids), None
    items, next_page = manager.getEdgeByPage(
        label=label,
        vertex_id=vertex_id,
        direction=direction,
        limit=limit,
        page=page,
        properties=properties,
    )
    return items, next_page


def _query_error(exc: Exception) -> dict[str, Any]:
    classification = classify_hugegraph_exception(exc)
    next_actions = [
        "Retry with exact id lookup if possible.",
        "For no-index condition queries, create an index in the P0b index workflow.",
    ]
    return envelope_err(
        classification.error_type,
        f"HugeGraph graph data query failed: {exc!s}",
        suggestion=classification.suggestion,
        retryable=classification.retryable,
        source="query_graph_data_tool",
        details={"error": str(exc), "reason": classification.reason},
        next_actions=next_actions,
    )


def _validation_error(
    message: str,
    suggestion: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return envelope_err(
        ErrorType.VALIDATION_ERROR,
        message,
        suggestion=suggestion,
        source="query_graph_data_tool",
        details=details,
    )


def _normalize_items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_plain_item(item) for item in value if item is not None]
    return [_plain_item(value)]


def _plain_item(item: Any) -> dict[str, Any]:
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
    if not result:
        result["value"] = item
    return result


def _normalize_ids(ids: list[Any] | None, warnings: list[str], *, target: str) -> list[Any]:
    seen: set[str] = set()
    normalized: list[Any] = []
    duplicate_count = 0
    for item in ids or []:
        key = _id_dedupe_key(item, target=target)
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        normalized.append(item)
    if duplicate_count:
        warnings.append(f"Ignored {duplicate_count} duplicate id value(s).")
    return normalized


def _id_dedupe_key(item: Any, *, target: str) -> str:
    return json.dumps(
        {"target": target, "type": type(item).__name__, "value": item},
        sort_keys=True,
        default=str,
    )


def _normalize_direction(direction: str | None) -> str | None:
    if direction is None:
        return None
    upper = str(direction).strip().upper()
    return upper if upper in VALID_DIRECTIONS else None


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")
