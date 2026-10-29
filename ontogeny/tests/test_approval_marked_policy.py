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

"""Human approval policy uses real values, not presentation masking."""

import pytest
from sqlalchemy import select
from test_agent_approval import _hdr, _pending_approval
from test_agent_approval import client as _approval_client

from ontogeny.action.models import RevisionRow
from ontogeny.agent.models import AgentApprovalRow
from ontogeny.core.models import PropertyDef
from ontogeny.policy.engine import PolicyEngine
from ontogeny.stores.repo import utcnow

approval_client = _approval_client
REVIEWER = {"id": "human-reviewer", "Role": ["reviewer"]}
POLICY = """
permit(principal in Role::"planner", action == Action::"release-production-order", resource);
permit(principal in Role::"reviewer", action == Action::"release-production-order", resource)
when { resource.priority != "HIGH" };
"""


def _policy(sc, text=POLICY):
    sc.compiled.objects["production-order"].spec.properties["priority"].marking = "internal"
    sc.compiled.cedar_texts["production"] = text
    sc.policy = PolicyEngine(sc.compiled)
    sc.runtime.policy = sc.policy


@pytest.mark.parametrize("decision", ["approved", "rejected"])
async def test_masked_restricted_value_cannot_authorize_approval_or_rejection(approval_client, decision):
    client, sc = approval_client
    async with sc.sessionmaker() as db:
        await sc.repo.action_update(db, "production-order", "PO-1002", {"priority": "HIGH"}, utcnow())
        await db.commit()
    _policy(sc)
    pending = await _pending_approval(client)
    visible = await client.get("/api/v1/objects/production-order/PO-1002", headers=_hdr(REVIEWER))
    assert visible.json()["priority"] == "__masked__"
    response = await client.post(
        f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
        json={"decision": decision},
        headers=_hdr(REVIEWER),
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "POLICY_DENIED" and "HIGH" not in response.text
    async with sc.sessionmaker() as db:
        approval = await db.get(AgentApprovalRow, pending["approval_id"])
        order = await sc.repo.get(db, "production-order", "PO-1002")
        assert approval.status == "pending" and approval.decided_by is None
        assert order["status"] == "PLANNED" and order["priority"] == "HIGH"


async def test_allowed_reviewer_does_not_need_marking_and_plugin_is_execution_identity(approval_client):
    client, sc = approval_client
    _policy(sc)
    pending = await _pending_approval(client)
    visible = await client.get("/api/v1/objects/production-order/PO-1002", headers=_hdr(REVIEWER))
    assert visible.json()["priority"] == "__masked__"
    response = await client.post(
        f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
        json={"decision": "approved"},
        headers=_hdr(REVIEWER),
    )
    assert response.status_code == 200 and response.json()["status"] == "executed"
    assert response.json()["decided_by"] == REVIEWER["id"]
    async with sc.sessionmaker() as db:
        revision = await db.get(RevisionRow, response.json()["revision_id"])
        assert revision.principal == "agent:planning-copilot"
    visible = await client.get("/api/v1/objects/production-order/PO-1002", headers=_hdr(REVIEWER))
    assert visible.json()["priority"] == "__masked__" and visible.json()["status"] == "RELEASED"


async def test_human_permit_does_not_replace_plugin_execution_policy(approval_client):
    client, sc = approval_client
    pending = await _pending_approval(client)
    _policy(
        sc,
        'permit(principal in Role::"reviewer", action == Action::"release-production-order", resource) '
        'when { resource.priority != "HIGH" };',
    )
    response = await client.post(
        f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
        json={"decision": "approved"},
        headers=_hdr(REVIEWER),
    )
    assert response.status_code == 200 and response.json()["status"] == "failed"
    async with sc.sessionmaker() as db:
        order = await sc.repo.get(db, "production-order", "PO-1002")
        approval = (
            await db.execute(select(AgentApprovalRow).where(AgentApprovalRow.id == pending["approval_id"]))
        ).scalar_one()
        assert order["status"] == "PLANNED" and approval.status == "failed"


@pytest.mark.parametrize("decision", ["approved", "rejected"])
async def test_marked_expression_derived_field_uses_real_value_for_approval(approval_client, decision):
    client, sc = approval_client
    async with sc.sessionmaker() as db:
        await sc.repo.action_update(db, "production-order", "PO-1002", {"priority": "HIGH"}, utcnow())
        await db.commit()
    sc.compiled.objects["production-order"].spec.properties["priority_copy"] = PropertyDef(
        type="string", marking="internal", derived="target.priority"
    )
    _policy(sc, POLICY.replace("resource.priority !=", "resource.priority_copy !="))
    pending = await _pending_approval(client)
    visible = await client.get("/api/v1/objects/production-order/PO-1002", headers=_hdr(REVIEWER))
    assert visible.json()["priority_copy"] == "__masked__"
    response = await client.post(
        f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
        json={"decision": decision},
        headers=_hdr(REVIEWER),
    )
    assert response.status_code == 403, response.text
    async with sc.sessionmaker() as db:
        approval = await db.get(AgentApprovalRow, pending["approval_id"])
        assert approval.status == "pending" and approval.decided_by is None


async def test_unmasked_expression_derived_value_can_authorize_reviewer(approval_client):
    client, sc = approval_client
    sc.compiled.objects["production-order"].spec.properties["priority_copy"] = PropertyDef(
        type="string", marking="internal", derived="target.priority"
    )
    _policy(sc, POLICY.replace("resource.priority !=", "resource.priority_copy !="))
    pending = await _pending_approval(client)
    visible = await client.get("/api/v1/objects/production-order/PO-1002", headers=_hdr(REVIEWER))
    assert visible.json()["priority_copy"] == "__masked__"
    response = await client.post(
        f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
        json={"decision": "approved"},
        headers=_hdr(REVIEWER),
    )
    assert response.status_code == 200 and response.json()["status"] == "executed"
