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

"""Gremlin 执行层 — 封装 HugeGraph Gremlin 读写客户端。

所有 Gremlin 查询统一通过 GremlinExecutor 执行，对连接失败/认证错误/
HTTP 错误/语法错误做结构化错误收集，不抛异常到上层。
"""

import json
import time
from typing import Any

import requests
from pyhugegraph.client import PyHugeClient
from pyhugegraph.utils.exceptions import (
    DataFormatError,
    InvalidParameterError,
    NotAuthorizedError,
    NotFoundError,
    ResponseParseError,
    ServerError,
    ServiceUnavailableError,
)

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.error_mapping import classify_hugegraph_exception
from hugegraph_mcp.gremlin_policy import check_gremlin_read, gremlin_cost_warnings
from hugegraph_mcp.guard import Capability, guard_write
from hugegraph_mcp.hugegraph_client import build_hugegraph_client


class GremlinExecutor:
    """封装 HugeGraph Gremlin 读写客户端，自动处理 graphspace 兼容性。

    HugeGraph 1.7.0+ 支持 graph space，配置为空时回退到默认客户端。
    """

    def __init__(self, cfg: MCPConfig) -> None:
        self._cfg = cfg

    def _build_client(self, request_timeout_seconds: float) -> PyHugeClient:
        return build_hugegraph_client(
            self._cfg,
            client_cls=PyHugeClient,
            request_timeout_seconds=request_timeout_seconds,
        )

    def get_read_client(self):
        return self._build_client(self._cfg.read_timeout_seconds).gremlin()

    def get_write_client(self):
        return self._build_client(self._cfg.write_timeout_seconds).gremlin()


_GREMLIN_ERROR_TYPE_MAP = {
    "connection_error": ErrorType.CONNECTION_FAILED,
    "timeout_error": ErrorType.TIMEOUT,
    "authentication_error": ErrorType.AUTHENTICATION_FAILED,
    "authorization_error": ErrorType.AUTHORIZATION_FAILED,
    "no_index_error": ErrorType.NO_INDEX,
    "query_syntax_error": ErrorType.QUERY_SYNTAX_ERROR,
    "server_error": ErrorType.SERVER_ERROR,
    "http_error": ErrorType.SERVER_ERROR,
    "not_found_error": ErrorType.NOT_FOUND,
    "unknown_error": ErrorType.SERVER_ERROR,
    **{error_type.value: error_type for error_type in ErrorType},
}
LIMIT_POLICIES = frozenset({"warn", "reject_unbounded", "auto_append"})


def _get_read_client():
    return GremlinExecutor(MCPConfig.from_env()).get_read_client()


def _get_write_client():
    return GremlinExecutor(MCPConfig.from_env()).get_write_client()


def _gremlin_error_envelope(result: dict[str, Any]) -> dict[str, Any]:
    error_type = _GREMLIN_ERROR_TYPE_MAP.get(
        result.get("error_type"),
        ErrorType.SERVER_ERROR,
    )
    suggestions = result.get("suggestions") or []
    suggestion = "; ".join(suggestions) if suggestions else None
    return envelope_err(
        error_type,
        result.get("message", "Gremlin query failed"),
        suggestion=suggestion,
        retryable=_gremlin_error_retryable(result),
        details=result,
        duration_ms=result.get("duration_ms"),
    )


def _gremlin_error_retryable(result: dict[str, Any]) -> bool:
    if "retryable" in result:
        return bool(result["retryable"])
    error_type = result.get("error_type")
    if error_type in {"connection_error", "timeout_error"}:
        return True
    if error_type not in {"server_error", "http_error"}:
        return False

    try:
        status_code = int(result.get("status_code"))
    except (TypeError, ValueError):
        return error_type == "server_error"
    return status_code in {500, 502, 503, 504}


def _gremlin_result_count(data: Any) -> int:
    """Return the number of result items from HugeGraph/PyHugeGraph shapes."""
    if data is None:
        return 0
    if isinstance(data, dict) and "data" in data:
        inner_data = data.get("data")
        if inner_data is None:
            return 0
        if isinstance(inner_data, (list, tuple, set)):
            return len(inner_data)
        return 1
    if isinstance(data, (list, tuple, set)):
        return len(data)
    return 1


def _gremlin_result_byte_size(data: Any) -> int:
    encoded = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    return len(encoded)


def _gremlin_output_guard_error(data: Any, count: int, duration_ms: float) -> dict[str, Any] | None:
    """Reject an already-materialized result that is too large to return.

    This is deliberately an output guard, not an execution or transport budget:
    PyHugeGraph has already downloaded and decoded ``data`` at this point.
    """
    cfg = MCPConfig.from_env()
    byte_size = _gremlin_result_byte_size(data)
    exceeded = []
    if count > cfg.max_result_items:
        exceeded.append("max_result_items")
    if byte_size > cfg.max_result_bytes:
        exceeded.append("max_result_bytes")
    if not exceeded:
        return None
    return envelope_err(
        ErrorType.VALIDATION_ERROR,
        "Gremlin result exceeds the configured post-materialization output guard.",
        suggestion="Use a smaller limit or return fewer/smaller properties.",
        details={
            "truncated": False,
            "guard_type": "post_materialization_output_guard",
            "hard_budget": False,
            "exceeded": exceeded,
            "result_items": count,
            "max_result_items": cfg.max_result_items,
            "result_bytes": byte_size,
            "max_result_bytes": cfg.max_result_bytes,
        },
        duration_ms=duration_ms,
    )


def _is_no_index_error(message: Any) -> bool:
    lowered = str(message).lower()
    return "noindexexception" in lowered or "no index" in lowered


def _no_index_error_result(
    message: str,
    duration_ms: float,
    operation_type: str,
) -> dict[str, Any]:
    return {
        "success": False,
        "error_type": "no_index_error",
        "message": message,
        "suggestions": [
            "Create an index for the queried property before using has() filters",
            "Use primary-key based lookups when possible",
            "Check HugeGraph schema index labels with inspect_graph_tool",
        ],
        "duration_ms": duration_ms,
        "operation_type": operation_type,
    }


def _get_client_address(client) -> str:
    """Extract server address from a pyhugegraph client for error messages.

    pyhugegraph does not expose a public URL getter; we read the private
    ``_url`` attribute with a ``hasattr`` guard as a last resort.  This is
    safe for error-reporting purposes only and should not be relied on for
    logic.
    """
    if client is not None and hasattr(client, "_url"):
        return str(client._url)
    return "unknown address"


def _execute_gremlin_with_error_handling(client, gremlin_query: str, operation_type: str = "read") -> dict[str, Any]:
    """执行 Gremlin 查询并做结构化错误处理。

    连接失败、HTTP 错误、语法错误等均返回结构化 dict 而非抛异常，
    便于上层统一处理。区分 401/403/404/500 等状态码给出针对性建议。
    """
    start = time.perf_counter()
    actual_client = None

    try:
        actual_client = client() if callable(client) else client
        data = actual_client.exec(gremlin_query)
        duration_ms = (time.perf_counter() - start) * 1000.0

        return {
            "success": True,
            "data": data,
            "count": _gremlin_result_count(data),
            "duration_ms": duration_ms,
            "operation_type": operation_type,
        }

    except requests.exceptions.ConnectionError:
        address = _get_client_address(actual_client)
        return {
            "success": False,
            "error_type": "connection_error",
            "message": f"Cannot connect to HugeGraph server at {address}",
            "suggestions": [
                "Check if HugeGraph server is running",
                "Verify the HUGEGRAPH_URL environment variable",
                "Check network connectivity to the server",
            ],
            "duration_ms": (time.perf_counter() - start) * 1000.0,
            "operation_type": operation_type,
        }

    except requests.exceptions.Timeout:
        address = _get_client_address(actual_client)
        return {
            "success": False,
            "error_type": "timeout_error",
            "message": f"HugeGraph request timed out at {address}",
            "suggestions": [
                "Retry the request after checking HugeGraph server health",
                "Verify the query is bounded and can complete within the client timeout",
                "Check network latency to the server",
            ],
            "duration_ms": (time.perf_counter() - start) * 1000.0,
            "operation_type": operation_type,
        }

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if hasattr(e, "response") and e.response else "unknown"

        if status_code == 401:
            error_type = "authentication_error"
            message = "Authentication failed - invalid credentials"
            suggestions = [
                "Check HUGEGRAPH_USER and HUGEGRAPH_PASSWORD environment variables",
                "Verify user permissions in HugeGraph",
            ]
        elif status_code == 403:
            error_type = "authorization_error"
            message = "Authorization failed - insufficient permissions"
            suggestions = [
                "Check if the user has permission to execute Gremlin queries",
                "Verify graph space permissions if using graph spaces",
            ]
        elif status_code == 404:
            error_type = "not_found_error"
            message = "Graph or endpoint not found"
            suggestions = [
                "Check if the graph name is correct",
                "Verify the graph exists in HugeGraph",
            ]
        elif status_code == 500:
            error_type = "server_error"
            # Try to extract detailed HugeGraph error information from the response body.
            detail_message = ""
            try:
                if hasattr(e, "response") and e.response is not None:
                    error_json = e.response.json()
                    detail_message = error_json.get("exception") or ""
                    if not detail_message:
                        detail_message = (
                            error_json.get("message")
                            or error_json.get("detail")
                            or error_json.get("error")
                            or str(error_json)
                        )
            except Exception:  # noqa: BLE001, S110 - best-effort error-body parsing
                pass

            if detail_message:
                if _is_no_index_error(detail_message):
                    return _no_index_error_result(
                        f"Query requires an index: {detail_message}",
                        (time.perf_counter() - start) * 1000.0,
                        operation_type,
                    )
                message = f"HugeGraph server internal error: {detail_message}"
            else:
                message = "HugeGraph server internal error"
            suggestions = [
                "Check the Gremlin query syntax",
                "Verify all referenced vertex/edge labels exist",
                "Check HugeGraph server logs for details",
                "Ensure the query doesn't violate graph constraints",
            ]
        else:
            error_type = "http_error"
            message = f"HTTP error {status_code}"
            suggestions = ["Check HugeGraph server status", "Verify the request format"]

        return {
            "success": False,
            "error_type": error_type,
            "message": message,
            "status_code": status_code,
            "suggestions": suggestions,
            "duration_ms": (time.perf_counter() - start) * 1000.0,
            "operation_type": operation_type,
        }

    except (
        NotAuthorizedError,
        NotFoundError,
        InvalidParameterError,
        DataFormatError,
        ServiceUnavailableError,
        ResponseParseError,
        ServerError,
    ) as e:
        duration_ms = (time.perf_counter() - start) * 1000.0
        if isinstance(e, (InvalidParameterError, DataFormatError)):
            return {
                "success": False,
                "error_type": "query_syntax_error",
                "message": str(e) or type(e).__name__,
                "suggestions": ["Check the Gremlin query syntax and parameters."],
                "retryable": False,
                "duration_ms": duration_ms,
                "operation_type": operation_type,
            }
        classification = classify_hugegraph_exception(e)
        if classification.error_type == ErrorType.NO_INDEX:
            return _no_index_error_result(str(e), duration_ms, operation_type)
        return {
            "success": False,
            "error_type": classification.error_type.value,
            "reason": classification.reason,
            "message": str(e) or type(e).__name__,
            "suggestions": [classification.suggestion],
            "retryable": classification.retryable,
            "duration_ms": duration_ms,
            "operation_type": operation_type,
        }

    except ValueError as e:
        return {
            "success": False,
            "error_type": "query_syntax_error",
            "message": f"Gremlin query syntax error: {e!s}",
            "suggestions": [
                "Check Gremlin query syntax",
                "Verify all steps and parameters are valid",
                "Ensure proper use of Gremlin traversal steps",
            ],
            "duration_ms": (time.perf_counter() - start) * 1000.0,
            "operation_type": operation_type,
        }

    except Exception as e:  # noqa: BLE001 - normalize every client failure
        duration_ms = (time.perf_counter() - start) * 1000.0
        message = f"Unexpected error: {e!s}"
        if _is_no_index_error(message):
            return _no_index_error_result(message, duration_ms, operation_type)
        return {
            "success": False,
            "error_type": "unknown_error",
            "message": message,
            "suggestions": [
                "Check HugeGraph server logs",
                "Verify the query format and parameters",
                "Try a simpler query to test connectivity",
            ],
            "duration_ms": duration_ms,
            "operation_type": operation_type,
        }


def execute_gremlin_read(
    gremlin_query: str,
    *,
    limit_policy: str = "warn",
) -> dict[str, Any]:
    """执行只读 Gremlin 查询。

    通过 GremlinPolicy.check_read() 做安全检查，
    拒绝写入类和无法确定的查询，只放行明确安全的遍历。
    limit_policy:
    - warn: 兼容默认，仅返回 unbounded warning。
    - reject_unbounded: 安全但无界时拒绝执行。
    - auto_append: 对简单无界遍历追加 .limit(100)，并返回原始/实际查询。
    返回 {data, total, duration_ms, is_read}。
    """
    if limit_policy not in LIMIT_POLICIES:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"Unsupported limit_policy: {limit_policy!r}.",
            suggestion="Use one of: warn, reject_unbounded, auto_append.",
            details={"limit_policy": limit_policy},
        )

    decision = check_gremlin_read(gremlin_query)
    if not decision.allowed:
        return envelope_err(
            ErrorType.UNSAFE_GREMLIN,
            decision.reason,
            suggestion=decision.suggestion,
            details={"classification": decision.classification},
        )

    original_gremlin = gremlin_query
    rewrite_reason = None
    cost_warnings = gremlin_cost_warnings(gremlin_query)
    unbounded = _has_unbounded_warning(cost_warnings)
    if limit_policy == "reject_unbounded" and unbounded:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "Gremlin read query is unbounded and limit_policy='reject_unbounded'.",
            suggestion="Add .limit(n) or .range(start, end), or use limit_policy='warn'.",
            details={"gremlin_query": gremlin_query, "warnings": cost_warnings},
            warnings=cost_warnings,
        )
    if limit_policy == "auto_append" and unbounded:
        rewritten = _auto_append_limit(gremlin_query)
        if rewritten is None:
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                "Cannot safely auto-append limit to this Gremlin query.",
                suggestion=("Add an explicit .limit(n) yourself, or use limit_policy='warn'."),
                details={"gremlin_query": gremlin_query, "warnings": cost_warnings},
                warnings=cost_warnings,
            )
        gremlin_query = rewritten
        rewrite_reason = "limit_policy='auto_append' added .limit(100) to an unbounded read traversal."
        cost_warnings = gremlin_cost_warnings(gremlin_query)

    result = _execute_gremlin_with_error_handling(_get_read_client, gremlin_query, "read")

    if result.get("success"):
        duration_ms = result["duration_ms"]
        output_guard_error = _gremlin_output_guard_error(result["data"], result["count"], duration_ms)
        if output_guard_error is not None:
            return output_guard_error
        return envelope_ok(
            {
                "data": result["data"],
                "total": result["count"],
                "duration_ms": duration_ms,
                "is_read": True,
                "limit_policy": limit_policy,
                "original_gremlin": original_gremlin,
                "executed_gremlin": gremlin_query,
                "rewrite_reason": rewrite_reason,
            },
            duration_ms=duration_ms,
            warnings=cost_warnings,
        )
    else:
        return _gremlin_error_envelope(result)


def _has_unbounded_warning(warnings: list[str]) -> bool:
    return any("Unbounded traversal" in warning for warning in warnings)


def _auto_append_limit(gremlin_query: str) -> str | None:
    stripped = gremlin_query.strip()
    if not stripped.endswith(")"):
        return None
    lowered = stripped.lower()
    if any(step in lowered for step in (".group(", ".path(", ".profile(", ".repeat(")):
        return None
    return f"{stripped}.limit(100)"


def execute_gremlin_write(
    gremlin_query: str,
    *,
    capability: Capability = Capability.DATA_WRITE,
) -> dict[str, Any]:
    """执行 Gremlin 写查询。

    readonly 模式下通过 guard_write 拒绝执行，
    正常模式返回 {success, affected, duration_ms, is_write}。
    """

    violation = guard_write(capability)
    if violation is not None:
        return violation

    result = _execute_gremlin_with_error_handling(_get_write_client, gremlin_query, "write")

    if result.get("success"):
        duration_ms = result["duration_ms"]
        return envelope_ok(
            {
                "affected": result["count"],
                "duration_ms": duration_ms,
                "is_write": True,
            },
            duration_ms=duration_ms,
        )
    else:
        return _gremlin_error_envelope(result)
