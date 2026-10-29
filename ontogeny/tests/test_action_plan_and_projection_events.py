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

import pytest
from sqlalchemy import func, select
from test_action import link_env as _link_env
from test_agent_approval import PLANNER
from test_agent_approval import client as _approval_client

from ontogeny.action.models import OutboxRow, RevisionRow
from ontogeny.core.models import FunctionExecution, LinkEntry, ParamDef, SetLinkEffect
from ontogeny.errors import DSLValidationError

approval_client = _approval_client
link_fixture = _link_env


@pytest.mark.parametrize(
    ("invalid_effect", "expected_code"),
    [
        ({"kind": "modify-target", "set": {"qty": 1}}, "ACTION-OWNER"),
        ({"kind": "modify-target", "set": {"release_lag_h": 1}}, "ACTION-DERIVED"),
        ({"kind": "modify-target", "set": {"unknown_property": 1}}, "ACTION-PROP"),
        ({"kind": "modify-target", "set": {"status": {"$expr": "target.missing_property"}}}, "EXPR-PATH"),
        ({"kind": "create-object", "properties": {"product_id": "P-101", "qty": 1}}, "ACTION-PK"),
        ({"kind": "set-link", "link": "bom-product", "add": []}, "ACTION-LINK-TARGET"),
        ({"kind": "modify-linked", "link": "bom-product", "set": {}}, "ACTION-LINK-TARGET"),
        ({"kind": "webhook", "url": "bad-url"}, "ACTION-WEBHOOK-URL"),
    ],
)
async def test_function_plan_is_validated_before_any_effect(approval_client, invalid_effect, expected_code):
    _, sc = approval_client
    action = sc.compiled.actions["release-production-order"]
    action.spec.execution = FunctionExecution(kind="function", entry="plan.py:main")

    async def run_plan(*args):
        return [{"kind": "modify-target", "set": {"status": "RELEASED"}}, invalid_effect]

    sc.runtime.function_runner = run_plan
    async with sc.sessionmaker() as session:
        before = await sc.repo.get(session, "production-order", "PO-1002")
        old_revisions = (await session.execute(select(func.count()).select_from(RevisionRow))).scalar_one()
        old_outbox = (await session.execute(select(func.count()).select_from(OutboxRow))).scalar_one()
        with pytest.raises(DSLValidationError) as error:
            await sc.runtime.execute(session, action.metadata.name, PLANNER, {}, "PO-1002")
        assert expected_code in {issue["code"] for issue in error.value.details["issues"]}
        # Even committing a session after the rejection cannot persist the
        # first, otherwise-valid effect or any action audit/outbox row.
        await session.commit()
        assert await sc.repo.get(session, "production-order", "PO-1002") == before
        assert (await session.execute(select(func.count()).select_from(RevisionRow))).scalar_one() == old_revisions
        assert (await session.execute(select(func.count()).select_from(OutboxRow))).scalar_one() == old_outbox


async def test_function_plan_values_are_data_and_valid_effects_still_run(approval_client):
    _, sc = approval_client
    action = sc.compiled.actions["release-production-order"]
    action.spec.execution = FunctionExecution(kind="function", entry="plan.py:main")

    async def run_plan(*args):
        return [{"kind": "modify-target", "set": {"status": "RELEASED"}}]

    sc.runtime.function_runner = run_plan
    async with sc.sessionmaker() as session:
        rev = await sc.runtime.execute(session, action.metadata.name, PLANNER, {}, "PO-1002")
        await session.commit()
        assert rev.after["status"] == "RELEASED"


async def test_join_table_link_add_and_remove_from_target_side(link_fixture):
    repo, runtime, maker = link_fixture["repo"], link_fixture["runtime"], link_fixture["maker"]
    action = runtime.compiled.actions["attach-item"]
    action.spec.target = "item"
    action.spec.parameters = {"container_id": ParamDef(type="string", required=True)}
    entry = LinkEntry.model_validate({"container_id": "parameters.container_id"})
    action.spec.effects = [SetLinkEffect(kind="set-link", link="container-items", add=[entry])]
    async with maker() as session:
        await runtime.execute(session, "attach-item", {"id": "u"}, {"container_id": "C-1"}, "I-2")
        await session.commit()
        assert await repo.link_members(session, "container-items", src_id="C-1") == [("C-1", "I-2")]
    action.spec.effects = [SetLinkEffect(kind="set-link", link="container-items", remove=[entry])]
    async with maker() as session:
        await runtime.execute(session, "attach-item", {"id": "u"}, {"container_id": "C-1"}, "I-2")
        await session.commit()
        assert await repo.link_members(session, "container-items", src_id="C-1") == []


async def test_each_created_object_gets_its_own_outbox_event(approval_client):
    _, sc = approval_client
    action = sc.compiled.actions["create-production-order"]
    action.spec.effects.append(action.spec.effects[0].model_copy(deep=True))
    async with sc.sessionmaker() as session:
        rev = await sc.runtime.execute(
            session,
            action.metadata.name,
            PLANNER,
            {"product_id": "P-101", "qty": 5},
        )
        await session.commit()
        events = (
            (await session.execute(select(OutboxRow).where(OutboxRow.revision_id == rev.id, OutboxRow.op == "upsert")))
            .scalars()
            .all()
        )
        ids = {event.object_id for event in events}
        assert ids == {"PO-000001", "PO-000002"}
        assert rev.object_id == "PO-000002"  # preserve the response contract
        for object_id in ids:
            assert await sc.repo.get(session, "production-order", object_id) is not None
