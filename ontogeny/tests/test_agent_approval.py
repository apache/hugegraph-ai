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

"""M2: the human approval gate for agent writes.

Invariants under test:
- a pending write executes NOTHING until a human decides (already covered in
  test_agent.TestBroker.test_write_without_approval_is_pending);
- approving executes the action under the PLUGIN principal, audited to both;
- rejecting refuses the write and frees nothing;
- the approver must THEMSELVES hold the action's Cedar permit (I3: no
  permission laundering through the approval endpoint);
- a decision is single-shot (no double-execution).

The write under test is tapeout: the product role owns it, and its permit
carries a row-level condition (resource.status == "PLANNED"), so the same
gates a human product engineer goes through bind agents too.
"""

from __future__ import annotations

import json
import shutil

import httpx
import pytest
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
  name: product-copilot
  display: Product copilot
spec:
  principal:
    id: "agent:product-copilot"
    Role: [product]
    site: hq
  transport: { kind: http }
  tools:
    allow: [describe_ontology, search_wafer_lot, act_tapeout]
  approval: { writes: confirm }
  budget: { steps: 25, wall_ms: 60000, writes_per_session: 3 }
"""

PRODUCT = {"id": "u-product", "Role": ["product"], "site": "hq"}
# mainline's newer suites import the planner-era name; same principal, chip role
PLANNER = PRODUCT
VISITOR = {"id": "u-visitor", "Role": ["visitor"]}


def _hdr(p):
    return {"X-Ontogeny-Principal": json.dumps(p)}


def _sc_settings(tmp_path, src) -> Settings:
    return Settings(
        dev_auth=True,
        db_dsn=f"sqlite+aiosqlite:///{tmp_path / 'main.db'}",
        env={"ERP_DSN": f"sqlite+aiosqlite:///{src}", "FAB_WEBHOOK": "https://fab-portal.example.test/hook"},
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
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=_hdr({"id": "agent-driver"}),
    ) as c:
        try:
            yield c, sc
        finally:
            await sc.engine.dispose()


async def _pending_approval(c) -> dict:
    session = (
        await c.post("/api/v1/agent/sessions", json={"plugin": "product-copilot", "task": "tapeout TO-A1"})
    ).json()
    out = (
        await c.post(
            "/api/v1/agent/sessions/1/tools/act_tapeout",
            json={
                "parameters": {},
                "target_id": "TO-A1",
                "rationale": "TO-A1 is PLANNED and its mask set is booked; submit it to the fab",
            },
        )
    ).json()
    assert out["outcome"] == "pending_approval", out
    approvals = (await c.get("/api/v1/agent/approvals")).json()["approvals"]
    assert len(approvals) == 1
    return out | {"session": session}


class TestApprovalGate:
    async def test_approve_executes_under_plugin_principal(self, client):
        c, sc = client
        pending = await _pending_approval(c)

        r = await c.post(
            f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
            json={"decision": "approved"},
            headers=_hdr(PRODUCT),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "executed" and body["decided_by"] == "u-product"

        # the object actually moved
        ver = (await c.get("/api/v1/objects/tapeout-version/TO-A1", headers=_hdr(PRODUCT))).json()
        assert ver["status"] == "FAB"
        assert ver["taped_out_at"] is not None

        # audit trail carries BOTH actors: execution to the plugin, decision to the human
        async with sc.sessionmaker() as s:
            from sqlalchemy import select

            from ontogeny.action.models import RevisionRow

            revs = (await s.execute(select(RevisionRow).where(RevisionRow.object_id == "TO-A1"))).scalars().all()
            assert any(r.principal == "agent:product-copilot" for r in revs)
            approval = (
                await s.execute(select(AgentApprovalRow).where(AgentApprovalRow.id == pending["approval_id"]))
            ).scalar_one()
            assert approval.status == "executed" and approval.decided_by == "u-product"
            assert approval.revision_id is not None

    async def test_reject_refuses_and_records(self, client):
        c, _sc = client
        pending = await _pending_approval(c)
        r = await c.post(
            f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
            json={"decision": "rejected"},
            headers=_hdr(PRODUCT),
        )
        assert r.status_code == 200 and r.json()["status"] == "rejected"
        ver = (await c.get("/api/v1/objects/tapeout-version/TO-A1", headers=_hdr(PRODUCT))).json()
        assert ver["status"] == "PLANNED"

    async def test_approver_must_hold_the_permit_themselves(self, client):
        """I3: a principal without the action's Cedar permit cannot approve —
        approvals are not a permission laundering channel."""
        c, _ = client
        pending = await _pending_approval(c)
        r = await c.post(
            f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
            json={"decision": "approved"},
            headers=_hdr(VISITOR),
        )
        assert r.status_code == 403
        # An unauthorized caller cannot consume someone else's pending intent.
        approvals = (await c.get("/api/v1/agent/approvals")).json()["approvals"]
        assert [a["id"] for a in approvals] == [pending["approval_id"]]
        assert approvals[0]["status"] == "pending"

    @pytest.mark.parametrize("decision", ["approved", "rejected"])
    async def test_guessed_approval_id_cannot_change_state_or_budget(self, client, decision):
        c, sc = client
        pending = await _pending_approval(c)
        sid = pending["session"]["id"]
        before = await sc.agents.get_session(sid)
        response = await c.post(
            f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
            json={"decision": decision},
            headers=_hdr(VISITOR),
        )
        assert response.status_code == 403
        after = await sc.agents.get_session(sid)
        assert after["budget"] == before["budget"]
        async with sc.sessionmaker() as db:
            approval = await db.get(AgentApprovalRow, pending["approval_id"])
            assert approval.status == "pending"
            assert approval.decided_by is None
            assert approval.decided_at is None
        # A different user with the action's permit may still decide it.
        authorized = await c.post(
            f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
            json={"decision": decision},
            headers=_hdr(PLANNER),
        )
        assert authorized.status_code == 200
        assert authorized.json()["status"] == ("executed" if decision == "approved" else "rejected")

    async def test_driver_may_reject_but_cannot_approve_without_action_permit(self, client):
        c, sc = client
        pending = await _pending_approval(c)
        decision_url = f"/api/v1/agent/approvals/{pending['approval_id']}/decision"
        # The fixture driver owns the session but does not hold a planner role.
        assert (await c.post(decision_url, json={"decision": "approved"})).status_code == 403
        assert (await c.post(decision_url, json={"decision": "rejected"})).status_code == 200
        sess = await sc.agents.get_session(pending["session"]["id"])
        assert sess["budget"]["writes_used"] == 0

    async def test_decision_is_single_shot(self, client):
        c, _ = client
        pending = await _pending_approval(c)
        r1 = await c.post(
            f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
            json={"decision": "approved"},
            headers=_hdr(PRODUCT),
        )
        assert r1.json()["status"] == "executed"
        r2 = await c.post(
            f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
            json={"decision": "approved"},
            headers=_hdr(PRODUCT),
        )
        assert r2.status_code == 500  # OOError -> already decided

    async def test_writes_budget_gates_pending_intents_and_refunds_rejections(self, client):
        """Pending intents consume writes_per_session up front (no spam);
        a human rejection refunds the slot (the agent is not deadlocked by a
        decision it does not control)."""
        c, _ = client
        await c.post("/api/v1/agent/sessions", json={"plugin": "product-copilot", "task": "x"})
        ids = []
        for i in range(3):  # budget_writes = 3
            out = (
                await c.post(
                    "/api/v1/agent/sessions/1/tools/act_tapeout",
                    json={"parameters": {}, "target_id": "TO-A1", "rationale": f"try {i}"},
                )
            ).json()
            assert out["outcome"] == "pending_approval"
            ids.append(out["approval_id"])
        # 4th intent is refused with a structured budget outcome
        out = (
            await c.post(
                "/api/v1/agent/sessions/1/tools/act_tapeout",
                json={"parameters": {}, "target_id": "TO-A1", "rationale": "one too many"},
            )
        ).json()
        assert out["outcome"] == "AGENT_BUDGET_EXCEEDED", out
        # rejecting one refunds the slot
        await c.post(f"/api/v1/agent/approvals/{ids[0]}/decision", json={"decision": "rejected"}, headers=_hdr(PRODUCT))
        out = (
            await c.post(
                "/api/v1/agent/sessions/1/tools/act_tapeout",
                json={"parameters": {}, "target_id": "TO-A1", "rationale": "fits again"},
            )
        ).json()
        assert out["outcome"] == "pending_approval", out


# ----------------------------------------------------------------- M3: auto


AUTO_PLUGIN = (
    PLUGIN.replace(
        "allow: [describe_ontology, search_wafer_lot, act_tapeout]",
        "allow: [describe_ontology, search_wafer_lot, act_tapeout, act_create_requirement]",
    )
    .replace(
        "approval: { writes: confirm }",
        "approval: { writes: auto, auto_actions: [act_tapeout] }",
    )
    .replace(
        "budget: { steps: 25, wall_ms: 60000, writes_per_session: 3 }",
        "budget: { steps: 25, wall_ms: 60000, writes_per_session: 1 }",
    )
)

# a fab-floor agent holds the fab role, which Cedar grants NO tapeout
# permit: its auto write must hit the policy gate, not the approval queue
FAB_PLUGIN = (
    PLUGIN.replace(
        "name: product-copilot",
        "name: fab-agent",
    )
    .replace(
        'id: "agent:product-copilot"',
        'id: "agent:fab-agent"',
    )
    .replace(
        "display: Product copilot",
        "display: Fab floor agent",
    )
    .replace(
        "Role: [product]",
        "Role: [fab]",
    )
    .replace(
        "approval: { writes: confirm }",
        "approval: { writes: auto, auto_actions: [act_tapeout] }",
    )
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
    (root / "agents" / "fab-agent.yaml").write_text(FAB_PLUGIN, encoding="utf-8")
    src = tmp_path / "erp.db"
    seed_from_package(golden_pkg_path, src, force=True)
    sc = ServiceContext(_sc_settings(tmp_path, src), str(root))
    await sc.initialize()
    for t in sc.compiled.objects:
        await sc.sync(t)
    app = build_app(sc)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=_hdr({"id": "agent-driver"}),
    ) as c:
        try:
            yield c, sc
        finally:
            await sc.engine.dispose()


class TestAutoApproval:
    async def test_whitelisted_action_executes_immediately(self, auto_client):
        """M3: auto_actions executes the write in one step -- the agent outcome
        is the revision, no human queue involved."""
        c, _ = auto_client
        await c.post("/api/v1/agent/sessions", json={"plugin": "product-copilot", "task": "auto"})
        out = (
            await c.post(
                "/api/v1/agent/sessions/1/tools/act_tapeout",
                json={"parameters": {}, "target_id": "TO-A1"},
            )
        ).json()
        assert out["outcome"] == "executed", out
        assert out.get("revision_id")
        ver = (await c.get("/api/v1/objects/tapeout-version/TO-A1", headers=_hdr(PRODUCT))).json()
        assert ver["status"] == "FAB"
        # no approval row was created
        approvals = (await c.get("/api/v1/agent/approvals")).json()["approvals"]
        assert approvals == []

    async def test_non_whitelisted_write_is_refused(self, auto_client):
        """auto gate is a whitelist: an act_* tool that the plugin may CALL but
        that is not in auto_actions must not slip through as auto (fail closed)."""
        c, _ = auto_client
        await c.post("/api/v1/agent/sessions", json={"plugin": "product-copilot", "task": "x"})
        out = (
            await c.post(
                "/api/v1/agent/sessions/1/tools/act_create_requirement",
                json={"parameters": {"title": "IO slew rate control", "priority": "NORMAL"}},
            )
        ).json()
        assert out["outcome"] == "POLICY_DENIED", out
        assert "auto_actions" in out.get("error", "")

    async def test_row_level_policy_applies_to_agents_too(self, auto_client):
        """The plugin principal carries its Cedar roles; tapeout is permitted to
        the product role only, so a fab-principaled agent hitting the same
        action is refused by policy -- the agent never escapes the role model
        its identity declares."""
        c, _ = auto_client
        await c.post("/api/v1/agent/sessions", json={"plugin": "fab-agent", "task": "x"})
        out = (
            await c.post(
                "/api/v1/agent/sessions/1/tools/act_tapeout",
                json={"parameters": {}, "target_id": "TO-A1"},
            )
        ).json()
        assert out["outcome"] == "POLICY_DENIED", out
        # and the version is untouched
        ver = (await c.get("/api/v1/objects/tapeout-version/TO-A1", headers=_hdr(PRODUCT))).json()
        assert ver["status"] == "PLANNED"

    async def test_writes_budget_counts_auto_executions(self, auto_client):
        """Auto executions consume writes_per_session; the next write hits the
        budget ceiling with a structured outcome."""
        c, _ = auto_client
        await c.post("/api/v1/agent/sessions", json={"plugin": "product-copilot", "task": "x"})
        out = (
            await c.post(
                "/api/v1/agent/sessions/1/tools/act_tapeout",
                json={"parameters": {}, "target_id": "TO-A1"},
            )
        ).json()
        assert out["outcome"] == "executed", out
        sess = (await c.get("/api/v1/agent/sessions/1")).json()
        assert sess["budget"]["writes_used"] == 1
        # budget_writes = 1 -> the next write (a fresh create) is over budget
        out = (
            await c.post(
                "/api/v1/agent/sessions/1/tools/act_create_requirement",
                json={"parameters": {"title": "IO slew rate control", "priority": "NORMAL"}},
            )
        ).json()
        assert out["outcome"] == "AGENT_BUDGET_EXCEEDED", out
