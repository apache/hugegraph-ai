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

"""VID 嵌入刷新 — 手动触发 HugeGraph-AI 重新索引顶点嵌入。

需要 INDEX_WRITE 权限 + confirm=True，readonly 模式下拒绝执行。
"""

import re
from typing import Any

from hugegraph_mcp.config import get_effective_config
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.hugegraph_ai_client import get, post


def refresh_vid_embeddings(confirm: bool = False) -> dict[str, Any]:
    """手动刷新 VID 嵌入 — 需要 confirm=True 确认。

    readonly 模式通过 guard(Capability.INDEX_WRITE) 拒绝。
    """

    violation = guard(Capability.INDEX_WRITE)
    if violation is not None:
        return violation

    if not confirm:
        return envelope_err(
            ErrorType.CONFIRM_REQUIRED,
            "VID embedding refresh requires confirm=True.",
            suggestion="Pass confirm=True to refresh VID embeddings.",
        )

    cfg = get_effective_config()
    capability = get("/vid-embeddings/refresh-capabilities", cfg=cfg)
    if not capability.get("ok"):
        error = capability.get("error") or {}
        # Only an explicitly absent/unsupported endpoint means the protocol is
        # unavailable. Keep transient and authentication errors retryable as
        # reported by the client, without ever dispatching the refresh.
        status_code = (error.get("details") or {}).get("status_code")
        if error.get("type") in {
            "AUTHENTICATION_FAILED",
            "AUTHORIZATION_FAILED",
            "FEATURE_DISABLED",
        } or status_code not in {404, 405}:
            return capability
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            "AI refresh target-validation endpoint is unavailable; refresh was not sent.",
            suggestion="Check the AI service URL and routing, or upgrade HugeGraph-AI to support target validation.",
            details={"status_code": status_code},
        )
    support = capability.get("data")
    if (
        not isinstance(support, dict)
        or type(support.get("protocol_version")) is not int
        or support["protocol_version"] != 1
    ):
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            "AI refresh target-validation protocol is unsupported; refresh was not sent.",
            suggestion="Upgrade HugeGraph-AI to a compatible target-validation version.",
        )
    # Discovery and refresh can reach different replica versions. Only this
    # versioned route binds validation to execution; never fall back to legacy.
    ai_result = post(
        "/v1/vid-embeddings/refresh",
        cfg=cfg,
        json={"expected_graph": cfg.graph, "expected_graphspace": cfg.graphspace},
    )
    if not ai_result.get("ok"):
        error = ai_result.get("error") or {}
        status_code = (error.get("details") or {}).get("status_code")
        if status_code in {404, 405} and error.get("type") not in {
            "AUTHENTICATION_FAILED",
            "AUTHORIZATION_FAILED",
            "FEATURE_DISABLED",
        }:
            return envelope_err(
                ErrorType.FEATURE_DISABLED,
                "AI validated-refresh endpoint is unavailable; legacy refresh was not sent.",
                suggestion="Check AI routing and upgrade all replicas to support /v1/vid-embeddings/refresh.",
                details={"status_code": status_code},
            )
        return ai_result

    data = _unwrap_ai_payload(ai_result.get("data"))
    if isinstance(data, dict) and data.get("ok") is False:
        return data

    added, removed, summary = _parse_refresh_result(data)
    return envelope_ok(
        {
            "added": added,
            "removed": removed,
            "summary": summary,
        }
    )


def _unwrap_ai_payload(data: Any) -> Any:
    if isinstance(data, dict) and "ok" in data and "data" in data:
        if data.get("ok") is False:
            return data
        return data.get("data")
    return data


def _parse_refresh_result(data: Any) -> tuple[int, int, Any]:
    if isinstance(data, dict):
        return data.get("added", 0), data.get("removed", 0), data.get("summary")
    if isinstance(data, str):
        added, removed = _parse_numbers_from_string(data)
        return added, removed, data
    return 0, 0, str(data) if data is not None else None


def _parse_numbers_from_string(text: str) -> tuple[int, int]:
    added = 0
    removed = 0
    match = re.search(r"(?:added|add)\s+(\d+)", text, re.IGNORECASE)
    if match:
        added = int(match.group(1))
    match = re.search(r"(?:removed|remove)\s+(\d+)", text, re.IGNORECASE)
    if match:
        removed = int(match.group(1))
    return added, removed
