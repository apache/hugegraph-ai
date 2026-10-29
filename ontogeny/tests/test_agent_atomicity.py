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
# specific language governing permissions and
# limitations under the License.

"""Real action effects and approval races must remain atomic."""

# The imported pytest fixture is intentionally injected by name below.
# ruff: noqa: F811

import asyncio

import pytest
from sqlalchemy import select
from test_agent_approval import PLANNER, _pending_approval, client  # noqa: F401

from ontogeny.action.models import RevisionRow
from ontogeny.agent.models import AgentApprovalRow
from ontogeny.core.models import ModifyTargetEffect
from ontogeny.errors import OOError


def _fail_second_effect(sc):
    action = sc.compiled.actions["release-production-order"]
    action.spec.effects.append(ModifyTargetEffect(kind="modify-target", set={"qty": "invalid_quantity"}))


async def _order(sc):
    async with sc.sessionmaker() as db:
        return await sc.repo.get(db, "production-order", "PO-1002")


@pytest.mark.parametrize("approval", [False, True])
async def test_failed_second_effect_rolls_back_first_but_records_outcome(client, approval):
    c, sc = client
    before = await _order(sc)
    if approval:
        pending = await _pending_approval(c)
        sid = pending["session"]["id"]
        _fail_second_effect(sc)
        result = await sc.agents.decide(pending["approval_id"], "approved", PLANNER)
        assert result["status"] == "failed"
        listed = (await c.get("/api/v1/agent/approvals?status=decided")).json()["approvals"]
        assert listed[0]["failure_reason"] == result["error"]
    else:
        plugin = sc.compiled.agent_plugins["planning-copilot"]
        plugin.spec.approval.writes = "auto"
        plugin.spec.approval.auto_actions = ["act_release_production_order"]
        session = await sc.agents.open_session("planning-copilot", "release")
        sid = session["id"]
        _fail_second_effect(sc)
        result = await sc.agents.call_tool(
            sid, "act_release_production_order", {"parameters": {}, "target_id": "PO-1002"}
        )
        assert result["outcome"] != "ok"
    after = await _order(sc)
    assert after == before
    async with sc.sessionmaker() as db:
        revisions = (await db.execute(select(RevisionRow).where(RevisionRow.object_id == "PO-1002"))).scalars().all()
        assert not any(r.outcome == "executed" for r in revisions)
    session = await sc.agents.get_session(sid)
    if not approval:
        assert session["steps"][-1]["outcome"] == result["outcome"]
        assert session["budget"]["writes_used"] == 0


@pytest.mark.parametrize("override", [0, -1])
async def test_nonpositive_session_override_cannot_remove_plugin_limits(client, override):
    _, sc = client
    result = await sc.agents.open_session(
        "planning-copilot", "", budget={"steps": override, "wall_ms": override, "writes_per_session": override}
    )
    assert result["budget"]["steps"] > 0
    assert result["budget"]["wall_ms"] > 0
    assert result["budget"]["writes"] > 0


async def test_positive_session_override_tightens_plugin_limits(client):
    _, sc = client
    result = await sc.agents.open_session(
        "planning-copilot", "", budget={"steps": 2, "wall_ms": 100, "writes_per_session": 1}
    )
    assert (result["budget"]["steps"], result["budget"]["wall_ms"], result["budget"]["writes"]) == (2, 100, 1)


@pytest.mark.parametrize("decisions", [("approved", "approved"), ("rejected", "rejected"), ("approved", "rejected")])
async def test_two_simultaneous_decisions_consume_intent_once(client, monkeypatch, decisions):
    c, sc = client
    pending = await _pending_approval(c)
    original = sc.repo.get
    arrived = 0
    ready = asyncio.Event()

    async def synchronize_approvers(*args, **kwargs):
        nonlocal arrived
        result = await original(*args, **kwargs)
        if kwargs.get("for_update"):
            return result
        arrived += 1
        if arrived == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=5)
        return result

    monkeypatch.setattr(sc.repo, "get", synchronize_approvers)
    results = await asyncio.gather(
        sc.agents.decide(pending["approval_id"], decisions[0], PLANNER),
        sc.agents.decide(pending["approval_id"], decisions[1], PLANNER),
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) and r["status"] in ("executed", "rejected") for r in results) == 1, results
    assert sum(isinstance(r, OOError) for r in results) == 1, results
    async with sc.sessionmaker() as db:
        approval = await db.get(AgentApprovalRow, pending["approval_id"])
        revisions = (await db.execute(select(RevisionRow).where(RevisionRow.object_id == "PO-1002"))).scalars().all()
    assert approval.status in ("executed", "rejected")
    assert sum(r.outcome == "executed" for r in revisions) == int(approval.status == "executed")
    if approval.status == "rejected":
        session = await sc.agents.get_session(pending["session"]["id"])
        assert session["budget"]["writes_used"] == 0


async def test_approval_preserves_expected_revision(client):
    from ontogeny.stores.repo import utcnow

    _, sc = client
    session = await sc.agents.open_session("planning-copilot", "release")
    before = await _order(sc)
    pending = await sc.agents.call_tool(
        session["id"],
        "act_release_production_order",
        {"parameters": {}, "target_id": "PO-1002", "expected_revision": before["_rev"]},
    )
    assert pending["outcome"] == "pending_approval"
    async with sc.sessionmaker() as db:
        await sc.repo.action_update(db, "production-order", "PO-1002", {"qty": before["qty"] + 1}, utcnow())
        await db.commit()
    result = await sc.agents.decide(pending["approval_id"], "approved", PLANNER)
    assert result["status"] == "failed"
    after = await _order(sc)
    assert after["status"] == "PLANNED"
    assert after["qty"] == before["qty"] + 1


async def test_existing_approval_table_gets_nullable_revision_column(tmp_path):
    from sqlalchemy import text

    from ontogeny.db import init_schema, make_engine

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'old.db'}")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE ontogeny_agent_approval (id INTEGER PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO ontogeny_agent_approval (id) VALUES (1)"))
    await init_schema(engine)
    async with engine.connect() as conn:
        value = (
            await conn.execute(text("SELECT expected_revision FROM ontogeny_agent_approval WHERE id = 1"))
        ).scalar_one()
        assert value is None
    await engine.dispose()


@pytest.mark.parametrize(
    "policy",
    [
        'permit(principal in Role::"other", action == Action::"invoke-order-yield", resource);',
        'forbid(principal, action == Action::"invoke-order-yield", resource);',
    ],
)
async def test_function_invoke_policy_applies_to_rest_and_agent_tools(client, policy):
    from test_agent_approval import _hdr

    from ontogeny.mcp_server import in_process_mcp_session
    from ontogeny.policy.engine import PolicyEngine

    c, sc = client
    sc.compiled.cedar_texts["function-guard"] = policy
    sc.policy = PolicyEngine(sc.compiled)
    sc.compiled.agent_plugins["planning-copilot"].spec.tools.allow.append("call_order_yield")
    params = {"order_id": "PO-1002"}
    rest = await c.post("/api/v1/functions/order-yield/invoke", json={"parameters": params}, headers=_hdr(PLANNER))
    assert rest.status_code == 403
    agent = await sc.agents.open_session("planning-copilot", "")
    governed = await sc.agents.call_tool(agent["id"], "call_order_yield", {"parameters": params})
    assert governed["outcome"] == "POLICY_DENIED"
    sessionless = await sc.agents.read_only_tool("call_order_yield", "planning-copilot", {"parameters": params})
    assert sessionless["outcome"] == "POLICY_DENIED"
    async with in_process_mcp_session(sc, engine_mode=False) as mcp:
        result = await mcp.call_tool("call_order_yield", {"plugin": "planning-copilot", "parameters": params})
        assert result["outcome"] == "POLICY_DENIED"


@pytest.mark.parametrize(
    "policy", ["", 'permit(principal in Role::"planner", action == Action::"invoke-order-yield", resource);']
)
async def test_function_without_restrictive_invoke_policy_stays_available(client, policy):
    from test_agent_approval import _hdr

    from ontogeny.policy.engine import PolicyEngine

    c, sc = client
    sc.compiled.cedar_texts["function-guard"] = policy
    sc.policy = PolicyEngine(sc.compiled)
    sc.compiled.agent_plugins["planning-copilot"].spec.tools.allow.append("call_order_yield")
    params = {"order_id": "PO-1002"}
    rest = await c.post("/api/v1/functions/order-yield/invoke", json={"parameters": params}, headers=_hdr(PLANNER))
    assert rest.status_code == 200
    agent = await sc.agents.open_session("planning-copilot", "")
    governed = await sc.agents.call_tool(agent["id"], "call_order_yield", {"parameters": params})
    assert governed["outcome"] == "ok"
    sessionless = await sc.agents.read_only_tool("call_order_yield", "planning-copilot", {"parameters": params})
    assert sessionless["outcome"] == "ok"
