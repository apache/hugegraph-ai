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

"""Revision preconditions cover effects that do not update target fields."""

import pytest
from sqlalchemy import func, select
from test_action import link_env as _link_env

from ontogeny.action.models import OutboxRow, RevisionRow
from ontogeny.core.models import ArchiveObjectEffect
from ontogeny.errors import ConflictError

link_fixture = _link_env  # shared real-database fixture


@pytest.mark.parametrize("effect", ["archive", "set-link"])
async def test_revision_precondition_precedes_all_effects(link_fixture, effect):
    repo, runtime, maker = link_fixture["repo"], link_fixture["runtime"], link_fixture["maker"]
    if effect == "archive":
        runtime.compiled.actions["attach-item"].spec.effects = [ArchiveObjectEffect(kind="archive-object")]

    async with maker() as session:
        target = await repo.get(session, "container", "C-1")
        current = target["_rev"]
        audit_before = (await session.execute(select(func.count()).select_from(RevisionRow))).scalar_one()
        outbox_before = (await session.execute(select(func.count()).select_from(OutboxRow))).scalar_one()
        with pytest.raises(ConflictError) as error:
            await runtime.execute(
                session, "attach-item", {"id": "u"}, {"item_id": "I-2"}, "C-1", expected_revision=current + 1
            )
        assert error.value.details == {"expected": current + 1, "current": current}
        # Even a caller that commits after the error must not persist any effect,
        # audit record, or outbox event from the rejected action.
        await session.commit()

    async with maker() as session:
        assert await repo.get(session, "container", "C-1") == target
        assert await repo.link_members(session, "container-items", src_id="C-1") == []
        assert (await session.execute(select(func.count()).select_from(RevisionRow))).scalar_one() == audit_before
        assert (await session.execute(select(func.count()).select_from(OutboxRow))).scalar_one() == outbox_before
        await runtime.execute(session, "attach-item", {"id": "u"}, {"item_id": "I-2"}, "C-1", expected_revision=current)
        await session.commit()

    async with maker() as session:
        if effect == "archive":
            assert await repo.get(session, "container", "C-1") is None
        else:
            assert await repo.link_members(session, "container-items", src_id="C-1") == [("C-1", "I-2")]
