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

"""Exercise sequence allocation with real PostgreSQL row concurrency."""

import asyncio
import os
import uuid

import pytest
from test_agent_governance import _make

from ontogeny.action import ActionRuntime


@pytest.mark.skipif(not os.environ.get("ONTOGENY_PG_DSN"), reason="PostgreSQL integration requires ONTOGENY_PG_DSN")
async def test_concurrent_independent_runtimes_get_distinct_ids(golden_pkg_path, tmp_path):
    sc = await _make(golden_pkg_path, tmp_path, db_dsn=os.environ["ONTOGENY_PG_DSN"])
    try:
        # A unique prefix makes the test repeatable without deleting data from
        # a database the operator supplied for integration testing.
        prefix = f"T{uuid.uuid4().hex}"
        action = sc.compiled.actions["create-production-order"]
        action.spec.effects[0].properties["order_id"] = f"newId('{prefix}')"
        workers = [ActionRuntime(sc.compiled, sc.repo, sc.policy, sc.settings) for _ in range(8)]

        async def create(runtime):
            async with sc.sessionmaker() as session:
                revision = await runtime.execute(
                    session,
                    "create-production-order",
                    {"id": "planner", "Role": ["planner"], "site": "plant-north"},
                    {"product_id": "P-101", "qty": 5},
                )
                await session.commit()
                return revision.object_id

        ids = await asyncio.gather(*(create(runtime) for runtime in workers))
        assert sorted(ids) == [f"{prefix}-{number:06d}" for number in range(1, 9)]
    finally:
        await sc.engine.dispose()
