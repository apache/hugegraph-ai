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

"""Shared per-invocation read budget for HugeGraph MCP read operations."""

from __future__ import annotations

import time
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from typing import Any

from hugegraph_mcp.config import MCPConfig, get_effective_config


class ReadBudgetExceededError(TimeoutError):
    """Raised when a shared read budget has no remaining time or byte allowance."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass
class ReadBudget:
    """Tracks remaining deadline and response-byte allowance across a tool call."""

    deadline_seconds: float
    max_response_bytes: int
    max_items: int
    started_at: float = field(default_factory=time.monotonic)
    consumed_bytes: int = 0
    requests_made: int = 0

    def remaining_seconds(self) -> float:
        elapsed = time.monotonic() - self.started_at
        return max(0.0, self.deadline_seconds - elapsed)

    def remaining_bytes(self) -> int:
        return max(0, self.max_response_bytes - self.consumed_bytes)

    def ensure_available(self) -> None:
        if self.remaining_seconds() <= 0:
            raise ReadBudgetExceededError(
                "Read deadline budget exceeded before backend request.",
                reason_code="READ_DEADLINE_EXCEEDED",
            )
        if self.remaining_bytes() <= 0:
            raise ReadBudgetExceededError(
                "Read response byte budget exceeded before backend request.",
                reason_code="READ_BYTE_BUDGET_EXCEEDED",
            )

    def record_bytes(self, byte_count: int) -> None:
        if byte_count > 0:
            self.consumed_bytes += byte_count

    def request_guard(
        self,
        target: Any,
        *,
        retries: bool = False,
    ) -> AbstractContextManager[Any]:
        """Return a client ``request_guard`` bound to the remaining budget."""

        self.ensure_available()
        self.requests_made += 1
        session = _extract_session(target)
        if session is not None and callable(getattr(session, "request_guard", None)):
            guard = session.request_guard(
                max_response_bytes=max(1, self.remaining_bytes()),
                deadline_seconds=max(0.001, self.remaining_seconds()),
                retries=retries,
            )
            if hasattr(guard, "__enter__") and hasattr(guard, "__exit__"):
                return guard
        return nullcontext()


def _extract_session(target: Any) -> Any:
    if target is None:
        return None
    direct = getattr(target, "session", None) or getattr(target, "_session", None) or getattr(target, "_sess", None)
    if direct is not None:
        return direct
    client = getattr(target, "client", None) or getattr(target, "_client", None)
    if client is not None:
        return getattr(client, "session", None) or getattr(client, "_session", None) or getattr(client, "_sess", None)
    return None


def read_budget_from_config(
    cfg: MCPConfig | None = None,
    *,
    deadline_seconds: float | None = None,
    max_response_bytes: int | None = None,
    max_items: int | None = None,
) -> ReadBudget:
    """Create a ``ReadBudget`` bounded by ``MCPConfig`` limits."""

    effective = cfg or get_effective_config()
    eff_deadline = (
        float(effective.read_timeout_seconds)
        if deadline_seconds is None
        else min(float(deadline_seconds), float(effective.read_timeout_seconds))
    )
    eff_bytes = (
        int(effective.max_result_bytes)
        if max_response_bytes is None
        else min(int(max_response_bytes), int(effective.max_result_bytes))
    )
    eff_items = (
        int(effective.max_result_items) if max_items is None else min(int(max_items), int(effective.max_result_items))
    )
    return ReadBudget(
        deadline_seconds=max(0.001, eff_deadline),
        max_response_bytes=max(1, eff_bytes),
        max_items=max(1, eff_items),
    )
