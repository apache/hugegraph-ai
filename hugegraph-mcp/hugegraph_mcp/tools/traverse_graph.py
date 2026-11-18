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

"""Bounded graph traversal and path analysis tool."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from pyhugegraph.client import PyHugeClient

from hugegraph_mcp.config import MCPConfig, get_effective_config
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.error_mapping import classify_hugegraph_exception
from hugegraph_mcp.hugegraph_client import build_hugegraph_client

OPERATIONS = frozenset({"neighbors", "k_out", "shortest_path", "paths"})
PATH_OPERATIONS = frozenset({"shortest_path", "paths"})
VALID_DIRECTIONS = frozenset({"OUT", "IN", "BOTH"})

MAX_DEPTH_LIMIT = 3
MAX_DEGREE_LIMIT = 64
MAX_CAPACITY_LIMIT = 5000
MAX_TRAVERSE_LIMIT = 100
MAX_TRAVERSE_BYTES = 1024 * 1024
TRAVERSE_DEADLINE_SECONDS = 10.0


def _build_client(cfg: MCPConfig) -> Any:
    return build_hugegraph_client(
        cfg,
        client_cls=PyHugeClient,
        request_timeout_seconds=min(cfg.read_timeout_seconds, TRAVERSE_DEADLINE_SECONDS),
    )


def _is_valid_vid(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        return bool(value.strip())
    return False


def _is_int_in_range(value: Any, *, min_val: int, max_val: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and min_val <= value <= max_val


def _validate_inputs(
    *,
    operation: str,
    source_id: Any,
    target_id: Any,
    direction: str,
    label: str | None,
    max_depth: int,
    max_degree: int,
    capacity: int,
    limit: int | None,
    cfg: MCPConfig,
) -> tuple[dict[str, Any] | None, int]:
    if operation not in OPERATIONS:
        return (
            envelope_err(
                ErrorType.VALIDATION_ERROR,
                f"Unsupported operation {operation!r}; expected one of {sorted(OPERATIONS)}.",
                details={"reason": "invalid_operation", "operation": operation},
            ),
            0,
        )
    if not _is_valid_vid(source_id):
        return (
            envelope_err(
                ErrorType.VALIDATION_ERROR,
                "source_id must be a non-empty string or integer vertex ID.",
                details={"reason": "invalid_source_id"},
            ),
            0,
        )
    if operation in PATH_OPERATIONS:
        if not _is_valid_vid(target_id):
            return (
                envelope_err(
                    ErrorType.VALIDATION_ERROR,
                    f"target_id is required for {operation!r} and must be a non-empty string or integer.",
                    details={"reason": "invalid_target_id"},
                ),
                0,
            )
    elif target_id is not None:
        return (
            envelope_err(
                ErrorType.VALIDATION_ERROR,
                f"target_id is not supported for {operation!r}.",
                details={"reason": "unexpected_target_id"},
            ),
            0,
        )

    if direction not in VALID_DIRECTIONS:
        return (
            envelope_err(
                ErrorType.VALIDATION_ERROR,
                f"direction must be one of {sorted(VALID_DIRECTIONS)}.",
                details={"reason": "invalid_direction", "direction": direction},
            ),
            0,
        )
    if label is not None and (not isinstance(label, str) or not label.strip()):
        return (
            envelope_err(
                ErrorType.VALIDATION_ERROR,
                "label must be a non-empty string when provided.",
                details={"reason": "invalid_label"},
            ),
            0,
        )
    if not _is_int_in_range(max_depth, min_val=1, max_val=MAX_DEPTH_LIMIT):
        return (
            envelope_err(
                ErrorType.VALIDATION_ERROR,
                f"max_depth must be an integer between 1 and {MAX_DEPTH_LIMIT}.",
                details={"reason": "budget_exceeded", "field": "max_depth", "max": MAX_DEPTH_LIMIT},
            ),
            0,
        )
    if not _is_int_in_range(max_degree, min_val=1, max_val=MAX_DEGREE_LIMIT):
        return (
            envelope_err(
                ErrorType.VALIDATION_ERROR,
                f"max_degree must be an integer between 1 and {MAX_DEGREE_LIMIT}.",
                details={"reason": "budget_exceeded", "field": "max_degree", "max": MAX_DEGREE_LIMIT},
            ),
            0,
        )
    if not _is_int_in_range(capacity, min_val=1, max_val=MAX_CAPACITY_LIMIT):
        return (
            envelope_err(
                ErrorType.VALIDATION_ERROR,
                f"capacity must be an integer between 1 and {MAX_CAPACITY_LIMIT}.",
                details={"reason": "budget_exceeded", "field": "capacity", "max": MAX_CAPACITY_LIMIT},
            ),
            0,
        )

    hard_limit = max(1, min(MAX_TRAVERSE_LIMIT, cfg.max_result_items))
    if operation == "shortest_path":
        if limit is not None and limit != 1:
            return (
                envelope_err(
                    ErrorType.VALIDATION_ERROR,
                    "shortest_path only returns 1 path; limit must be 1 or omitted.",
                    details={"reason": "budget_exceeded", "field": "limit", "max": 1},
                ),
                0,
            )
        effective_limit = 1
    else:
        effective_limit = min(20, hard_limit) if limit is None else limit
        if not _is_int_in_range(effective_limit, min_val=1, max_val=hard_limit):
            return (
                envelope_err(
                    ErrorType.VALIDATION_ERROR,
                    f"limit must be an integer between 1 and {hard_limit}.",
                    details={"reason": "budget_exceeded", "field": "limit", "max": hard_limit},
                ),
                0,
            )

    if operation == "neighbors":
        worst_case = 1 + sum(max_degree**depth for depth in range(1, max_depth + 1))
        if worst_case > capacity:
            return (
                envelope_err(
                    ErrorType.VALIDATION_ERROR,
                    f"neighbors admission budget exceeded: "
                    f"1 + sum(max_degree^d) = {worst_case} > capacity ({capacity}).",
                    details={
                        "reason": "admission_budget_exceeded",
                        "estimated_nodes": worst_case,
                        "capacity": capacity,
                    },
                ),
                0,
            )

    return None, effective_limit


def _normalize_result(operation: str, raw: Any, *, effective_limit: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"Expected dict traversal response, got {type(raw).__name__}")
    if operation in {"neighbors", "k_out"}:
        if isinstance(raw.get("vertices"), list):
            items = list(raw["vertices"])[:effective_limit]
        elif isinstance(raw.get("ids"), list):
            items = list(raw["ids"])[:effective_limit]
        else:
            raise ValueError("Traversal response missing 'vertices' or 'ids' list")
        return {"vertices": items, "count": len(items)}
    if operation == "shortest_path":
        if "path" not in raw or not isinstance(raw.get("path"), list):
            raise ValueError("shortest_path response missing 'path' list")
        path = list(raw["path"])
        return {"path": path, "found": bool(path), "count": 1 if path else 0}
    if "paths" not in raw or not isinstance(raw.get("paths"), list):
        raise ValueError("paths response missing 'paths' list")
    paths = list(raw["paths"])[:effective_limit]
    normalized_paths = [list(p.get("objects") or []) if isinstance(p, dict) else list(p) for p in paths]
    return {"paths": normalized_paths, "count": len(normalized_paths)}


def traverse_graph(
    *,
    operation: str,
    source_id: str | int,
    target_id: str | int | None = None,
    direction: str = "BOTH",
    label: str | None = None,
    max_depth: int = 2,
    max_degree: int = 16,
    capacity: int = 1000,
    limit: int | None = None,
) -> dict[str, Any]:
    """Execute a strictly bounded graph traversal or path query."""
    cfg = get_effective_config()
    validation_err, effective_limit = _validate_inputs(
        operation=operation,
        source_id=source_id,
        target_id=target_id,
        direction=direction,
        label=label,
        max_depth=max_depth,
        max_degree=max_degree,
        capacity=capacity,
        limit=limit,
        cfg=cfg,
    )
    if validation_err is not None:
        return validation_err

    try:
        client = _build_client(cfg)
        traverser = client.traverser()
        byte_budget = max(1, min(MAX_TRAVERSE_BYTES, cfg.max_result_bytes))
        sess = getattr(client, "session", None) or getattr(client, "_session", None)
        guard = (
            sess.request_guard(
                max_response_bytes=byte_budget,
                deadline_seconds=TRAVERSE_DEADLINE_SECONDS,
                retries=False,
            )
            if sess is not None and hasattr(sess, "request_guard")
            else nullcontext()
        )
        with guard:
            if operation == "neighbors":
                raw = traverser.k_neighbor(
                    source_id,
                    max_depth,
                    direction=direction,
                    label=label,
                    max_degree=max_degree,
                    limit=effective_limit,
                )
            elif operation == "k_out":
                raw = traverser.k_out(
                    source_id,
                    max_depth,
                    direction=direction,
                    label=label,
                    max_degree=max_degree,
                    capacity=capacity,
                    limit=effective_limit,
                )
            elif operation == "shortest_path":
                raw = traverser.shortest_path(
                    source_id,
                    target_id,
                    max_depth,
                    direction=direction,
                    label=label,
                    max_degree=max_degree,
                    with_vertex=False,
                    with_edge=False,
                    capacity=capacity,
                )
            else:
                raw = traverser.paths(
                    source_id,
                    target_id,
                    max_depth,
                    direction=direction,
                    label=label,
                    max_degree=max_degree,
                    capacity=capacity,
                    limit=effective_limit,
                )
    except Exception as exc:
        classified = classify_hugegraph_exception(exc)
        return envelope_err(
            classified.error_type,
            f"Graph traversal failed: {exc}",
            suggestion=classified.suggestion,
            retryable=classified.retryable,
            details={"reason": classified.reason, "operation": operation},
        )

    try:
        normalized = _normalize_result(operation, raw, effective_limit=effective_limit)
    except ValueError as exc:
        return envelope_err(
            ErrorType.SERVER_ERROR,
            f"HugeGraph returned an unexpected traversal response: {exc}",
            suggestion="Check HugeGraph server version and traversal endpoint compatibility.",
            retryable=False,
            details={"reason": "invalid_response_shape", "operation": operation},
        )
    normalized.update(
        {
            "operation": operation,
            "source_id": source_id,
            "target_id": target_id,
            "direction": direction,
            "budgets_applied": {
                "max_depth": max_depth,
                "max_degree": max_degree,
                "capacity": capacity,
                "limit": effective_limit,
                "max_response_bytes": min(MAX_TRAVERSE_BYTES, cfg.max_result_bytes),
                "deadline_seconds": TRAVERSE_DEADLINE_SECONDS,
            },
            "graph_target": {
                "graph": cfg.graph,
                "graphspace": cfg.graphspace or "DEFAULT",
            },
        }
    )
    return envelope_ok(normalized)
