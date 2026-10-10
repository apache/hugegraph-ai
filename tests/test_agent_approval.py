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
"""M2: the human approval gate for agent writes.

Invariants under test:
- a pending write executes NOTHING until a human decides (already covered in
  test_agent.TestBroker.test_write_without_approval_is_pending);
- approving executes the action under the PLUGIN principal, audited to both;
- rejecting refuses the write and frees nothing;
- the approver must THEMSELVES hold the action's Cedar permit (I3: no
  permission laundering through the approval endpoint);
- a decision is single-shot (no double-execution).

The write under test is release-production-order: planners own it, and its
permit carries a row-level condition (resource.status == "PLANNED"), so the
same gates a human planner goes through bind agents too.
"""
from __future__ import annotations

import json
import shutil

import httpx
import pytest_asyncio

from ontogeny.agent.models import AgentApprovalRow
from ontogeny.api import build_app
from ontogeny.config import Settings
from ontogeny.demo import seed_from_package
from ontogeny.service import ServiceContext

PLUGIN = """\
apiVersion: ontogeny/v1
kind: AgentPlugin
metadata:
  name: planning-copilot
  display: Planning copilot
spec:
  principal:
    id: "agent:planning-copilot"
    Role: [planner]
    site: plant-north
  transport: { kind: http }
  tools:
    allow: [describe_ontology, search_production_order, act_release_production_order]
  approval: { writes: confirm }
  budget: { steps: 25, wall_ms: 60000, writes_per_session: 3 }
"""

PLANNER = {"id": "u-planner", "Role": ["planner"], "site": "plant-north"}
VISITOR = {"id": "u-visitor", "Role": ["visitor"]}


def _hdr(p):
    return {"X-Ontogeny-Principal": json.dumps(p)}


def _sc_settings(tmp_path, src) -> Settings:
    return Settings(
        dev_auth=True,
        db_dsn=f"sqlite+aiosqlite:///{tmp_path/'main.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}",
             "WMS_WEBHOOK": "https://wms.example.test/hook"},
    )


@pytest_asyncio.fixture()
async def client(golden_pkg_path, tmp_path):
    root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, root)
    (root / "agents").mkdir(exist_ok=True)
    # the package ships its own plugins; these tests exercise one injected
    # plugin in isolation, so start the copy from an empty agents/ dir
    for f in (root / "agents").glob("*.yaml"):
        f.unlink()
    (root / "agents" / "copilot.yaml").write_text(PLUGIN, encoding="utf-8")
    src = tmp_path / "erp.db"
    # the package owns its source data: execute its own seed SQL so the tables
    # match the ontology exactly
    seed_from_package(golden_pkg_path, src, force=True)
    sc = ServiceContext(_sc_settings(tmp_path, src), str(root))
    await sc.initialize()
    for t in sc.compiled.objects:
        await sc.sync(t)
    app = build_app(sc)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, sc


async def _pending_approval(c) -> dict:
    session = (await c.post("/api/v1/agent/sessions",
                            json={"plugin": "planning-copilot", "task": "release PO-1002"})).json()
    out = (await c.post("/api/v1/agent/sessions/1/tools/act_release_production_order", json={
        "parameters": {},
        "target_id": "PO-1002",
        "rationale": "PO-1002 is PLANNED with NORMAL priority and due 2026-10-30",
    })).json()
    assert out["outcome"] == "pending_approval", out
    approvals = (await c.get("/api/v1/agent/approvals")).json()["approvals"]
    assert len(approvals) == 1
    return out | {"session": session}


class TestApprovalGate:
    async def test_approve_executes_under_plugin_principal(self, client):
        c, sc = client
        pending = await _pending_approval(c)

        r = await c.post(f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
                         json={"decision": "approved"}, headers=_hdr(PLANNER))
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "executed" and body["decided_by"] == "u-planner"

        # the object actually moved
        po = (await c.get("/api/v1/objects/production-order/PO-1002", headers=_hdr(PLANNER))).json()
        assert po["status"] == "RELEASED"
        assert po["released_at"] is not None

        # audit trail carries BOTH actors: execution to the plugin, decision to the human
        async with sc.sessionmaker() as s:
            from sqlalchemy import select
            from ontogeny.action.models import RevisionRow
            revs = (await s.execute(select(RevisionRow).where(
                RevisionRow.object_id == "PO-1002"))).scalars().all()
            assert any(r.principal == "agent:planning-copilot" for r in revs)
            approval = (await s.execute(
                select(AgentApprovalRow).where(AgentApprovalRow.id == pending["approval_id"])
            )).scalar_one()
            assert approval.status == "executed" and approval.decided_by == "u-planner"
            assert approval.revision_id is not None

    async def test_reject_refuses_and_records(self, client):
        c, sc = client
        pending = await _pending_approval(c)
        r = await c.post(f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
                         json={"decision": "rejected"}, headers=_hdr(PLANNER))
        assert r.status_code == 200 and r.json()["status"] == "rejected"
        po = (await c.get("/api/v1/objects/production-order/PO-1002", headers=_hdr(PLANNER))).json()
        assert po["status"] == "PLANNED"

    async def test_approver_must_hold_the_permit_themselves(self, client):
        """I3: a principal without the action's Cedar permit cannot approve —
        approvals are not a permission laundering channel."""
        c, _ = client
        pending = await _pending_approval(c)
        r = await c.post(f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
                         json={"decision": "approved"}, headers=_hdr(VISITOR))
        assert r.status_code == 403
        # and the approval is consumed as rejected, not left dangling
        approvals = (await c.get("/api/v1/agent/approvals")).json()["approvals"]
        assert approvals == []

    async def test_decision_is_single_shot(self, client):
        c, _ = client
        pending = await _pending_approval(c)
        r1 = await c.post(f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
                          json={"decision": "approved"}, headers=_hdr(PLANNER))
        assert r1.json()["status"] == "executed"
        r2 = await c.post(f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
                          json={"decision": "approved"}, headers=_hdr(PLANNER))
        assert r2.status_code == 500  # OOError -> already decided

    async def test_writes_budget_gates_pending_intents_and_refunds_rejections(self, client):
        """Pending intents consume writes_per_session up front (no spam);
        a human rejection refunds the slot (the agent is not deadlocked by a
        decision it does not control)."""
        c, _ = client
        await c.post("/api/v1/agent/sessions",
                     json={"plugin": "planning-copilot", "task": "x"})
        ids = []
        for i in range(3):  # budget_writes = 3
            out = (await c.post("/api/v1/agent/sessions/1/tools/act_release_production_order", json={
                "parameters": {}, "target_id": "PO-1002", "rationale": f"try {i}"})).json()
            assert out["outcome"] == "pending_approval"
            ids.append(out["approval_id"])
        # 4th intent is refused with a structured budget outcome
        out = (await c.post("/api/v1/agent/sessions/1/tools/act_release_production_order", json={
            "parameters": {}, "target_id": "PO-1002", "rationale": "one too many"})).json()
        assert out["outcome"] == "AGENT_BUDGET_EXCEEDED", out
        # rejecting one refunds the slot
        await c.post(f"/api/v1/agent/approvals/{ids[0]}/decision",
                     json={"decision": "rejected"}, headers=_hdr(PLANNER))
        out = (await c.post("/api/v1/agent/sessions/1/tools/act_release_production_order", json={
            "parameters": {}, "target_id": "PO-1002", "rationale": "fits again"})).json()
        assert out["outcome"] == "pending_approval", out


# ----------------------------------------------------------------- M3: auto


AUTO_PLUGIN = PLUGIN.replace(
    "allow: [describe_ontology, search_production_order, act_release_production_order]",
    "allow: [describe_ontology, search_production_order, act_release_production_order, act_create_production_order]",
).replace(
    "approval: { writes: confirm }",
    "approval: { writes: auto, auto_actions: [act_release_production_order] }",
).replace("budget: { steps: 25, wall_ms: 60000, writes_per_session: 3 }",
          "budget: { steps: 25, wall_ms: 60000, writes_per_session: 1 }")

# a shop-floor agent holds the operator role, which Cedar grants NO release
# permit: its auto write must hit the policy gate, not the approval queue
OPERATOR_PLUGIN = PLUGIN.replace(
    "name: planning-copilot", "name: floor-agent",
).replace(
    'id: "agent:planning-copilot"', 'id: "agent:floor-agent"',
).replace(
    "display: Planning copilot", "display: Shop floor agent",
).replace(
    "Role: [planner]", "Role: [operator]",
).replace(
    "approval: { writes: confirm }",
    "approval: { writes: auto, auto_actions: [act_release_production_order] }",
)


@pytest_asyncio.fixture()
async def auto_client(golden_pkg_path, tmp_path):
    root = tmp_path / "pkg"
    shutil.copytree(golden_pkg_path, root)
    (root / "agents").mkdir(exist_ok=True)
    # the package ships its own plugins; these tests exercise one injected
    # plugin in isolation, so start the copy from an empty agents/ dir
    for f in (root / "agents").glob("*.yaml"):
        f.unlink()
    (root / "agents" / "copilot.yaml").write_text(AUTO_PLUGIN, encoding="utf-8")
    (root / "agents" / "floor-agent.yaml").write_text(OPERATOR_PLUGIN, encoding="utf-8")
    src = tmp_path / "erp.db"
    seed_from_package(golden_pkg_path, src, force=True)
    sc = ServiceContext(_sc_settings(tmp_path, src), str(root))
    await sc.initialize()
    for t in sc.compiled.objects:
        await sc.sync(t)
    app = build_app(sc)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, sc


class TestAutoApproval:
    async def test_whitelisted_action_executes_immediately(self, auto_client):
        """M3: auto_actions executes the write in one step -- the agent outcome
        is the revision, no human queue involved."""
        c, _ = auto_client
        await c.post("/api/v1/agent/sessions", json={"plugin": "planning-copilot", "task": "auto"})
        out = (await c.post("/api/v1/agent/sessions/1/tools/act_release_production_order", json={
            "parameters": {}, "target_id": "PO-1002"})).json()
        assert out["outcome"] == "executed", out
        assert out.get("revision_id")
        po = (await c.get("/api/v1/objects/production-order/PO-1002", headers=_hdr(PLANNER))).json()
        assert po["status"] == "RELEASED"
        # no approval row was created
        approvals = (await c.get("/api/v1/agent/approvals")).json()["approvals"]
        assert approvals == []

    async def test_non_whitelisted_write_is_refused(self, auto_client):
        """auto gate is a whitelist: an act_* tool that the plugin may CALL but
        that is not in auto_actions must not slip through as auto (fail closed)."""
        c, _ = auto_client
        await c.post("/api/v1/agent/sessions", json={"plugin": "planning-copilot", "task": "x"})
        out = (await c.post("/api/v1/agent/sessions/1/tools/act_create_production_order", json={
            "parameters": {"product_id": "P-100", "qty": 5}})).json()
        assert out["outcome"] == "POLICY_DENIED", out
        assert "auto_actions" in out.get("error", "")

    async def test_row_level_policy_applies_to_agents_too(self, auto_client):
        """The plugin principal carries its Cedar roles; release-production-order
        is permitted to planners only, so an operator-principaled agent hitting
        the same action is refused by policy -- the agent never escapes the
        role model its identity declares."""
        c, _ = auto_client
        await c.post("/api/v1/agent/sessions", json={"plugin": "floor-agent", "task": "x"})
        out = (await c.post("/api/v1/agent/sessions/1/tools/act_release_production_order", json={
            "parameters": {}, "target_id": "PO-1002"})).json()
        assert out["outcome"] == "POLICY_DENIED", out
        # and the order is untouched
        po = (await c.get("/api/v1/objects/production-order/PO-1002", headers=_hdr(PLANNER))).json()
        assert po["status"] == "PLANNED"

    async def test_writes_budget_counts_auto_executions(self, auto_client):
        """Auto executions consume writes_per_session; the next write hits the
        budget ceiling with a structured outcome."""
        c, _ = auto_client
        await c.post("/api/v1/agent/sessions", json={"plugin": "planning-copilot", "task": "x"})
        out = (await c.post("/api/v1/agent/sessions/1/tools/act_release_production_order", json={
            "parameters": {}, "target_id": "PO-1002"})).json()
        assert out["outcome"] == "executed", out
        sess = (await c.get("/api/v1/agent/sessions/1")).json()
        assert sess["budget"]["writes_used"] == 1
        # budget_writes = 1 -> the next write (a fresh create) is over budget
        out = (await c.post("/api/v1/agent/sessions/1/tools/act_create_production_order", json={
            "parameters": {"product_id": "P-100", "qty": 5}})).json()
        assert out["outcome"] == "AGENT_BUDGET_EXCEEDED", out
