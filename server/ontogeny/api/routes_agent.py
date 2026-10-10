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
"""Agent plugin surfaces: sessions, tools, approvals (one governance door)."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select

from ..errors import NotFoundError, OOError
from ..service import ServiceContext
from .deps import get_principal, get_sc, require_admin
from .schemas import (AgentDecisionBody, AgentFinishBody, AgentRunBody,
                      AgentSessionBody, AgentToolBody)


def register(r: APIRouter, sc: ServiceContext) -> None:
    # ---- agent plugins (external agents; same governance, no second door) --

    def _require_driver(principal: dict, sc: ServiceContext) -> dict:
        """WHO drives the session is now authenticated (A2).

        With ``dev_auth`` on (the default, CI/demo) any caller may drive --
        the identity is recorded, not ignored. With it off, the agent surfaces
        require a real signed-in principal (cookie or bearer); anonymous is
        refused: the plugin principal is the EXECUTION identity, and somebody
        has to be accountable for asking it to run.
        """
        if not principal.get("authenticated") and not sc.settings.dev_auth:
            raise HTTPException(401, "agent surfaces require an authenticated driver "
                                     "(sign in, or send the bearer token from /auth/login)")
        return principal

    @r.get("/agent/plugins")
    async def agent_plugins(sc: ServiceContext = Depends(get_sc)):
        return {"plugins": sc.agents.list_plugins()}

    @r.post("/agent/sessions")
    async def agent_session_open(body: AgentSessionBody, sc: ServiceContext = Depends(get_sc),
                                 principal: dict = Depends(get_principal)):
        _require_driver(principal, sc)
        expires = None
        if body.expires_at:
            import datetime as _dt

            try:
                expires = _dt.datetime.fromisoformat(body.expires_at.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(400, "expires_at must be an ISO instant")
        return await sc.agents.open_session(
            body.plugin, body.task,
            budget=body.budget.model_dump(exclude_none=True) if body.budget else None,
            expires_at=expires, driver=principal)

    @r.get("/agent/sessions")
    async def agent_sessions(plugin: str | None = None, limit: int = 50,
                             sc: ServiceContext = Depends(get_sc),
                             principal: dict = Depends(get_principal)):
        _require_driver(principal, sc)
        return {"sessions": await sc.agents.list_sessions(plugin=plugin, limit=min(limit, 200))}

    @r.get("/agent/sessions/{session_id}")
    async def agent_session_get(session_id: int, sc: ServiceContext = Depends(get_sc),
                                principal: dict = Depends(get_principal)):
        _require_driver(principal, sc)
        return await sc.agents.get_session(session_id)

    @r.delete("/agent/sessions/{session_id}")
    async def agent_session_delete(session_id: int, sc: ServiceContext = Depends(get_sc),
                                   principal: dict = Depends(get_principal)):
        _require_driver(principal, sc)
        return await sc.agents.delete_session(session_id)

    @r.post("/agent/sessions/{session_id}/run")
    async def agent_session_run(session_id: int, background: BackgroundTasks,
                                body: AgentRunBody | None = None,
                                sc: ServiceContext = Depends(get_sc),
                                principal: dict = Depends(get_principal)):
        """Engine dispatcher (agent-paradigm §3): hand the session to the
        engine declared by its plugin. builtin-llm drives in-process (202,
        loop in background); external-push would delegate remotely (reserved);
        external-pull is driven FROM outside, so we return the how-to instead."""

        # run spends the session's budget and can auto-execute writes: it is
        # exactly the kind of surface the driver gate exists for (open and
        # tool-call already had it; this one was missed).
        _require_driver(principal, sc)

        sess = await sc.agents.get_session(session_id)  # 404 when unknown
        plug = sc.compiled.agent_plugins.get(sess["plugin"]) if sc.compiled else None
        if plug is None:
            raise NotFoundError(f"plugin {sess['plugin']!r} not found")
        kind = plug.spec.engine.kind
        if sess["status"] == "running":
            return {"id": session_id, "status": "running"}
        # direction 3: a session may be driven many times -- every run bumps
        # the counter and its steps are tagged, so each pass leaves its own
        # trace. A finished/exhausted session is re-opened for the new drive.
        await sc.agents.start_run(session_id, task=(body.task if body else None))

        if kind == "external-pull":
            raise OOError(
                "this plugin is driven by an external engine",
                details={"engine": kind,
                         "how": ("drive the session over the session protocol -- "
                                 "MCP at /mcp (agent_open_session, then tools with "
                                 "plugin/session_id) or REST: POST /api/v1/agent/"
                                 "sessions/{id}/tools/{tool}; see "
                                 "docs/architecture/05-agent-governance.md §5.2")})

        # generic engine dispatch (agent-paradigm §3.1): extensions register
        # kind -> factory(sc); the dispatcher never names a concrete engine
        factory = sc.agent_engines.get(kind)
        if factory is None:
            raise OOError(
                f"engine kind {kind!r} is declared but no engine is registered "
                "(the providing extension is not loaded)",
                details={"code": "AGENT_ENGINE_UNAVAILABLE"})
        engine = factory(sc)
        # engines that drive via an LLM carry an ``llm`` attribute; None means
        # the capability is absent (no provider extension / no ONTOGENY_LLM_BASE_URL)
        if getattr(engine, "llm", "n/a") is None:
            raise OOError(
                "this engine requires the platform LLM (ONTOGENY_LLM_BASE_URL) to be configured",
                details={"code": "LLM_NOT_CONFIGURED"})

        async def _drive():
            try:
                await engine.drive(session_id)
            except Exception as exc:  # noqa: BLE001 -- a dying engine must
                # still release the session (back to `open`, error recorded --
                # a crashed run must not strand the session in `running`)
                await sc.agents.set_status(
                    session_id, "open", {"error": f"engine crashed: {exc}"})

        # async background task: Starlette awaits it on the event loop AFTER the
        # response is sent. (Wrapping in asyncio.create_task ran it via a worker
        # thread with no running loop -> RuntimeError, engine never drove.)
        background.add_task(_drive)
        return {"id": session_id, "status": "running"}

    @r.post("/agent/sessions/{session_id}/finish")
    async def agent_session_finish(session_id: int, body: AgentFinishBody,
                                   sc: ServiceContext = Depends(get_sc),
                                   principal: dict = Depends(get_principal)):
        _require_driver(principal, sc)
        return await sc.agents.finish_session(session_id, body.result)

    @r.post("/agent/sessions/{session_id}/tools/{tool}")
    async def agent_tool_call(session_id: int, tool: str, body: AgentToolBody,
                              sc: ServiceContext = Depends(get_sc),
                              driver: dict = Depends(get_principal)):
        _require_driver(driver, sc)
        # agent-trace is a declared observability source (evolution policy), and
        # the agent_tool_error detector reads this table -- but nothing ever
        # wrote it. Record the outcome class of every call; failures (refusals,
        # rule rejections) carry their code as the error.
        try:
            payload = body.model_dump(exclude_none=True)
            # `thought` describes the call, it is not part of its arguments
            thought = str(payload.pop("thought", "") or "")
            out = await sc.agents.call_tool(session_id, tool, payload, thought=thought,
                                            driver=driver)
        except Exception as exc:
            async with sc.sessionmaker() as s:
                await sc.telemetry.record_agent(s, tool, error=f"{type(exc).__name__}: {exc}")
                await s.commit()
            raise
        error = None if out.get("outcome") == "ok" else str(out.get("error") or out.get("outcome"))
        async with sc.sessionmaker() as s:
            await sc.telemetry.record_agent(s, tool, error=error)
            await s.commit()
        return out

    @r.get("/agent/approvals")
    async def agent_approvals(status: str = "pending", sc: ServiceContext = Depends(get_sc),
                              principal: dict = Depends(get_principal)):
        _require_driver(principal, sc)

        from ..agent.models import AgentApprovalRow

        async with sc.sessionmaker() as s:
            # "decided" = everything past its gate (approved/executed/rejected/
            # failed): the console shows the audit trail next to the queue
            if status == "decided":
                where = AgentApprovalRow.status.in_(("approved", "rejected", "executed", "failed"))
            else:
                where = AgentApprovalRow.status == status
            rows = (await s.execute(
                select(AgentApprovalRow).where(where)
                .order_by(AgentApprovalRow.id.desc()).limit(100)
            )).scalars().all()
        return {"approvals": [{
            "id": a.id, "session_id": a.session_id, "plugin": a.plugin,
            "tool": a.tool, "action": a.action, "parameters": a.parameters,
            "target_id": a.target_id, "rationale": a.rationale, "status": a.status,
            "decided_by": a.decided_by,
            "decided_at": a.decided_at.isoformat() if a.decided_at else None,
            "requested_at": a.requested_at.isoformat() if a.requested_at else None,
        } for a in rows]}

    @r.get("/agent/plugins/{plugin_name}/resource")
    async def agent_plugin_resource(plugin_name: str, sc: ServiceContext = Depends(get_sc)):
        """The plugin's raw DSL resource for the editor: load -> edit -> save
        must round-trip losslessly (engine/transport/deny/auto_actions are not
        visible in the compiled view the console lists)."""
        plug = (sc.compiled.agent_plugins or {}).get(plugin_name) if sc.compiled else None
        if plug is None:
            raise HTTPException(404, f"unknown plugin {plugin_name!r}")
        return {"resource": plug.model_dump(mode="json", by_alias=True, exclude_none=True)}

    @r.post("/agent/approvals/{approval_id}/decision")
    async def agent_approval_decision(approval_id: int, body: AgentDecisionBody,
                                      sc: ServiceContext = Depends(get_sc),
                                      principal: dict = Depends(get_principal)):
        """Human gate for agent writes (invariant I3) -- logic lives in the
        broker so the engine resume path and the API share one implementation."""
        _require_driver(principal, sc)
        return await sc.agents.decide(approval_id, body.decision, principal)

    @r.delete("/agent/approvals/{approval_id}")
    async def agent_approval_delete(approval_id: int, _: dict = Depends(require_admin),
                                    sc: ServiceContext = Depends(get_sc)):
        # deleting a decided approval erases a piece of the audit trail
        # (decided_by is part of the accountability chain): operator only.
        return await sc.agents.delete_approval(approval_id)
