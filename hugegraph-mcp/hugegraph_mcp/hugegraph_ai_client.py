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

"""HugeGraph-AI HTTP 客户端 — 统一请求层。

所有 AI 调用经 request() 统一处理：allow_ai 开关检查、超时控制、
Bearer Token 注入、结构化错误返回。不抛异常。
"""

import time
from typing import Any
from urllib.parse import urlsplit

import requests

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok

_MAX_NESTED_THIN_ENVELOPES = 1
_THIN_ENVELOPE_KEYS = frozenset({"ok", "data", "error", "warnings", "next_actions", "meta"})


def request(
    method: str,
    path: str,
    *,
    cfg: MCPConfig | None = None,
    json: Any = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """调用 HugeGraph-AI 并返回标准化信封。

    allow_ai=False 时直接拒绝，连接超时/HTTP 错误/JSON 解析失败均返回
    结构化错误信封，不抛异常。
    """

    start = time.perf_counter()
    cfg = cfg or MCPConfig.from_env()
    method = method.upper()

    if not _is_relative_path(path):
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "Absolute URLs are not allowed; use a relative HugeGraph-AI path",
            retryable=False,
            duration_ms=_duration_ms(start),
            details={"method": method, "reason": "absolute_url_not_allowed"},
        )

    url = _build_url(cfg.ai_url, path)

    if not cfg.allow_ai:
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            "AI calls are disabled by configuration",
            suggestion=(
                "Set HUGEGRAPH_MCP_ALLOW_AI=true and restart the MCP server, "
                "or use tools that do not require HugeGraph-AI."
            ),
            retryable=False,
            duration_ms=_duration_ms(start),
            details={"method": method, "url": url, "reason": "allow_ai_false"},
        )

    try:
        request_headers = dict(headers) if headers is not None else {}
        if cfg.ai_token and not any(name.lower() == "authorization" for name in request_headers):
            request_headers["Authorization"] = f"Bearer {cfg.ai_token}"
        kwargs: dict[str, Any] = {
            "params": params,
            "headers": request_headers or None,
            "timeout": cfg.timeout_seconds,
        }
        if json is not None:
            kwargs["json"] = json
        response = requests.request(method, url, **kwargs)
        try:
            data = response.json()
        except ValueError:
            # Preserve status-aware handling for empty/HTML HTTP error bodies.
            response.raise_for_status()
            raise
        if _is_thin_api_envelope(data) and not data["ok"]:
            return _normalize_response(data, duration_ms=_duration_ms(start))
        response.raise_for_status()
        return _normalize_response(data, duration_ms=_duration_ms(start))
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        return _ai_error(
            _exception_message("HugeGraph-AI is unavailable", exc),
            duration_ms=_duration_ms(start),
            retryable=True,
            details={"method": method, "url": url},
        )
    except requests.exceptions.HTTPError as exc:
        status_code = _status_code(exc)
        details = {"method": method, "url": url, "status_code": status_code}
        if status_code in {401, 403}:
            return envelope_err(
                ErrorType.AUTHORIZATION_FAILED,
                _exception_message("HugeGraph-AI authorization failed", exc),
                retryable=False,
                details=details,
                duration_ms=_duration_ms(start),
            )
        if isinstance(status_code, int) and 400 <= status_code < 500:
            return _ai_error(
                _exception_message("HugeGraph-AI request failed", exc),
                duration_ms=_duration_ms(start),
                retryable=status_code == 429,
                details=details,
            )
        return _ai_error(
            _exception_message("HugeGraph-AI is unavailable", exc),
            duration_ms=_duration_ms(start),
            retryable=True,
            details=details,
        )
    except ValueError as exc:
        return _ai_error(
            _exception_message("HugeGraph-AI returned invalid JSON", exc),
            duration_ms=_duration_ms(start),
            details={"method": method, "url": url},
        )
    except requests.exceptions.RequestException as exc:
        return _ai_error(
            _exception_message("HugeGraph-AI request failed", exc),
            duration_ms=_duration_ms(start),
            retryable=True,
            details={"method": method, "url": url},
        )


def get(
    path: str,
    *,
    cfg: MCPConfig | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return request("GET", path, cfg=cfg, params=params, headers=headers)


def post(
    path: str,
    *,
    cfg: MCPConfig | None = None,
    json: Any = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return request("POST", path, cfg=cfg, json=json, params=params, headers=headers)


def health_check(*, cfg: MCPConfig | None = None) -> dict[str, Any]:
    """尽力而为的 AI 健康检查 — 尝试多个端点探测 HugeGraph-AI 可用性。

    优先探查 /graph-index-info，失败时回退到 /openapi.json，
    401/403 立即返回不重试。
    """

    attempts: list[str] = []
    last_result: dict[str, Any] | None = None
    for path in ("/graph-index-info", "/openapi.json"):
        result = get(path, cfg=cfg)
        if result.get("ok"):
            data = result.get("data")
            if isinstance(data, dict):
                result["data"] = {
                    "status": "available",
                    "health_endpoint": path,
                    **data,
                }
            else:
                result["data"] = {
                    "status": "available",
                    "health_endpoint": path,
                    "response": data,
                }
            if attempts:
                result["warnings"] = [*result.get("warnings", []), *attempts]
            return result

        last_result = result
        error = result.get("error") or {}
        details = error.get("details") or {}
        status_code = details.get("status_code")
        attempts.append(f"{path}: {error.get('message', 'unavailable')}")
        if status_code in {401, 403}:
            return result

    if last_result is not None and attempts:
        last_result["warnings"] = [*last_result.get("warnings", []), *attempts]
    return last_result or get("/openapi.json", cfg=cfg)


def _build_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _is_relative_path(path: str) -> bool:
    try:
        parsed = urlsplit(path)
    except (TypeError, ValueError):
        return False
    return not parsed.scheme and not parsed.netloc


def _duration_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _status_code(exc: requests.exceptions.HTTPError) -> int | None:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def _exception_message(prefix: str, exc: Exception) -> str:
    message = str(exc).strip()
    return f"{prefix}: {message}" if message else prefix


def _ai_error(
    message: str,
    *,
    duration_ms: float,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return envelope_err(
        ErrorType.HUGEGRAPH_AI_UNAVAILABLE,
        message,
        retryable=retryable,
        details=details,
        duration_ms=duration_ms,
    )


def _normalize_response(data: Any, *, duration_ms: float) -> dict[str, Any]:
    """Convert a Thin API envelope without wrapping it in a second envelope."""
    if not _is_thin_api_envelope(data):
        return envelope_ok(data, duration_ms=duration_ms)

    current = data
    nested_envelopes = 0
    seen_ids: set[int] = set()
    while True:
        current_id = id(current)
        if current_id in seen_ids:
            return _invalid_upstream_response(
                "cyclic_nested_envelope",
                duration_ms=duration_ms,
            )
        seen_ids.add(current_id)

        remote_meta = current.get("meta")
        request_id = remote_meta.get("request_id")
        warnings = current.get("warnings")
        next_actions = current.get("next_actions")
        if not current["ok"]:
            error = current.get("error") if isinstance(current.get("error"), dict) else {}
            retryable = error.get("retryable", False)
            return envelope_err(
                error.get("type", ErrorType.HUGEGRAPH_AI_UNAVAILABLE),
                error.get("message", "HugeGraph-AI request failed"),
                suggestion=error.get("suggestion"),
                retryable=retryable if isinstance(retryable, bool) else False,
                source=error.get("source", "hugegraph-llm"),
                details=error.get("details"),
                duration_ms=duration_ms,
                warnings=warnings,
                next_actions=next_actions,
                request_id=request_id,
            )

        inner_data = current.get("data")
        if _is_thin_api_envelope(inner_data):
            if id(inner_data) in seen_ids:
                return _invalid_upstream_response(
                    "cyclic_nested_envelope",
                    duration_ms=duration_ms,
                    request_id=request_id,
                )
            if nested_envelopes >= _MAX_NESTED_THIN_ENVELOPES:
                return _invalid_upstream_response(
                    "nested_envelope_depth_exceeded",
                    duration_ms=duration_ms,
                    request_id=request_id,
                    max_nested_envelopes=_MAX_NESTED_THIN_ENVELOPES,
                )
            nested_envelopes += 1
            current = inner_data
            continue
        if _looks_like_thin_api_envelope(inner_data):
            return _invalid_upstream_response(
                "malformed_nested_envelope",
                duration_ms=duration_ms,
                request_id=request_id,
            )
        return envelope_ok(
            inner_data,
            duration_ms=duration_ms,
            warnings=warnings,
            next_actions=next_actions,
            request_id=request_id,
        )


def _invalid_upstream_response(
    issue: str,
    *,
    duration_ms: float,
    request_id: str | None = None,
    **details: Any,
) -> dict[str, Any]:
    return envelope_err(
        ErrorType.HUGEGRAPH_AI_UNAVAILABLE,
        "HugeGraph-AI returned an invalid response envelope",
        retryable=False,
        source="hugegraph-llm",
        details={
            "reason": "invalid_upstream_response",
            "issue": issue,
            **details,
        },
        duration_ms=duration_ms,
        request_id=request_id,
    )


def _looks_like_thin_api_envelope(data: Any) -> bool:
    return isinstance(data, dict) and _THIN_ENVELOPE_KEYS.issubset(data)


def _is_thin_api_envelope(data: Any) -> bool:
    meta = data.get("meta") if isinstance(data, dict) else None
    return (
        isinstance(data, dict)
        and isinstance(data.get("ok"), bool)
        and "data" in data
        and (data.get("error") is None or isinstance(data.get("error"), dict))
        and isinstance(data.get("warnings"), list)
        and isinstance(data.get("next_actions"), list)
        and isinstance(meta, dict)
        and isinstance(meta.get("request_id"), str)
        and isinstance(meta.get("duration_ms"), (int, float))
    )
