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

"""Target-bound plan hash — 防止跨图、跨用户、过期重放。

PlanContext 将工具名、模式、图目标、主体、readonly、payload 摘要、
schema 摘要、nonce 和过期时间绑定到一个哈希中。
confirm 时重新计算并比较，拒绝不匹配或过期的计划。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType

# Default plan lifetime in seconds.
DEFAULT_PLAN_TTL_SECONDS = 600  # 10 minutes.


@dataclass(frozen=True)
class PlanContext:
    """计划上下文 — 绑定到特定工具、目标和时间窗口。"""

    tool_name: str
    mode: str
    graph_url: str
    graph_name: str
    graphspace: str
    principal: str
    readonly: bool
    payload_digest: str
    schema_hash: str | None
    nonce: str
    expires_at: int
    extra_context: dict[str, Any] = field(default_factory=dict)


def compute_plan_hash(context: PlanContext) -> str:
    """计算目标绑定的计划哈希。

    使用 canonical JSON 序列化（sorted keys, stable normalization），
    对完整 PlanContext 做 SHA256 哈希。expires_at 参与哈希，防止
    调用方在 confirm 时延长计划有效期。
    """
    payload = asdict(context)
    payload = _canonicalize(payload)
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def build_plan_context(
    tool_name: str,
    mode: str,
    payload_digest: str,
    schema_hash: str | None = None,
    nonce: str | None = None,
    ttl_seconds: int = DEFAULT_PLAN_TTL_SECONDS,
    extra_context: dict[str, Any] | None = None,
) -> tuple[PlanContext, str]:
    """构建 PlanContext 并计算 plan_hash。

    Returns:
        (PlanContext, plan_hash) 元组。
    """
    cfg = MCPConfig.from_env()
    now = int(time.time())

    if nonce is None:
        nonce = _generate_nonce()

    context = PlanContext(
        tool_name=tool_name,
        mode=mode,
        graph_url=cfg.url,
        graph_name=cfg.graph,
        graphspace=cfg.graphspace or "DEFAULT",
        principal=cfg.user,
        readonly=cfg.is_readonly(),
        payload_digest=payload_digest,
        schema_hash=schema_hash,
        nonce=nonce,
        expires_at=now + ttl_seconds,
        extra_context=extra_context or {},
    )

    plan_hash = compute_plan_hash(context)
    return context, plan_hash


def verify_plan_hash(
    submitted_hash: str,
    tool_name: str,
    mode: str,
    payload_digest: str,
    schema_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
    extra_context: dict[str, Any] | None = None,
) -> tuple[bool, str | None, dict[str, Any] | None]:
    """验证提交的 plan_hash。

    重新读取 config 和 schema，重新计算哈希，检查过期。

    Returns:
        (valid, error_type, details) 元组。
        valid=True 时 error_type 和 details 为 None。
    """
    cfg = MCPConfig.from_env()

    if nonce is None:
        return (
            False,
            ErrorType.PLAN_HASH_MISMATCH,
            {"reason": "Missing nonce in plan context."},
        )

    expires_at_seconds = _coerce_expires_at(expires_at)

    # Check expiration. expires_at is returned in the dry-run plan context and
    # must be sent back during confirmation; missing or malformed values are
    # treated as expired so None cannot bypass the lifetime check.
    if expires_at_seconds is None or int(time.time()) > expires_at_seconds:
        return (
            False,
            ErrorType.PLAN_EXPIRED,
            {
                "expires_at": expires_at,
                "current_time": int(time.time()),
                "reason": "Plan has expired. Run dry_run again.",
            },
        )

    # Rebuild the context using the current config, not the submitted config.
    context = PlanContext(
        tool_name=tool_name,
        mode=mode,
        graph_url=cfg.url,
        graph_name=cfg.graph,
        graphspace=cfg.graphspace or "DEFAULT",
        principal=cfg.user,
        readonly=cfg.is_readonly(),
        payload_digest=payload_digest,
        schema_hash=schema_hash,
        nonce=nonce,
        expires_at=expires_at_seconds,
        extra_context=extra_context or {},
    )

    expected_hash = compute_plan_hash(context)

    if submitted_hash != expected_hash:
        return (
            False,
            ErrorType.PLAN_HASH_MISMATCH,
            {
                "provided_hash": submitted_hash,
                "reason": "Plan context has changed since dry_run.",
            },
        )

    return True, None, None


def compute_payload_digest(payload: Any) -> str:
    """计算 payload 的规范化摘要。"""
    normalized = _canonicalize(payload)
    encoded = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _canonicalize(obj: Any) -> Any:
    """Canonical JSON 序列化 — 递归排序 dict keys。"""
    if isinstance(obj, dict):
        return {k: _canonicalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_canonicalize(item) for item in obj]
    return obj


def _generate_nonce() -> str:
    """生成随机 nonce。"""
    from uuid import uuid4

    return uuid4().hex[:12]


def _coerce_expires_at(value: float | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
