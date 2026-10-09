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
"""Operational counters for /admin/metrics: hand-written aggregation SQL over
the platform's own tables. Extracted from the route so the route layer stays
SQL-free and a future CLI/scraper can reach the same numbers."""
from __future__ import annotations

from typing import Any


async def collect(sc) -> dict[str, Any]:
    """The window is the whole retained telemetry (aggregate_signals prunes
    on the evolution cadence); per-window stats are the RSI surface's job."""
    import datetime as _dt

    from sqlalchemy import case as sa_case
    from sqlalchemy import func as sa_func, select as sa_select

    from .action.models import OutboxRow
    from .agent.models import AgentSessionRow, AgentStepRow
    from .telemetry.service import TelemetryActionRow, TelemetryAgentRow, TelemetryQueryRow

    async with sc.sessionmaker() as s:
        q = (await s.execute(sa_select(
            sa_func.count(TelemetryQueryRow.id),
            sa_func.avg(TelemetryQueryRow.latency_ms),
            sa_func.sum(sa_case((TelemetryQueryRow.error, 1), else_=0)),
        ))).one()
        queries = {
            "total": int(q[0] or 0),
            "avg_latency_ms": round(float(q[1] or 0.0), 2),
            "errors": int(q[2] or 0),
        }
        a = (await s.execute(sa_select(
            sa_func.count(TelemetryActionRow.id),
            sa_func.avg(TelemetryActionRow.duration_ms),
        ))).one()
        actions = {"total": int(a[0] or 0), "avg_duration_ms": round(float(a[1] or 0.0), 2)}
        g = (await s.execute(sa_select(
            sa_func.count(TelemetryAgentRow.id),
        ))).one()
        agent_calls = {"total": int(g[0] or 0)}
        sess = (await s.execute(sa_select(
            sa_func.count(AgentSessionRow.id),
            sa_func.sum(sa_case((AgentSessionRow.status == "blocked_on_approval", 1), else_=0)),
            sa_func.sum(sa_case((AgentSessionRow.status == "running", 1), else_=0)),
        ))).one()
        sessions = {"total": int(sess[0] or 0),
                    "blocked_on_approval": int(sess[1] or 0),
                    "running": int(sess[2] or 0)}
        steps = int((await s.execute(
            sa_select(sa_func.count(AgentStepRow.id)))).scalar() or 0)
        outbox = (await s.execute(sa_select(
            sa_func.count(OutboxRow.id),
            sa_func.sum(sa_case((OutboxRow.published_at.is_(None), 1), else_=0)),
        ))).one()
        outbox_stats = {"total": int(outbox[0] or 0), "pending": int(outbox[1] or 0)}
    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "queries": queries,
        "actions": actions,
        "agent": {**agent_calls, "steps_recorded": steps, "sessions": sessions},
        "outbox": outbox_stats,
    }