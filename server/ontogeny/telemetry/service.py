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
"""Telemetry: the fitness-signal substrate for the evolution loop.

Recording is marking-aware by design: principals are hashed, filters are kept
(pure schema diagnostics), row values never leave their tables.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, case, func, select
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..evolve.models import EvolveSignalRow


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class TelemetryQueryRow(Base):
    __tablename__ = "ontogeny_telemetry_query"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    principal_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_type: Mapped[str] = mapped_column(String(200), index=True)
    filter: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_results: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[bool] = mapped_column(Boolean, default=False)


class TelemetryActionRow(Base):
    __tablename__ = "ontogeny_telemetry_action"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    action: Mapped[str] = mapped_column(String(200), index=True)
    outcome: Mapped[str] = mapped_column(String(32))
    rule_expr: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


class TelemetryAgentRow(Base):
    __tablename__ = "ontogeny_telemetry_agent"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    tool: Mapped[str] = mapped_column(String(200), index=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retries: Mapped[int] = mapped_column(Integer, default=0)


def hash_principal(principal: dict | None) -> str | None:
    if not principal or not principal.get("id"):
        return None
    return hashlib.sha256(str(principal["id"]).encode()).hexdigest()[:16]


class TelemetryService:
    def __init__(self, compiled) -> None:
        self.compiled = compiled

    async def record_query(self, session, object_type: str, principal: dict | None,
                           filt: Any, latency_ms: float, n_results: int, error: bool = False) -> None:
        session.add(TelemetryQueryRow(
            principal_hash=hash_principal(principal), object_type=object_type,
            filter=_jsonable_filter(filt), latency_ms=latency_ms, n_results=n_results, error=error,
        ))

    async def record_action(self, session, action: str, outcome: str,
                            rule_expr: str | None = None, duration_ms: float | None = None) -> None:
        session.add(TelemetryActionRow(action=action, outcome=outcome, rule_expr=rule_expr, duration_ms=duration_ms))

    async def record_agent(self, session, tool: str, error: str | None = None, retries: int = 0) -> None:
        session.add(TelemetryAgentRow(tool=tool, error=error, retries=retries))

    # ------------------------------------------------------------ aggregation

    async def aggregate_signals(self, session, *, window_hours: int = 168,
                                thresholds: dict[str, float] | None = None) -> list[dict]:
        """Deterministic detectors -> ontogeny_evolve_signal rows.

        Aggregation is idempotent within the window: a (kind, evidence) pair that
        is already on record is not written again. Without this, the rolling
        window re-detects the same finding on every run and the signal feed
        drowns in duplicates -- one empty-query finding fired once per aggregate
        click, seven identical rows deep.

        ``thresholds`` (from the domain's EvolutionPolicy.observability) overrides
        per-detector sensitivity; unset keys keep the built-in defaults.
        """
        th = {
            "empty_query_rate": 0.1,
            "unmapped_filter_min": 5,
            "rule_reject_rate": 0.3,
            "rule_reject_min": 5,
            "agent_error_min": 3,
            "slow_query_p95_ms": 2000.0,
            "approval_reject_rate": 0.3,
            "approval_reject_min": 5,
            "hot_query_min": 3,
        }
        th.update({k: v for k, v in (thresholds or {}).items() if v is not None})
        since = _utcnow() - _dt.timedelta(hours=window_hours)
        created = await self._detect_signals(session, since, th)
        created += await self._detect_quarantine(session, since)
        known = await self._known_signal_keys(session, since)
        fresh = [sig for sig in created if _signal_key(sig) not in known]
        for sig in fresh:
            session.add(EvolveSignalRow(kind=sig["kind"], evidence=sig["evidence"]))
        return fresh

    async def _detect_signals(self, session, since, th: dict[str, float]) -> list[dict]:
        created: list[dict] = []

        # 1) empty-result rate per object type
        empty_sum = func.sum(case((TelemetryQueryRow.n_results == 0, 1), else_=0))
        rows = (await session.execute(
            select(TelemetryQueryRow.object_type, func.count().label("n"), empty_sum.label("empty"))
            .where(TelemetryQueryRow.ts >= since, TelemetryQueryRow.error.is_(False))
            .group_by(TelemetryQueryRow.object_type)
        )).all()
        rate_th = float(th.get("empty_query_rate", 0.1))
        for object_type, n, empty in rows:
            if n and (empty or 0) / n >= rate_th:
                created.append({"kind": "empty_query_rate",
                                "evidence": {"object_type": object_type, "rate": round((empty or 0) / n, 3), "samples": int(n)}})

        # 2) filters referencing fields that are not properties (schema gap);
        #    error queries carry the strongest signal here, so no error filter
        qrows = (await session.execute(
            select(TelemetryQueryRow).where(TelemetryQueryRow.ts >= since)
        )).scalars()
        unmapped: dict[tuple[str, str], int] = {}
        hot: dict[tuple[str, str], dict] = {}
        unmapped_min = int(th.get("unmapped_filter_min", 5))
        hot_min = int(th.get("hot_query_min", 3))
        for q in qrows:
            for field in _filter_fields(q.filter):
                obj = self.compiled.objects.get(q.object_type)
                if obj is not None and field not in obj.spec.properties and not field.startswith("_"):
                    unmapped[(q.object_type, field)] = unmapped.get((q.object_type, field), 0) + 1
            # hot queries: a recurring filter that RETURNS data is a regression
            # candidate for the eval suite (direction C: eval-case-synth)
            if not q.error and q.n_results and q.filter and isinstance(q.filter, dict) and q.filter:
                key = (q.object_type, json.dumps(q.filter, sort_keys=True, ensure_ascii=True, default=str))
                entry = hot.setdefault(key, {"object_type": q.object_type, "filter": q.filter, "count": 0})
                entry["count"] += 1
        for (object_type, field), count in sorted(unmapped.items()):
            if count >= unmapped_min:
                created.append({"kind": "unmapped_filter_field",
                                "evidence": {"object_type": object_type, "field": field, "count": count}})
        for entry in sorted(hot.values(), key=lambda e: (-e["count"], e["object_type"]))[:5]:
            if entry["count"] >= hot_min:
                created.append({"kind": "hot_query",
                                "evidence": {"object_type": entry["object_type"],
                                             "filter": entry["filter"], "count": entry["count"]}})

        # 3) action rule-reject rate
        arows = (await session.execute(
            select(TelemetryActionRow.action, TelemetryActionRow.outcome, func.count())
            .where(TelemetryActionRow.ts >= since).group_by(TelemetryActionRow.action, TelemetryActionRow.outcome)
        )).all()
        totals: dict[str, dict[str, int]] = {}
        for action, outcome, n in arows:
            totals.setdefault(action, {})[outcome] = int(n)
        rr_rate = float(th.get("rule_reject_rate", 0.3))
        rr_min = int(th.get("rule_reject_min", 5))
        for action, by_outcome in totals.items():
            total = sum(by_outcome.values())
            rejected = by_outcome.get("rejected_rule", 0)
            if total >= rr_min and rejected / total >= rr_rate:
                created.append({"kind": "action_rule_reject",
                                "evidence": {"action": action, "rate": round(rejected / total, 3), "samples": total}})

        # 4) agent tool errors
        tool_rows = (await session.execute(
            select(TelemetryAgentRow.tool, func.count())
            .where(TelemetryAgentRow.ts >= since, TelemetryAgentRow.error.is_not(None))
            .group_by(TelemetryAgentRow.tool)
        )).all()
        ae_min = int(th.get("agent_error_min", 3))
        for tool, n in tool_rows:
            if n >= ae_min:
                created.append({"kind": "agent_tool_error", "evidence": {"tool": tool, "count": int(n)}})

        # 5) slow queries: p95 latency per object type over the window
        lat_rows = (await session.execute(
            select(TelemetryQueryRow.object_type, TelemetryQueryRow.latency_ms)
            .where(TelemetryQueryRow.ts >= since, TelemetryQueryRow.error.is_(False),
                   TelemetryQueryRow.latency_ms.is_not(None))
        )).all()
        by_type: dict[str, list[float]] = {}
        for object_type, latency in lat_rows:
            by_type.setdefault(object_type, []).append(float(latency))
        p95_th = float(th.get("slow_query_p95_ms", 2000.0))
        for object_type, lats in sorted(by_type.items()):
            if len(lats) < 2:
                continue
            lats.sort()
            p95 = lats[min(len(lats) - 1, int(round(0.95 * (len(lats) - 1))))]
            if p95 >= p95_th:
                created.append({"kind": "slow_query_p95",
                                "evidence": {"object_type": object_type,
                                             "p95_ms": round(p95, 1), "samples": len(lats)}})

        # 6) approval friction: humans rejecting an agent's writes is a policy
        # mismatch signal (the plugin keeps asking for things people keep saying
        # no to -- tighten the plugin or the rules it fights)
        created += await self._detect_approval(session, since, th)

        return created

    async def _detect_approval(self, session, since, th: dict[str, float]) -> list[dict]:
        try:
            from ..agent.models import AgentApprovalRow
        except ModuleNotFoundError:  # pragma: no cover -- agent layer absent
            return []
        rows = (await session.execute(
            select(AgentApprovalRow.plugin, AgentApprovalRow.status, func.count())
            .where(AgentApprovalRow.requested_at >= since,
                   AgentApprovalRow.status.in_(("rejected", "executed", "approved")))
            .group_by(AgentApprovalRow.plugin, AgentApprovalRow.status)
        )).all()
        rate_th = float(th.get("approval_reject_rate", 0.3))
        min_th = int(th.get("approval_reject_min", 5))
        by_plugin: dict[str, dict[str, int]] = {}
        for plugin, status, n in rows:
            by_plugin.setdefault(plugin, {})[status] = int(n)
        created: list[dict] = []
        for plugin, by_status in sorted(by_plugin.items()):
            total = sum(by_status.values())
            rejected = by_status.get("rejected", 0)
            if total >= min_th and rejected / total >= rate_th:
                created.append({"kind": "approval_reject_rate",
                                "evidence": {"plugin": plugin,
                                             "rate": round(rejected / total, 3), "samples": total}})
        return created

    async def _detect_quarantine(self, session, since) -> list[dict]:
        from ..stores.sync import QuarantineRow

        rows = (await session.execute(
            select(QuarantineRow.object_type, QuarantineRow.code, func.count())
            .where(QuarantineRow.created_at >= since).group_by(QuarantineRow.object_type, QuarantineRow.code)
        )).all()
        return [
            {"kind": "quarantine_rate",
             "evidence": {"object_type": object_type, "code": code, "count": int(n)}}
            for object_type, code, n in rows
        ]

    async def _known_signal_keys(self, session, since) -> set[str]:
        """(kind, evidence) fingerprints already recorded inside the window."""
        rows = (await session.execute(
            select(EvolveSignalRow.kind, EvolveSignalRow.evidence).where(EvolveSignalRow.created_at >= since)
        )).all()
        return {_signal_key({"kind": kind, "evidence": evidence or {}}) for kind, evidence in rows}


def _signal_key(sig: dict) -> str:
    """A stable fingerprint for "this exact finding is already on record"."""
    return sig["kind"] + "|" + json.dumps(sig.get("evidence") or {}, sort_keys=True, ensure_ascii=True, default=str)


def _filter_fields(filt: Any) -> list[str]:
    if filt is None:
        return []
    if isinstance(filt, dict):
        if "field" in filt:
            return [str(filt["field"])]
        if "and" in filt or "or" in filt:
            return [f for sub in filt.get("and", []) + filt.get("or", []) for f in _filter_fields(sub)]
        if "not" in filt:
            return _filter_fields(filt["not"])
        return [str(k) for k in filt.keys()]
    return []


def _jsonable_filter(filt: Any) -> Any:
    if filt is None:
        return None
    if isinstance(filt, dict):
        return {k: _jsonable_filter(v) for k, v in filt.items()}
    if isinstance(filt, list):
        return [_jsonable_filter(v) for v in filt]
    if isinstance(filt, (_dt.datetime, _dt.date)):
        return filt.isoformat()
    return filt
