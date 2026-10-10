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
"""Evolution-loop persistence: signals, proposals, budgets."""
from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class EvolveSignalRow(Base):
    __tablename__ = "ontogeny_evolve_signal"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)  # empty_query_rate | unmapped_filter_field | quarantine_rate | action_rule_reject | agent_tool_error
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class ProposalRow(Base):
    __tablename__ = "ontogeny_evolve_proposal"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gap_kind: Mapped[str] = mapped_column(String(64))
    diff: Mapped[list[Any]] = mapped_column(JSON)  # list of mutation dicts
    rationale: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(32), default="heuristic")  # heuristic | llm | human
    status: Mapped[str] = mapped_column(String(32), default="proposed", index=True)
    # proposed -> evaluated -> promoted | rejected | awaiting_human
    eval_report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    promoted_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # the model's own reasoning, kept even when it declined the mutation: the
    # decline rationale is often the most valuable part of the round
    llm_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    # human rejection reason (feeds the proposer's memory) and the winner id
    # when a sibling candidate from the same signal got promoted instead
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class BudgetRow(Base):
    __tablename__ = "ontogeny_evolve_budget"

    namespace: Mapped[str] = mapped_column(String(200), primary_key=True)
    week: Mapped[str] = mapped_column(String(10), primary_key=True)  # ISO year-week
    used: Mapped[int] = mapped_column(Integer, default=0)
