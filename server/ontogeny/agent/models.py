# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Agent session persistence: sessions, steps, and write approvals.

Three tables, deliberately narrow:

- ``ontogeny_agent_session``  one run of one plugin against one task; carries the
  plugin's frozen snapshot (principal + budget + catalog hash) so a plugin
  edit mid-session cannot silently widen a running agent.
- ``ontogeny_agent_step``     one tool call: what was attempted, with what argument
  digest, what came back (stable outcome code), how long it took. This is the
  observation surface for the UI timeline AND for RSI signals.
- ``ontogeny_agent_approval`` a pending write: created BEFORE execution, consumed by
  a human principal; the approval row is what the broker exchanges for a real
  Action execution, so approval is on the execution path, not a rubber stamp.
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class AgentSessionRow(Base):
    __tablename__ = "ontogeny_agent_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin: Mapped[str] = mapped_column(String(100), index=True)
    principal: Mapped[str] = mapped_column(String(200))            # frozen plugin principal id
    task: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open|finished|expired
    # frozen limits (from the plugin at session start)
    budget_steps: Mapped[int] = mapped_column(Integer, default=40)
    budget_wall_ms: Mapped[int] = mapped_column(Integer, default=120_000)
    budget_writes: Mapped[int] = mapped_column(Integer, default=3)
    writes_used: Mapped[int] = mapped_column(Integer, default=0)
    steps_used: Mapped[int] = mapped_column(Integer, default=0)
    catalog_hash: Mapped[str] = mapped_column(String(64), default="")
    # 0 = unlimited (a session opened with explicit "no budget" overrides)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # when set, the session refuses calls and runs past this moment
    expires_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # how many times this session has been driven (1 on first run) -- steps are
    # tagged with the run they belong to so every pass leaves its own trace
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    # WHO opened/drove the session ({id, via} principal snapshot): the plugin
    # principal is the EXECUTION identity, this is the accountable driver
    driver: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # when the current run started (wall_ms is enforced against this clock)
    run_started_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # the frozen tool catalog (ToolDef.to_meta() per name): a plugin edit
    # mid-session cannot silently widen or narrow a running session -- the
    # session keeps the exact catalog it was opened with
    tools_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AgentStepRow(Base):
    __tablename__ = "ontogeny_agent_step"
    __table_args__ = (Index("ix_agent_step_session", "session_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String(200))
    args_digest: Mapped[str] = mapped_column(Text, default="")     # truncated JSON
    # Why the agent chose this call: the driving engine's own reasoning text for
    # the step. Kept out of `detail` so the observation surface RSI reads stays
    # exactly the tool result.
    thought: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(String(40), default="ok")  # ok|POLICY_DENIED|...
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[float] = mapped_column(default=0.0)
    revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # which drive of the session produced this step (1-based; 0 = legacy rows)
    run_no: Mapped[int] = mapped_column(Integer, default=0)
    # who drove this step: the driver's principal id ("engine" when the
    # session's own engine made the call) -- I4 means the trail answers WHO,
    # not just what
    driver: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentApprovalRow(Base):
    __tablename__ = "ontogeny_agent_approval"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    plugin: Mapped[str] = mapped_column(String(100))
    tool: Mapped[str] = mapped_column(String(200))                  # act_<action>
    action: Mapped[str] = mapped_column(String(200))
    parameters: Mapped[dict] = mapped_column(JSON)
    target_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rationale: Mapped[str] = mapped_column(Text, default="")        # why the agent wants this
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending|approved|rejected|executed
    requested_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


def args_digest(args: dict[str, Any], limit: int = 2000) -> str:
    text = json.dumps(args, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 3] + "..."
