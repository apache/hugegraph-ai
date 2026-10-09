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
"""AgentBroker: session lifecycle + governed tool execution.

Every external agent call funnels through :meth:`call_tool`. The method is
the contract: authenticate the session, check the catalog, execute through
ServiceContext, record the step. Writes additionally go through the approval
gate (M2) -- a pending approval row is created and nothing executes until a
human consumes it.
"""
from __future__ import annotations

import datetime as _dt
import logging
import time
from typing import Any

from sqlalchemy import delete, or_, select, update

from ..action.models import OutboxRow  # noqa: F401  (re-exported for API layer typing)
from ..errors import NotFoundError, OOError, PolicyDeniedError, StoreError
from ..registry.compiled import CompiledOntology
from .catalog import ToolDef, build_catalog, catalog_hash, effective_tools
from .models import AgentApprovalRow, AgentSessionRow, AgentStepRow, args_digest

log = logging.getLogger("ontogeny.agent")


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _jsonable(value: Any) -> Any:
    """Row objects carry dates/datetimes/Decimals; JSON columns refuse them."""
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    try:
        import json as _json
        _json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


class SessionBudgetExceeded(OOError):
    code = "AGENT_BUDGET_EXCEEDED"
    http_status = 429


class ToolNotAllowed(OOError):
    code = "AGENT_TOOL_NOT_ALLOWED"
    http_status = 403


class AgentServiceError(StoreError):
    """Raised for broker-internal problems (bad session state etc.)."""


class AgentBroker:
    def __init__(self, sc) -> None:
        self.sc = sc

    # ------------------------------------------------------------- catalog

    def plugin(self, name: str) -> Any:
        if self.sc.compiled is None:
            raise StoreError("service not initialized")
        plug = self.sc.compiled.agent_plugins.get(name)
        if plug is None:
            raise NotFoundError(f"unknown agent plugin {name!r}")
        return plug

    def list_plugins(self) -> list[dict[str, Any]]:
        if self.sc.compiled is None:
            return []
        out = []
        for name, plug in self.sc.compiled.agent_plugins.items():
            tools = effective_tools(self.sc.compiled, plug)
            out.append({
                "name": name,
                "display": plug.metadata.display,
                "description": plug.metadata.description,
                "transport": plug.spec.transport.kind,
                "engine": {"kind": plug.spec.engine.kind, "endpoint": plug.spec.engine.endpoint},
                "principal": plug.spec.principal.as_principal(),
                "approval": plug.spec.approval.writes,
                "budget": {
                    "steps": plug.spec.budget.steps,
                    "wall_ms": plug.spec.budget.wall_ms,
                    "writes_per_session": plug.spec.budget.writes_per_session,
                },
                "tools": {n: t.to_meta() for n, t in tools.items()},
            })
        return out

    # ------------------------------------------------------------ sessions

    async def open_session(self, plugin_name: str, task: str, *,
                           budget: dict[str, Any] | None = None,
                           expires_at: _dt.datetime | None = None,
                           driver: dict[str, Any] | None = None) -> dict[str, Any]:
        """Open a session. ``budget`` overrides the plugin's frozen limits per
        field; 0 (or a negative) means UNLIMITED, an omitted field keeps the
        plugin's value. ``expires_at`` bounds the session's usable life.
        ``driver`` is the accountable WHO behind the session (the plugin
        principal stays the EXECUTION identity; this records who asked for it).
        """
        plug = self.plugin(plugin_name)
        compiled: CompiledOntology = self.sc.compiled  # type: ignore[assignment]
        tools = effective_tools(compiled, plug)
        budget = budget or {}

        def _limit(field: str, plugin_default: int) -> int:
            v = budget.get(field)
            if v is None:
                return plugin_default
            return max(int(v), 0)  # 0 = unlimited

        async with self.sc.sessionmaker() as session:
            row = AgentSessionRow(
                plugin=plugin_name,
                principal=plug.spec.principal.id,
                task=task or "",
                budget_steps=_limit("steps", plug.spec.budget.steps),
                budget_wall_ms=_limit("wall_ms", plug.spec.budget.wall_ms),
                budget_writes=_limit("writes_per_session", plug.spec.budget.writes_per_session),
                expires_at=expires_at,
                catalog_hash=catalog_hash(tools),
                driver={"id": driver.get("id", "?"), "via": driver.get("via", "?")}
                if driver else None,
                run_started_at=_utcnow(),
                # freeze the catalog: a plugin edit mid-session can neither
                # widen nor narrow a running session (the documented contract)
                tools_json={n: t.to_meta() for n, t in tools.items()},
            )
            session.add(row)
            await session.commit()
            return self._session_view(row, tools)

    async def start_run(self, session_id: int, task: str | None = None) -> dict[str, Any]:
        """Direction 3: a session may be driven MANY times. Each run bumps the
        run counter (new steps are tagged with it) and re-opens a finished or
        budget-exhausted session so the engine can drive it again. ``task`` is
        this run's instruction: when given, it becomes the session's task (the
        creation-time text is a description, not the command)."""
        async with self.sc.sessionmaker() as session:
            row = (await session.execute(
                select(AgentSessionRow).where(AgentSessionRow.id == session_id)
            )).scalar_one_or_none()
            if row is None:
                raise NotFoundError(f"agent session {session_id} not found")
            if self._check_expired(row):
                raise OOError("agent session expired",
                              details={"code": "AGENT_SESSION_EXPIRED"})
            if row.status == "running":
                return {"id": row.id, "status": "running", "run_count": row.run_count}
            if task and task.strip():
                row.task = task.strip()
            row.status = "open"
            row.finished_at = None
            row.run_count += 1
            # a fresh run gets a fresh wall clock: wall_ms bounds one drive,
            # not the session's whole multi-run life
            row.run_started_at = _utcnow()
            await session.commit()
            return {"id": row.id, "status": row.status, "run_count": row.run_count}

    def _check_expired(self, row: AgentSessionRow) -> bool:
        """True when the session is past its expires_at (and marks it)."""
        # SQLite returns naive UTC datetimes; normalize before comparing
        exp = row.expires_at.replace(tzinfo=_dt.timezone.utc) \
            if row.expires_at is not None and row.expires_at.tzinfo is None \
            else row.expires_at
        if exp is not None and _utcnow() > exp:
            row.status = "expired"
            return True
        return False

    async def get_session(self, session_id: int) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            row = (await session.execute(
                select(AgentSessionRow).where(AgentSessionRow.id == session_id)
            )).scalar_one_or_none()
            if row is None:
                raise NotFoundError(f"agent session {session_id} not found")
            steps = (await session.execute(
                select(AgentStepRow).where(AgentStepRow.session_id == session_id)
                .order_by(AgentStepRow.seq)
            )).scalars().all()
            plug = self.sc.compiled.agent_plugins.get(row.plugin) if self.sc.compiled else None
            tools = self._frozen_tools(row, plug)
            return self._session_view(row, tools, steps=[self._step_view(s) for s in steps])

    async def list_sessions(self, *, plugin: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        stmt = select(AgentSessionRow).order_by(AgentSessionRow.id.desc()).limit(limit)
        if plugin:
            stmt = stmt.where(AgentSessionRow.plugin == plugin)
        async with self.sc.sessionmaker() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [self._session_view(r) for r in rows]

    async def delete_session(self, session_id: int) -> dict[str, Any]:
        """Delete one agent session and every observation belonging to it.

        The session row is the governance record's root: steps and approvals
        are meaningless without it, so the delete is deliberately transitive.
        """
        async with self.sc.sessionmaker() as session:
            row = await session.get(AgentSessionRow, session_id)
            if row is None:
                raise NotFoundError(f"agent session {session_id} not found")
            await session.execute(delete(AgentStepRow).where(AgentStepRow.session_id == session_id))
            await session.execute(delete(AgentApprovalRow).where(AgentApprovalRow.session_id == session_id))
            await session.delete(row)
            await session.commit()
        return {"deleted": session_id}

    async def delete_approval(self, approval_id: int) -> dict[str, Any]:
        """Delete one approval row (a dismissed/stale write request)."""
        async with self.sc.sessionmaker() as session:
            row = await session.get(AgentApprovalRow, approval_id)
            if row is None:
                raise NotFoundError(f"agent approval {approval_id} not found")
            await session.delete(row)
            await session.commit()
        return {"deleted": approval_id}

    async def finish_session(self, session_id: int, result: dict | None) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            row = (await session.execute(
                select(AgentSessionRow).where(AgentSessionRow.id == session_id)
            )).scalar_one_or_none()
            if row is None:
                raise NotFoundError(f"agent session {session_id} not found")
            if row.status == "finished":
                raise AgentServiceError(f"agent session {session_id} is already finished")
            row.status = "finished"
            row.finished_at = row.finished_at or _utcnow()
            row.result = result
            await session.commit()
            return {"id": row.id, "status": row.status}

    def _session_view(self, row: AgentSessionRow, tools: dict[str, ToolDef] | None = None,
                      *, steps: list[dict] | None = None) -> dict[str, Any]:
        view: dict[str, Any] = {
            "id": row.id, "plugin": row.plugin, "principal": row.principal,
            "driver": row.driver,
            "task": row.task, "status": row.status,
            "budget": {"steps": row.budget_steps, "wall_ms": row.budget_wall_ms,
                       "writes": row.budget_writes, "writes_used": row.writes_used,
                       "steps_used": row.steps_used},
            "catalog_hash": row.catalog_hash,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "result": row.result,
            "run_count": row.run_count,
            "run_started_at": row.run_started_at.isoformat() if row.run_started_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        }
        if tools is not None:
            view["tools"] = {n: t.to_meta() for n, t in tools.items()}
        if steps is not None:
            view["steps"] = steps
        return view

    @staticmethod
    def _step_view(step: AgentStepRow) -> dict[str, Any]:
        return {
            "seq": step.seq, "tool": step.tool, "args": step.args_digest,
            "thought": step.thought or "",
            "driver": step.driver or "",
            "outcome": step.outcome, "detail": step.detail,
            "latency_ms": step.latency_ms, "revision_id": step.revision_id,
            "approval_id": step.approval_id,
            "run_no": step.run_no,
        }

    async def decide(self, approval_id: int, decision: str, principal: dict) -> dict:
        """Human gate for agent writes (I3), shared by the API and tests.

        The approver must THEMSELVES hold the action's permit; decisions are
        audited to the human, executions to the plugin principal. A rejection
        refunds the writes slot (the write did not happen).
        """
        from datetime import datetime, timezone

        from sqlalchemy import select

        from ..errors import NotFoundError, OOError

        async with self.sc.sessionmaker() as s:
            row = (await s.execute(
                select(AgentApprovalRow).where(AgentApprovalRow.id == approval_id)
            )).scalar_one_or_none()
            if row is None:
                raise NotFoundError(f"agent approval {approval_id} not found")
            if row.status != "pending":
                raise OOError(f"approval {approval_id} is already {row.status}",
                              details={"status": row.status})

            def _close(status: str) -> None:
                row.status, row.decided_by = status, principal.get("id", "?")
                row.decided_at = datetime.now(timezone.utc)

            if decision == "rejected":
                _close("rejected")
                # refund the writes slot atomically (the write did not happen)
                await s.execute(
                    update(AgentSessionRow)
                    .where(AgentSessionRow.id == row.session_id,
                           AgentSessionRow.writes_used > 0)
                    .values(writes_used=AgentSessionRow.writes_used - 1)
                    .execution_options(synchronize_session=False))
                await s.commit()
                return {"id": row.id, "status": "rejected", "decided_by": row.decided_by}

            target = None
            if row.target_id:
                target = await self.sc.query.get(
                    s, self.sc.compiled.action_target(row.action), row.target_id, principal)
            try:
                self.sc.policy.require(principal, row.action, target)
            except Exception:
                _close("rejected")
                await s.commit()
                raise
            _close("approved")

            plug = self.sc.compiled.agent_plugins.get(row.plugin)
            agent_principal = (plug.spec.principal.as_principal()
                               if plug else {"id": f"agent:{row.plugin}"})
            try:
                rev = await self.sc.runtime.execute(s, row.action, agent_principal,
                                                    row.parameters, row.target_id)
            except OOError as exc:
                # approval granted but the runtime refused (state moved between
                # request and decision): record honestly instead of a 500
                row.status = "failed"
                await s.commit()
                return {"id": row.id, "status": "failed", "error": exc.message,
                        "decided_by": row.decided_by}
            row.status, row.revision_id = "executed", rev.id
            await s.commit()
            return {"id": row.id, "status": "executed", "revision_id": rev.id,
                    "outcome": rev.outcome, "decided_by": row.decided_by}

    # ------------------------------------------------------- engine driving

    async def set_status(self, session_id: int, status: str,
                         result: dict | None = None) -> None:
        async with self.sc.sessionmaker() as session:
            row = (await session.execute(
                select(AgentSessionRow).where(AgentSessionRow.id == session_id)
            )).scalar_one_or_none()
            if row is None:
                return
            row.status = status
            if result is not None:
                row.result = result
            if status in ("finished", "budget_exhausted", "blocked_on_approval"):
                from .models import _utcnow
                row.finished_at = _utcnow() if status != "blocked_on_approval" else row.finished_at
            await session.commit()

    async def steps_of(self, session_id: int) -> list[AgentStepRow]:
        async with self.sc.sessionmaker() as session:
            return list((await session.execute(
                select(AgentStepRow).where(AgentStepRow.session_id == session_id)
                .order_by(AgentStepRow.seq)
            )).scalars())

    # ---------------------------------------------------------- tool calls

    # ----------------------------------------------------- frozen catalog

    def _frozen_tools(self, sess: AgentSessionRow,
                      plug) -> dict[str, ToolDef]:
        """The session's OWN catalog: the frozen copy it was opened with.

        Legacy rows (pre-freeze) fall back to recomputing from the current
        plugin definition and persist the freeze -- equivalent to freezing at
        first use, never silently narrowing an already-running session.
        """
        if sess.tools_json:
            try:
                return {n: ToolDef(**meta) for n, meta in sess.tools_json.items()}
            except TypeError:  # malformed freeze -- fall through to recompute
                pass
        if plug is None or self.sc.compiled is None:
            return {}
        tools = effective_tools(self.sc.compiled, plug)
        if sess.tools_json is None and tools:
            sess.tools_json = {n: t.to_meta() for n, t in tools.items()}
        return tools

    @staticmethod
    def _wall_exceeded(sess: AgentSessionRow) -> bool:
        """wall_ms bounds ONE RUN's wall clock (run_started_at; falls back to
        created_at for rows that predate the column). 0 = unlimited."""
        if not sess.budget_wall_ms:
            return False
        started = sess.run_started_at or sess.created_at
        if started is None:
            return False
        if started.tzinfo is None:  # SQLite returns naive UTC datetimes
            started = started.replace(tzinfo=_dt.timezone.utc)
        elapsed_ms = (_utcnow() - started).total_seconds() * 1000
        return elapsed_ms > sess.budget_wall_ms

    async def read_only_tool(self, name: str, plugin_name: str | None,
                             args: dict[str, Any]) -> dict[str, Any]:
        """Session-less dispatch for read-only tools (the MCP surface's
        no-session path).

        Deliberately routed through ``_execute_tool`` -- the same dispatcher
        the session path uses -- so the two surfaces cannot drift again: the
        sessionless path used to be a copy that skipped query telemetry (making
        MCP traffic invisible to the evolution loop) and treated missing
        arguments differently. Writes are refused: sessions are the governed
        execution containers.
        """
        compiled = self.sc.compiled
        if compiled is None:
            raise OOError("service not initialized")
        tools = build_catalog(compiled)
        tdef = tools.get(name)
        if tdef is None:
            return {"outcome": "NOT_FOUND", "error": f"unknown tool {name!r}"}
        if tdef.writes:
            return {"outcome": "WRITE_REQUIRES_SESSION",
                    "error": ("writes need a governed session: call agent_open_session, "
                              "then pass plugin and session_id on every call")}

        plug = None
        if plugin_name:
            plug = compiled.agent_plugins.get(plugin_name)
            if plug is None:
                raise OOError(f"unknown agent plugin {plugin_name!r}")
            if name not in effective_tools(compiled, plug):
                return {"outcome": "AGENT_TOOL_NOT_ALLOWED",
                        "error": f"tool {name!r} is not allowed for plugin {plugin_name!r}"}

        principal = (plug.spec.principal.as_principal() if plug
                     else {"id": "mcp-agent", "Role": [], "via": "mcp-sessionless"})
        # the session path indexes required arguments strictly; converge on
        # that while keeping the MCP wire envelope structured (never a KeyError)
        for req in (tdef.input_schema or {}).get("required", []):
            if args.get(req) is None:
                return {"outcome": "ONTOGENY_ERROR",
                        "error": f"missing required argument {req!r} for tool {name!r}"}

        async with self.sc.sessionmaker() as session:
            try:
                outcome, detail, _extra = await self._execute_tool(session, tdef, principal, args)
                await session.commit()  # query telemetry from the read path
                return {"outcome": outcome, "detail": detail}
            except OOError as exc:
                # same envelope discipline as call_tool: stable outcome codes,
                # never bare exceptions through the wire (agent-paradigm §3.1)
                return {"outcome": exc.code, "error": exc.message}

    async def call_tool(self, session_id: int, tool: str, args: dict[str, Any],
                        *, engine: bool = False, thought: str = "",
                        driver: dict[str, Any] | None = None) -> dict[str, Any]:
        """The single door. Returns the tool result, or a pending-approval
        marker for gated writes.

        ``engine=True`` marks the call as coming from the session's driving
        engine; while a session is ``running``, non-engine callers get a
        structured refusal instead of interleaving with the loop.

        ``thought`` is the driver's own reasoning for choosing this call (the
        builtin engine's model output, or an external driver's rationale). It is
        recorded on the step so the UI can show the decision process, not just
        the tool calls. ``driver`` is WHO made the call when it is not the
        engine (the HTTP/MCP transport resolves it); the trail answers WHO,
        not just what (I4)."""
        started = time.perf_counter()
        async with self.sc.sessionmaker() as session:
            sess = (await session.execute(
                select(AgentSessionRow).where(AgentSessionRow.id == session_id)
            )).scalar_one_or_none()
            if sess is None:
                raise NotFoundError(f"agent session {session_id} not found")
            if sess.status not in ("open", "running", "blocked_on_approval"):
                return {"outcome": "AGENT_SESSION_CLOSED",
                        "error": f"agent session {session_id} is {sess.status}"}
            if sess.status == "running" and not engine:
                # a human / third-party driver must not interleave with the
                # engine that owns the running session (agent-paradigm §2)
                return {"outcome": "AGENT_SESSION_RUNNING",
                        "error": "session is being driven by its engine"}

            plug = self.sc.compiled.agent_plugins.get(sess.plugin)
            # the FROZEN catalog, not the current plugin definition: a promote
            # that edits the plugin mid-session cannot change what a running
            # session may call (even when the plugin row itself is gone)
            tools = self._frozen_tools(sess, plug)
            if tool not in tools:
                # structured outcomes, not exceptions: distinguish "not a tool
                # at all" (NOT_FOUND) from "not in your allow list" (403-shaped)
                if plug is not None and tool in build_catalog(self.sc.compiled):
                    return {"outcome": ToolNotAllowed.code,
                            "error": f"tool {tool!r} is not allowed for plugin {sess.plugin!r}"}
                return {"outcome": "NOT_FOUND", "error": f"unknown tool {tool!r}"}

            if self._check_expired(sess):
                return {"outcome": "AGENT_SESSION_EXPIRED",
                        "error": f"agent session {session_id} expired"}
            if self._wall_exceeded(sess):
                # the platform-side wall clock (all three budget gates are now
                # enforced): no step is recorded, the session parks as exhausted
                sess.status = "budget_exhausted"
                await session.commit()
                return {"outcome": SessionBudgetExceeded.code,
                        "error": f"wall budget exhausted ({sess.budget_wall_ms} ms per run)"}
            if sess.run_count == 0:
                sess.run_count = 1  # an external first drive is run #1

            # step budget as ONE atomic conditional increment: the check and
            # the increment are the same statement, so two concurrent drivers
            # cannot both squeeze past the cap (SQLite serializes writes, but
            # Postgres would happily lose the read-modify-write race)
            bumped = await session.execute(
                update(AgentSessionRow)
                .where(AgentSessionRow.id == session_id,
                       or_(AgentSessionRow.budget_steps == 0,
                           AgentSessionRow.steps_used < AgentSessionRow.budget_steps))
                .values(steps_used=AgentSessionRow.steps_used + 1)
                .execution_options(synchronize_session=False))
            if bumped.rowcount == 0:
                # structured outcome, not an exception: agents need a
                # machine-readable stop signal, and no step is recorded
                return {"outcome": SessionBudgetExceeded.code,
                        "error": f"step budget exhausted ({sess.budget_steps})"}
            await session.refresh(sess, ["steps_used"])
            seq = sess.steps_used

            who = ("engine" if engine
                   else (driver or {}).get("id")
                   or ((sess.driver or {}).get("id"))
                   or "external")
            step = AgentStepRow(session_id=session_id, seq=seq, tool=tool,
                                args_digest=args_digest(args if isinstance(args, dict) else {}),
                                thought=(thought or "")[:4000],
                                driver=str(who)[:200],
                                run_no=max(sess.run_count, 1))
            session.add(step)
            try:
                outcome, detail, extra = await self._execute_tool(
                    session, tools[tool], self._principal_of(plug, sess), args,
                    plug=plug, sess_row=sess)
            except OOError as exc:
                step.outcome = exc.code
                step.detail = {"message": exc.message}
                await session.commit()
                return {"outcome": exc.code, "error": exc.message, "step": seq}
            step.outcome = outcome
            step.detail = _jsonable(detail)
            step.revision_id = extra.get("revision_id")
            step.approval_id = extra.get("approval_id")
            step.latency_ms = round((time.perf_counter() - started) * 1000, 2)
            # writes slots are consumed (and refunded) inside _execute_action,
            # atomically with the decision that caused them
            await session.commit()
            return {
                "outcome": outcome,
                **({"detail": detail} if detail is not None else {}),
                **extra,
                "step": seq,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }

    @staticmethod
    def _principal_of(plug, sess: AgentSessionRow) -> dict[str, Any]:
        """The frozen plugin principal. The plugin row may have vanished from
        the registry mid-session; the session froze its identity at open."""
        if plug is not None:
            return plug.spec.principal.as_principal()
        return {"id": sess.principal or f"agent:{sess.plugin}"}

    @staticmethod
    async def _atomic_bump_writes(session, session_id: int) -> bool:
        """Atomically consume one writes slot; False when the ceiling hit."""
        res = await session.execute(
            update(AgentSessionRow)
            .where(AgentSessionRow.id == session_id,
                   or_(AgentSessionRow.budget_writes == 0,
                       AgentSessionRow.writes_used < AgentSessionRow.budget_writes))
            .values(writes_used=AgentSessionRow.writes_used + 1)
            .execution_options(synchronize_session=False))
        return res.rowcount > 0

    @staticmethod
    async def _atomic_refund_writes(session, session_id: int) -> None:
        """Give back one writes slot (the write did not happen after all)."""
        await session.execute(
            update(AgentSessionRow)
            .where(AgentSessionRow.id == session_id,
                   AgentSessionRow.writes_used > 0)
            .values(writes_used=AgentSessionRow.writes_used - 1)
            .execution_options(synchronize_session=False))

    async def _execute_tool(self, session, tdef: ToolDef, principal: dict, args: dict[str, Any],
                            plug=None, sess_row: AgentSessionRow | None = None,
                            ) -> tuple[str, Any, dict[str, Any]]:
        """Dispatch one tool against ServiceContext. Returns (outcome, detail, extra)."""
        sc = self.sc
        if tdef.kind == "meta":
            return "ok", sc.compiled.to_meta(), {}
        if tdef.kind == "search":
            limit = int(args.get("limit") or 20)
            started = time.perf_counter()
            try:
                out = await sc.query.query(session, tdef.target, principal,
                                           filt=args.get("filter"), limit=limit)
            except OOError:
                # agent queries are fitness signal too: the evolution loop reads
                # these rows to find filter fields the schema never modelled
                # (the HTTP query door records the same thing)
                await sc.telemetry.record_query(
                    session, tdef.target, principal, args.get("filter"),
                    (time.perf_counter() - started) * 1000, 0, error=True,
                )
                raise
            await sc.telemetry.record_query(
                session, tdef.target, principal, args.get("filter"),
                out["latency_ms"], out["total"],
            )
            return "ok", out, {}
        if tdef.kind == "traverse":
            out = await sc.query.traverse(session, args["start_type"], args["start_ids"],
                                          principal, args["path"])
            return "ok", out, {}
        if tdef.kind == "call":
            fn = sc.compiled.functions.get(tdef.target)
            if fn is None:
                raise NotFoundError(f"unknown function {tdef.target!r}")
            value = await sc.functions.run(session, fn, args.get("parameters") or {})
            return "ok", value, {}
        if tdef.kind == "act":
            return await self._execute_action(session, tdef, principal, args, plug, sess_row)
        raise AgentServiceError(f"unhandled tool kind {tdef.kind!r}")

    async def _execute_action(self, session, tdef: ToolDef, principal: dict,
                              args: dict[str, Any], plug, sess_row: AgentSessionRow,
                              ) -> tuple[str, Any, dict[str, Any]]:
        """Writes: validate first (free, no writes), then the approval gate.

        The gate comes from the CURRENT plugin row -- the one piece of the
        contract not frozen (identity, budget and catalog are). When the plugin
        has vanished from the registry mid-session the gate falls back to
        ``confirm`` and the auto whitelist is treated as empty: the most
        conservative posture available, never a silent widening.
        """
        sc = self.sc
        params = args.get("parameters") or {}
        target_id = args.get("target_id")

        # free pre-check so agents can plan: identical to the human validate API
        try:
            await sc.runtime.validate(session, tdef.target, principal, params, target_id)
        except OOError:
            raise  # validate already carries stable codes (RULE_REJECTED, ...)

        gate = plug.spec.approval.writes if plug is not None else "confirm"
        if gate == "never":
            raise PolicyDeniedError(f"plugin {sess_row.plugin!r} is read-only (approval.writes=never)")
        if gate == "confirm":
            # the pending intent consumes the writes budget ATOMICALLY and up
            # front; a human rejection refunds it (the write did not happen --
            # see decision API)
            if not await self._atomic_bump_writes(session, sess_row.id):
                return (SessionBudgetExceeded.code, None,
                        {"error": f"writes budget exhausted ({sess_row.budget_writes})"})
            approval = AgentApprovalRow(
                session_id=sess_row.id, plugin=sess_row.plugin,
                tool=tdef.name, action=tdef.target,
                parameters=params, target_id=target_id,
                rationale=str(args.get("rationale") or ""),
            )
            session.add(approval)
            await session.flush()
            return "pending_approval", {
                "message": "write requires human approval",
                "approval_id": approval.id,
                "action": tdef.target, "parameters": params, "target_id": target_id,
            }, {"approval_id": approval.id, "write": False}

        # auto gate (M3): only the actions listed in auto_actions skip the
        # queue; a vanished plugin row means the whitelist is unknowable.
        # The budget is the HARD gate and is checked first (same outcome
        # order as the REST surface): occupy one writes slot atomically,
        # refund it when the whitelist refuses or the execution fails.
        if not await self._atomic_bump_writes(session, sess_row.id):
            return (SessionBudgetExceeded.code, None,
                    {"error": f"writes budget exhausted ({sess_row.budget_writes})"})
        if plug is None or tdef.name not in set(plug.spec.approval.auto_actions):
            await self._atomic_refund_writes(session, sess_row.id)
            raise PolicyDeniedError(
                f"action {tdef.target!r} is not in the plugin's auto_actions list")
        try:
            rev = await sc.runtime.execute(session, tdef.target, principal, params, target_id,
                                           expected_revision=args.get("expected_revision"))
        except OOError:
            # a refused/failed execution consumed nothing in the end
            await self._atomic_refund_writes(session, sess_row.id)
            raise
        await session.commit()
        return rev.outcome, {"revision_id": rev.id, "object_id": rev.object_id}, {
            "revision_id": rev.id, "write": False,  # accounted above
        }

