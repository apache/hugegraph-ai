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

from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.hugegraph_ai_client import post


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

    ai_result = post("/vid-embeddings/refresh", json={})
    if not ai_result.get("ok"):
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
