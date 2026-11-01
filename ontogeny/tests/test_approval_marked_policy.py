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
permit(principal in Role::"product", action == Action::"tapeout", resource);
permit(principal in Role::"reviewer", action == Action::"tapeout", resource)
when { resource.project != "X2" };
"""


def _policy(sc, text=POLICY):
    sc.compiled.objects["tapeout-version"].spec.properties["project"].marking = "internal"
    sc.compiled.cedar_texts["lifecycle"] = text
    sc.policy = PolicyEngine(sc.compiled)
    sc.runtime.policy = sc.policy


@pytest.mark.parametrize("decision", ["approved", "rejected"])
async def test_masked_restricted_value_cannot_authorize_approval_or_rejection(approval_client, decision):
    client, sc = approval_client
    async with sc.sessionmaker() as db:
        await sc.repo.action_update(db, "tapeout-version", "TO-A1", {"project": "X2"}, utcnow())
        await db.commit()
    _policy(sc)
    pending = await _pending_approval(client)
    visible = await client.get("/api/v1/objects/tapeout-version/TO-A1", headers=_hdr(REVIEWER))
    assert visible.json()["project"] == "__masked__"
    response = await client.post(
        f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
        json={"decision": decision},
        headers=_hdr(REVIEWER),
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "POLICY_DENIED" and "X2" not in response.text
    async with sc.sessionmaker() as db:
        approval = await db.get(AgentApprovalRow, pending["approval_id"])
        version = await sc.repo.get(db, "tapeout-version", "TO-A1")
        assert approval.status == "pending" and approval.decided_by is None
        assert version["status"] == "PLANNED" and version["project"] == "X2"


async def test_allowed_reviewer_does_not_need_marking_and_plugin_is_execution_identity(approval_client):
    client, sc = approval_client
    _policy(sc)
    pending = await _pending_approval(client)
    visible = await client.get("/api/v1/objects/tapeout-version/TO-A1", headers=_hdr(REVIEWER))
    assert visible.json()["project"] == "__masked__"
    response = await client.post(
        f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
        json={"decision": "approved"},
        headers=_hdr(REVIEWER),
    )
    assert response.status_code == 200 and response.json()["status"] == "executed"
    assert response.json()["decided_by"] == REVIEWER["id"]
    async with sc.sessionmaker() as db:
        revision = await db.get(RevisionRow, response.json()["revision_id"])
        assert revision.principal == "agent:product-copilot"
    visible = await client.get("/api/v1/objects/tapeout-version/TO-A1", headers=_hdr(REVIEWER))
    assert visible.json()["project"] == "__masked__" and visible.json()["status"] == "FAB"


async def test_human_permit_does_not_replace_plugin_execution_policy(approval_client):
    client, sc = approval_client
    pending = await _pending_approval(client)
    _policy(
        sc,
        'permit(principal in Role::"reviewer", action == Action::"tapeout", resource) '
        'when { resource.project != "X2" };',
    )
    response = await client.post(
        f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
        json={"decision": "approved"},
        headers=_hdr(REVIEWER),
    )
    assert response.status_code == 200 and response.json()["status"] == "failed"
    async with sc.sessionmaker() as db:
        version = await sc.repo.get(db, "tapeout-version", "TO-A1")
        approval = (
            await db.execute(select(AgentApprovalRow).where(AgentApprovalRow.id == pending["approval_id"]))
        ).scalar_one()
        assert version["status"] == "PLANNED" and approval.status == "failed"


@pytest.mark.parametrize("decision", ["approved", "rejected"])
async def test_marked_expression_derived_field_uses_real_value_for_approval(approval_client, decision):
    client, sc = approval_client
    async with sc.sessionmaker() as db:
        await sc.repo.action_update(db, "tapeout-version", "TO-A1", {"project": "X2"}, utcnow())
        await db.commit()
    sc.compiled.objects["tapeout-version"].spec.properties["project_copy"] = PropertyDef(
        type="string", marking="internal", derived="target.project"
    )
    _policy(sc, POLICY.replace("resource.project !=", "resource.project_copy !="))
    pending = await _pending_approval(client)
    visible = await client.get("/api/v1/objects/tapeout-version/TO-A1", headers=_hdr(REVIEWER))
    assert visible.json()["project_copy"] == "__masked__"
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
    sc.compiled.objects["tapeout-version"].spec.properties["project_copy"] = PropertyDef(
        type="string", marking="internal", derived="target.project"
    )
    _policy(sc, POLICY.replace("resource.project !=", "resource.project_copy !="))
    pending = await _pending_approval(client)
    visible = await client.get("/api/v1/objects/tapeout-version/TO-A1", headers=_hdr(REVIEWER))
    assert visible.json()["project_copy"] == "__masked__"
    response = await client.post(
        f"/api/v1/agent/approvals/{pending['approval_id']}/decision",
        json={"decision": "approved"},
        headers=_hdr(REVIEWER),
    )
    assert response.status_code == 200 and response.json()["status"] == "executed"
