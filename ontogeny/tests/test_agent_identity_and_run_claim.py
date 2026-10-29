# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Session identity snapshots and competing HTTP engine runs."""

import asyncio
import json
import os

import httpx
import pytest
from test_agent_engine import sc as _sc
from test_agent_governance import _make

from ontogeny.agent.models import AgentSessionRow
from ontogeny.api import build_app
from ontogeny.errors import OOError

agent_sc = _sc


async def test_session_principal_does_not_gain_new_plugin_roles(agent_sc):
    sc = agent_sc
    plug = sc.compiled.agent_plugins["planning-copilot"]
    plug.spec.principal.Role = ["operator"]
    plug.spec.approval.writes = "auto"
    plug.spec.approval.auto_actions = ["act_release_production_order"]
    sid = (await sc.agents.open_session("planning-copilot", "release"))["id"]
    plug.spec.principal.Role = ["planner"]
    result = await sc.agents.call_tool(sid, "act_release_production_order", {"target_id": "PO-1002"})
    assert result["outcome"] != "executed"
    async with sc.sessionmaker() as db:
        order = await sc.repo.get(db, "production-order", "PO-1002")
    assert order["status"] == "PLANNED"


async def test_session_principal_does_not_gain_new_markings(agent_sc):
    sc = agent_sc
    plug = sc.compiled.agent_plugins["planning-copilot"]
    plug.spec.tools.allow.append("search_material")
    sid = (await sc.agents.open_session("planning-copilot", "read"))["id"]
    plug.spec.principal.markings = ["internal"]
    result = await sc.agents.call_tool(sid, "search_material", {"filter": {"material_id": "M-102"}})
    assert result["outcome"] == "ok"
    assert result["detail"]["objects"][0]["unit_cost"] == "__masked__"


async def test_approval_uses_session_principal_not_changed_plugin(agent_sc):
    sc = agent_sc
    plug = sc.compiled.agent_plugins["planning-copilot"]
    plug.spec.principal.Role = ["operator"]
    sid = (await sc.agents.open_session("planning-copilot", "release"))["id"]
    pending = await sc.agents.call_tool(sid, "act_release_production_order", {"target_id": "PO-1002"})
    assert pending["outcome"] == "pending_approval"
    plug.spec.principal.Role = ["planner"]
    result = await sc.agents.decide(pending["approval_id"], "approved", {"id": "human", "Role": ["planner"]})
    assert result["status"] == "failed"
    async with sc.sessionmaker() as db:
        order = await sc.repo.get(db, "production-order", "PO-1002")
    assert order["status"] == "PLANNED"


async def test_old_session_without_claim_snapshot_fails_closed(agent_sc):
    sc = agent_sc
    sid = (await sc.agents.open_session("planning-copilot", "legacy"))["id"]
    async with sc.sessionmaker() as db:
        row = await db.get(AgentSessionRow, sid)
        row.principal_snapshot = None
        await db.commit()
    result = await sc.agents.call_tool(sid, "search_work_center", {})
    assert "open a new session" in result.get("error", "")
    with pytest.raises(OOError, match="open a new session"):
        await sc.agents.start_run(sid, claim=True)


async def test_overlapping_http_runs_start_one_engine(agent_sc):
    sc = agent_sc
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    class PausedEngine:
        async def drive(self, session_id):
            calls.append(session_id)
            entered.set()
            await release.wait()
            await sc.agents.set_status(session_id, "open")

    sc.agent_engines["builtin-llm"] = lambda _: PausedEngine()
    sid = (await sc.agents.open_session("planning-copilot", "race", driver={"id": "driver"}))["id"]
    transport = httpx.ASGITransport(app=build_app(sc))
    headers = {"X-Ontogeny-Principal": json.dumps({"id": "driver", "authenticated": True})}
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        first = asyncio.create_task(client.post(f"/api/v1/agent/sessions/{sid}/run", json={}))
        await asyncio.wait_for(entered.wait(), timeout=5)
        try:
            second = await asyncio.wait_for(client.post(f"/api/v1/agent/sessions/{sid}/run", json={}), timeout=5)
        finally:
            release.set()
        assert (await first).status_code == 200
        assert second.status_code == 200
    assert calls == [sid]
    assert (await sc.agents.get_session(sid))["run_count"] == 1


async def test_concurrent_claims_have_one_winner(agent_sc):
    sc = agent_sc
    sid = (await sc.agents.open_session("planning-copilot", "race", driver={"id": "driver"}))["id"]
    claims = await asyncio.gather(*(sc.agents.start_run(sid, principal={"id": "driver"}, claim=True) for _ in range(2)))
    assert sum(claim["started"] for claim in claims) == 1
    assert (await sc.agents.get_session(sid))["run_count"] == 1


@pytest.mark.skipif(not os.environ.get("ONTOGENY_PG_DSN"), reason="PostgreSQL integration requires ONTOGENY_PG_DSN")
async def test_concurrent_run_claim_on_postgres(golden_pkg_path, tmp_path):
    sc = await _make(golden_pkg_path, tmp_path, db_dsn=os.environ["ONTOGENY_PG_DSN"])
    try:
        sid = (await sc.agents.open_session("planning-copilot", "race", driver={"id": "driver"}))["id"]
        claims = await asyncio.gather(
            *(sc.agents.start_run(sid, principal={"id": "driver"}, claim=True) for _ in range(8))
        )
        assert sum(claim["started"] for claim in claims) == 1
        assert (await sc.agents.get_session(sid))["run_count"] == 1
    finally:
        await sc.engine.dispose()
