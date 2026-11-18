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

"""Read-only HugeGraph async task observability tools."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from pyhugegraph.client import PyHugeClient

from hugegraph_mcp.config import MCPConfig, get_effective_config
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.error_mapping import classify_hugegraph_exception
from hugegraph_mcp.hugegraph_client import build_hugegraph_client

MAX_TASK_LIST_LIMIT = 100
MAX_TASK_RESPONSE_BYTES = 1024 * 1024
TASK_DEADLINE_SECONDS = 10.0
ALLOWED_TASK_STATUSES = frozenset(
    {
        "new",
        "scheduling",
        "scheduled",
        "queued",
        "running",
        "restoring",
        "success",
        "cancelled",
        "cancelling",
        "hanging",
        "deleting",
        "failed",
        "unknown",
    }
)


def _build_client(cfg: MCPConfig) -> Any:
    return build_hugegraph_client(
        cfg,
        client_cls=PyHugeClient,
        request_timeout_seconds=min(cfg.read_timeout_seconds, TASK_DEADLINE_SECONDS),
    )


def _sanitize_task(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": raw.get("id"),
        "type": raw.get("type") or raw.get("task_type"),
        "name": raw.get("name") or raw.get("task_name"),
        "status": raw.get("status") or raw.get("task_status"),
        "progress": raw.get("progress") if "progress" in raw else raw.get("task_progress"),
        "create_time": raw.get("create") or raw.get("task_create"),
        "update_time": raw.get("update") or raw.get("task_update"),
        "retries": raw.get("retries") if "retries" in raw else raw.get("task_retries"),
        "server": raw.get("server") or raw.get("task_server"),
    }


def _request_guard(client: Any, cfg: MCPConfig):
    sess = getattr(client, "session", None) or getattr(client, "_session", None)
    if sess is not None and hasattr(sess, "request_guard"):
        return sess.request_guard(
            max_response_bytes=max(1, min(MAX_TASK_RESPONSE_BYTES, cfg.max_result_bytes)),
            deadline_seconds=TASK_DEADLINE_SECONDS,
            retries=False,
        )
    return nullcontext()


def get_task_status(*, task_id: int) -> dict[str, Any]:
    """Fetch a HugeGraph async task status without loading large task_result payloads."""
    if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id <= 0:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "task_id must be a positive integer.",
            details={"reason": "invalid_task_id"},
        )
    cfg = get_effective_config()
    try:
        client = _build_client(cfg)
        with _request_guard(client, cfg):
            raw = client.task().get_task(task_id, with_result=False)
    except Exception as exc:
        classified = classify_hugegraph_exception(exc)
        return envelope_err(
            classified.error_type,
            f"Failed to query task {task_id}: {exc}",
            suggestion=classified.suggestion,
            retryable=classified.retryable,
            details={"reason": classified.reason, "task_id": task_id},
        )
    if not isinstance(raw, dict):
        return envelope_err(
            ErrorType.SERVER_ERROR,
            "Unexpected response format from HugeGraph task endpoint.",
            details={"reason": "invalid_task_response"},
        )
    return envelope_ok(_sanitize_task(raw))


def list_tasks(
    *,
    status: str | None = None,
    limit: int = 20,
    page: str | None = None,
) -> dict[str, Any]:
    """List HugeGraph async tasks with bounded limit and sanitized metadata."""
    cfg = get_effective_config()
    hard_limit = max(1, min(MAX_TASK_LIST_LIMIT, cfg.max_result_items))
    if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= hard_limit):
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"limit must be an integer between 1 and {hard_limit}.",
            details={"reason": "budget_exceeded", "field": "limit", "max": hard_limit},
        )
    normalized_status: str | None = None
    if status is not None:
        if not isinstance(status, str) or not status.strip():
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                "status must be a non-empty string when provided.",
                details={"reason": "invalid_status"},
            )
        normalized_status = status.strip().lower()
        if normalized_status not in ALLOWED_TASK_STATUSES:
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                f"Unsupported task status {status!r}; expected one of {sorted(ALLOWED_TASK_STATUSES)}.",
                details={"reason": "invalid_status", "status": status},
            )

    try:
        client = _build_client(cfg)
        with _request_guard(client, cfg):
            raw = client.task().list_tasks(status=normalized_status, limit=limit, page=page)
    except Exception as exc:
        classified = classify_hugegraph_exception(exc)
        return envelope_err(
            classified.error_type,
            f"Failed to list tasks: {exc}",
            suggestion=classified.suggestion,
            retryable=classified.retryable,
            details={"reason": classified.reason},
        )

    if not isinstance(raw, dict):
        return envelope_err(
            ErrorType.SERVER_ERROR,
            "Unexpected response format from HugeGraph task list endpoint.",
            details={"reason": "invalid_task_list_response"},
        )
    tasks_raw = raw.get("tasks") or []
    tasks = [_sanitize_task(item) for item in tasks_raw[:limit] if isinstance(item, dict)]
    return envelope_ok(
        {
            "tasks": tasks,
            "count": len(tasks),
            "page": raw.get("page"),
            "graph_target": {
                "graph": cfg.graph,
                "graphspace": cfg.graphspace or "DEFAULT",
            },
        }
    )


def cancel_task(*, task_id: int) -> dict[str, Any]:
    """Request cancellation of a HugeGraph async task by task_id."""
    if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id <= 0:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "task_id must be a positive integer.",
            details={"reason": "invalid_task_id"},
        )
    cfg = get_effective_config()
    try:
        client = _build_client(cfg)
        with _request_guard(client, cfg):
            raw = client.task().cancel_task(task_id)
    except Exception as exc:
        classified = classify_hugegraph_exception(exc)
        return envelope_err(
            classified.error_type,
            f"Failed to cancel task {task_id}: {exc}",
            suggestion=classified.suggestion,
            retryable=classified.retryable,
            details={"reason": classified.reason, "task_id": task_id},
        )
    if isinstance(raw, dict):
        return envelope_ok(_sanitize_task(raw))
    return envelope_ok({"task_id": task_id, "status": "cancelling"})
