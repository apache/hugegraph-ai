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

"""Actions apply effects in order and decide event gates at that point."""

import pytest
from sqlalchemy import func, select
from test_agent_approval import PLANNER
from test_agent_approval import client as _approval_client

from ontogeny.action.models import OutboxRow, RevisionRow
from ontogeny.core.models import (
    ArchiveObjectEffect,
    CreateObjectEffect,
    EmitEventEffect,
    ModifyTargetEffect,
    WebhookEffect,
)
from ontogeny.errors import TypeMismatchError

approval_client = _approval_client


async def test_two_target_modifications_create_ordered_versions(approval_client):
    _, sc = approval_client
    action = sc.compiled.actions["release-production-order"]
    action.spec.effects = [
        ModifyTargetEffect(kind="modify-target", set={"status": "RELEASED"}),
        ModifyTargetEffect(kind="modify-target", set={"priority": "HIGH"}),
    ]
    async with sc.sessionmaker() as session:
        before = await sc.repo.get(session, "production-order", "PO-1002")
        revision = await sc.runtime.execute(
            session, action.metadata.name, PLANNER, {}, "PO-1002", expected_revision=before["_rev"]
        )
        await session.commit()
        assert revision.after["status"] == "RELEASED"
        assert revision.after["priority"] == "HIGH"
        history = await sc.repo.history(session, "production-order", "PO-1002")
    assert [row["_rev"] for row in history[-3:]] == [before["_rev"], before["_rev"] + 1, before["_rev"] + 2]
    assert len({row["_valid_from"] for row in history[-3:]}) == 3
    assert all(row["_valid_from"] < row["_valid_to"] for row in history[-3:-1])


async def test_modify_then_foreign_key_link_updates_context_for_next_effect(approval_client):
    _, sc = approval_client
    action = sc.compiled.actions["assign-operation"]
    link = action.spec.effects[0]
    action.spec.effects = [
        ModifyTargetEffect(kind="modify-target", set={"status": "RUNNING"}),
        link,
        ModifyTargetEffect(kind="modify-target", when="target.work_center_id == 'WC-03'", set={"status": "COMPLETED"}),
    ]
    async with sc.sessionmaker() as session:
        before = await sc.repo.get(session, "operation", "OP-2002")
        rev = await sc.runtime.execute(
            session,
            action.metadata.name,
            PLANNER,
            {"work_center_id": "WC-03"},
            "OP-2002",
            expected_revision=before["_rev"],
        )
        await session.commit()
        assert rev.after["work_center_id"] == "WC-03"
        assert rev.after["status"] == "COMPLETED"
        history = await sc.repo.history(session, "operation", "OP-2002")
    assert [row["_rev"] for row in history[-4:]] == list(range(before["_rev"], before["_rev"] + 4))
    assert len({row["_valid_from"] for row in history[-4:]}) == 4


async def test_archive_after_multiple_modifications_closes_the_last_version_in_order(approval_client):
    _, sc = approval_client
    action = sc.compiled.actions["release-production-order"]
    action.spec.effects = [
        ModifyTargetEffect(kind="modify-target", set={"status": "RELEASED"}),
        ModifyTargetEffect(kind="modify-target", set={"priority": "HIGH"}),
        ArchiveObjectEffect(kind="archive-object"),
    ]
    async with sc.sessionmaker() as session:
        await sc.runtime.execute(session, action.metadata.name, PLANNER, {}, "PO-1002")
        await session.commit()
        assert await sc.repo.get(session, "production-order", "PO-1002") is None
        history = await sc.repo.history(session, "production-order", "PO-1002")
    assert all(row["_valid_to"] is not None and row["_valid_from"] < row["_valid_to"] for row in history)


async def test_archive_then_recreate_same_key_in_one_action(approval_client):
    _, sc = approval_client
    action = sc.compiled.actions["release-production-order"]
    action.spec.effects = [
        ArchiveObjectEffect(kind="archive-object"),
        CreateObjectEffect(
            kind="create-object",
            properties={
                "order_id": "target.order_id",
                "product_id": "target.product_id",
                "qty": "target.qty",
                "status": "RELEASED",
            },
        ),
    ]
    async with sc.sessionmaker() as session:
        rev = await sc.runtime.execute(session, action.metadata.name, PLANNER, {}, "PO-1002")
        await session.commit()
        assert rev.after["status"] == "RELEASED"
        history = await sc.repo.history(session, "production-order", "PO-1002")
    assert len(history) == 2
    assert history[0]["_valid_from"] < history[0]["_valid_to"] < history[1]["_valid_from"]
    assert history[1]["_valid_to"] is None


async def test_event_gates_use_state_at_their_position_in_the_action(approval_client):
    _, sc = approval_client
    action = sc.compiled.actions["release-production-order"]
    planned = "target.status == 'PLANNED'"
    released = "target.status == 'RELEASED'"
    action.spec.effects = [
        WebhookEffect(kind="webhook", when=planned, url="https://example.test/accepted"),
        EmitEventEffect(kind="emit-event", when=planned, payload={"case": "accepted"}),
        WebhookEffect(kind="webhook", when=released, url="https://example.test/rejected"),
        EmitEventEffect(kind="emit-event", when=released, payload={"case": "rejected"}),
        ModifyTargetEffect(kind="modify-target", set={"status": "RELEASED"}),
    ]
    async with sc.sessionmaker() as session:
        rev = await sc.runtime.execute(session, action.metadata.name, PLANNER, {}, "PO-1002")
        await session.commit()
        rows = (
            (await session.execute(select(OutboxRow).where(OutboxRow.revision_id == rev.id, OutboxRow.op == "event")))
            .scalars()
            .all()
        )
    assert len(rows) == 2
    assert {row.payload["kind"] for row in rows} == {"webhook", "emit"}
    assert all("rejected" not in str(row.payload) for row in rows)


async def test_failed_later_effect_rolls_back_earlier_effect_and_events(approval_client):
    _, sc = approval_client
    action = sc.compiled.actions["release-production-order"]
    action.spec.effects = [
        EmitEventEffect(kind="emit-event", payload={"case": "must roll back"}),
        ModifyTargetEffect(kind="modify-target", set={"status": "RELEASED"}),
        ModifyTargetEffect(kind="modify-target", set={"qty": "invalid_integer"}),
    ]
    async with sc.sessionmaker() as session:
        before = await sc.repo.get(session, "production-order", "PO-1002")
        history = await sc.repo.history(session, "production-order", "PO-1002")
        audit_count = (await session.execute(select(func.count()).select_from(RevisionRow))).scalar_one()
        outbox_count = (await session.execute(select(func.count()).select_from(OutboxRow))).scalar_one()
    with pytest.raises(TypeMismatchError):
        async with sc.sessionmaker() as session:
            await sc.runtime.execute(session, action.metadata.name, PLANNER, {}, "PO-1002")
            await session.commit()
    async with sc.sessionmaker() as session:
        assert await sc.repo.get(session, "production-order", "PO-1002") == before
        assert await sc.repo.history(session, "production-order", "PO-1002") == history
        assert (await session.execute(select(func.count()).select_from(RevisionRow))).scalar_one() == audit_count
        assert (await session.execute(select(func.count()).select_from(OutboxRow))).scalar_one() == outbox_count
