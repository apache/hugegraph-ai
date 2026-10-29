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

import asyncio

from sqlalchemy import select

from ontogeny.action import ActionRuntime
from ontogeny.action.models import IdSequenceRow
from ontogeny.core.models import Rule
from ontogeny.stores.repo import utcnow

PLANNER = {"id": "planner", "Role": ["planner"], "site": "plant-north"}
PARAMS = {"product_id": "P-101", "qty": 5, "priority": "NORMAL", "due_date": "2026-12-01"}


async def create(sc, runtime):
    async with sc.sessionmaker() as session:
        revision = await runtime.execute(session, "create-production-order", PLANNER, PARAMS)
        await session.commit()
        return revision.object_id


async def test_id_sequence_survives_runtime_rebuild_and_legacy_rows(client):
    _, sc = client
    async with sc.sessionmaker() as session:
        await sc.repo.action_insert(
            session,
            "production-order",
            {"order_id": "PO-000001", "product_id": "P-101", "qty": 1},
            utcnow(),
        )
        await session.commit()

    first = await create(sc, sc.runtime)
    restarted = ActionRuntime(sc.compiled, sc.repo, sc.policy, sc.settings)
    second = await create(sc, restarted)
    assert (first, second) == ("PO-000002", "PO-000003")


async def test_independent_runtimes_allocate_without_collisions(client):
    _, sc = client
    workers = [ActionRuntime(sc.compiled, sc.repo, sc.policy, sc.settings) for _ in range(4)]
    ids = await asyncio.gather(*(create(sc, runtime) for runtime in workers))
    assert sorted(ids) == [f"PO-{number:06d}" for number in range(1, 5)]


async def test_rollback_does_not_consume_id(client):
    _, sc = client
    async with sc.sessionmaker() as session:
        revision = await sc.runtime.execute(session, "create-production-order", PLANNER, PARAMS)
        assert revision.object_id == "PO-000001"
        await session.rollback()
    assert await create(sc, sc.runtime) == "PO-000001"


async def test_dry_run_does_not_allocate_ids_in_rules(client):
    _, sc = client
    action = sc.compiled.actions["create-production-order"]
    action.spec.rules.append(Rule(expr="newId('RULE') != ''"))
    async with sc.sessionmaker() as session:
        result = await sc.runtime.validate(session, "create-production-order", PLANNER, PARAMS, None)
        assert all(rule["ok"] for rule in result["rules"])
        assert (await session.execute(select(IdSequenceRow))).scalars().all() == []
    assert await create(sc, sc.runtime) == "PO-000001"
