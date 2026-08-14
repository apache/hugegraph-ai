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

"""统一响应信封 — 所有 MCP 工具通过 envelope_ok/envelope_err 返回一致结构。

强制格式: {ok, data, error, warnings, next_actions, meta}
前端/Agent 无需猜测返回形状，始终可安全解析。"""

import json
import re
from enum import Enum
from typing import Any
from uuid import uuid4

from hugegraph_mcp.config import MCPConfig

REDACTED_VALUE = "***REDACTED***"
SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
)


class ErrorType(str, Enum):
    """标准化错误类型枚举 — 按能力域划分，便于 Agent 分类处理。"""

    CONNECTION_FAILED = "CONNECTION_FAILED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    READONLY_VIOLATION = "READONLY_VIOLATION"
    CONFIRM_REQUIRED = "CONFIRM_REQUIRED"
    PLAN_HASH_MISMATCH = "PLAN_HASH_MISMATCH"
    PLAN_EXPIRED = "PLAN_EXPIRED"
    PLAN_ALREADY_USED = "PLAN_ALREADY_USED"
    TARGET_CHANGED = "TARGET_CHANGED"
    PARTIAL_APPLY = "PARTIAL_APPLY"
    NOT_FOUND = "NOT_FOUND"
    NO_INDEX = "NO_INDEX"
    UNSAFE_GREMLIN = "UNSAFE_GREMLIN"
    QUERY_SYNTAX_ERROR = "QUERY_SYNTAX_ERROR"
    SERVER_ERROR = "SERVER_ERROR"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    INVALID_GRAPH_DATA = "INVALID_GRAPH_DATA"
    HUGEGRAPH_AI_UNAVAILABLE = "HUGEGRAPH_AI_UNAVAILABLE"
    FEATURE_DISABLED = "FEATURE_DISABLED"
    FLOW_EXECUTION_FAILED = "FLOW_EXECUTION_FAILED"
    LLM_FAILED = "LLM_FAILED"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    TIMEOUT = "TIMEOUT"


def generate_request_id() -> str:
    return f"req-{uuid4().hex[:12]}"


def sanitize_for_response(value: Any) -> Any:
    """Redact common secret shapes before returning MCP envelopes."""

    if isinstance(value, dict):
        return {
            key: REDACTED_VALUE
            if _is_sensitive_key(key)
            else sanitize_for_response(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_for_response(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_for_response(item) for item in value)
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _is_sensitive_key(key: Any) -> bool:
    key_lower = str(key).lower()
    return any(part in key_lower for part in SENSITIVE_KEY_PARTS)


def _sanitize_text(value: str) -> str:
    if not _may_contain_sensitive_marker(value):
        return _redact_url_userinfo(value)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        redacted = re.sub(
            r'(?i)("?[a-z0-9_-]*(?:api_key|authorization|password|passwd|pwd|secret|token)[a-z0-9_-]*"?\s*[:=]\s*)"[^"]*"',
            rf"\1\"{REDACTED_VALUE}\"",
            value,
        )
        redacted = re.sub(
            r"(?i)(api_key|authorization|password|passwd|pwd|secret|token)=([^&\s]+)",
            rf"\1={REDACTED_VALUE}",
            redacted,
        )
        redacted = re.sub(
            r"(?i)((?:api_key|authorization|password|passwd|pwd|secret|token)\s*:\s*)"
            r"([^,\"'\n]+)",
            rf"\1{REDACTED_VALUE}",
            redacted,
        )
        redacted = re.sub(
            r"(?i)('[a-z0-9_-]*(?:api_key|authorization|password|passwd|pwd|secret|token)"
            r"[a-z0-9_-]*'\s*:\s*)'[^']*'",
            rf"\1'{REDACTED_VALUE}'",
            redacted,
        )
        redacted = re.sub(
            r"(?i)\b(api_key|authorization|password|passwd|pwd|secret|token)"
            r"(\s*[:=]?\s+)([a-z0-9_.\-]{4,})\b",
            rf"\1\2{REDACTED_VALUE}",
            redacted,
        )
        return _redact_url_userinfo(redacted)
    return json.dumps(sanitize_for_response(parsed), ensure_ascii=False)


def _may_contain_sensitive_marker(value: str) -> bool:
    lowered = value.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS) or "://" in lowered


def _redact_url_userinfo(value: str) -> str:
    return re.sub(r"(https?://)([^/@\s]+)@", rf"\1{REDACTED_VALUE}@", value)


def build_meta(
    *,
    duration_ms: float | None = None,
    request_id: str | None = None,
    graph: str | None = None,
    graphspace: str | None = None,
    readonly: bool | None = None,
    extra_meta: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    cfg = MCPConfig.from_env()
    meta = {
        "request_id": request_id or generate_request_id(),
        "graph": cfg.graph if graph is None else graph,
        "graphspace": cfg.graphspace if graphspace is None else graphspace,
        "readonly": cfg.readonly if readonly is None else readonly,
    }

    if duration_ms is not None:
        meta["duration_ms"] = duration_ms
    if extra_meta:
        meta.update(extra_meta)
    if kwargs:
        meta.update(kwargs)

    return meta


def envelope_ok(
    data: Any = None,
    *,
    duration_ms: float | None = None,
    warnings: list[str] | tuple[str, ...] | None = None,
    next_actions: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    request_id: str | None = None,
    graph: str | None = None,
    graphspace: str | None = None,
    readonly: bool | None = None,
    **meta_fields: Any,
) -> dict[str, Any]:
    envelope_meta = build_meta(
        duration_ms=duration_ms,
        request_id=request_id,
        graph=graph,
        graphspace=graphspace,
        readonly=readonly,
        extra_meta=meta,
        **meta_fields,
    )
    return {
        "ok": True,
        "data": data,
        "error": None,
        "warnings": list(warnings or []),
        "next_actions": list(next_actions or []),
        "meta": envelope_meta,
    }


def envelope_err(
    error_type: ErrorType | str,
    message: str,
    *,
    suggestion: str | None = None,
    retryable: bool = False,
    source: str = "hugegraph-mcp",
    details: Any = None,
    duration_ms: float | None = None,
    warnings: list[str] | tuple[str, ...] | None = None,
    next_actions: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    request_id: str | None = None,
    graph: str | None = None,
    graphspace: str | None = None,
    readonly: bool | None = None,
    **meta_fields: Any,
) -> dict[str, Any]:
    error_value = (
        error_type.value if isinstance(error_type, ErrorType) else str(error_type)
    )
    error: dict[str, Any] = {
        "type": error_value,
        "message": sanitize_for_response(message),
        "suggestion": sanitize_for_response(suggestion),
        "retryable": retryable,
        "source": source,
        "details": sanitize_for_response(details) if details is not None else {},
    }

    envelope_meta = build_meta(
        duration_ms=duration_ms,
        request_id=request_id,
        graph=graph,
        graphspace=graphspace,
        readonly=readonly,
        extra_meta=meta,
        **meta_fields,
    )
    return {
        "ok": False,
        "data": None,
        "error": error,
        "warnings": list(warnings or []),
        "next_actions": list(next_actions or []),
        "meta": envelope_meta,
    }


# Backward-compatible aliases — older code may use several names for the same function.
make_ok_envelope = envelope_ok
make_err_envelope = envelope_err
ok_envelope = envelope_ok
err_envelope = envelope_err
ok = envelope_ok
err = envelope_err
