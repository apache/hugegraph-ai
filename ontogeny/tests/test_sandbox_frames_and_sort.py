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

"""Real subprocess regressions for bounded RPC frames and query ordering."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest
from test_declarative_functions import _fn

from ontogeny.core.models import Capability
from ontogeny.errors import PolicyDeniedError, SandboxError
from ontogeny.functions.sandbox import FunctionSandbox
from ontogeny.stores.repo import utcnow

FRAME_LIMIT = 256 * 1024


@pytest.fixture()
def spawned(monkeypatch):
    processes = []
    create = asyncio.create_subprocess_exec

    async def recording_create(*args, **kwargs):
        process = await create(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", recording_create)
    return processes


def sandbox_for(sc, tmp_path, source, *, allowed=None):
    directory = tmp_path / "functions"
    directory.mkdir(exist_ok=True)
    (directory / "probe.py").write_text(source, encoding="utf-8")
    fn = _fn(runtime="python", entry="probe.py:probe", capabilities=[Capability(**{"read-objects": allowed or []})])
    return FunctionSandbox(replace(sc.compiled, package_root=str(tmp_path)), sc.repo, timeout_s=10), fn


async def test_batch_of_one_hundred_kilobyte_values_crosses_default_readline_limit(client, tmp_path, spawned):
    _, sc = client
    sandbox, fn = sandbox_for(sc, tmp_path, 'def probe(obj):\n    return obj["text"]\n')
    rows = [{"text": "x" * 1000} for _ in range(100)]
    async with sc.sessionmaker() as session:
        result = await sandbox.map_rows(session, fn, rows)
    assert result == ["x" * 1000] * 100
    assert spawned and all(process.returncode is not None for process in spawned)


@pytest.mark.parametrize("delta", [-1, 0, 1])
async def test_result_frame_has_explicit_byte_boundary_and_always_reaps_process(client, tmp_path, spawned, delta):
    _, sc = client
    overhead = len((json.dumps({"type": "result", "value": ""}) + "\n").encode())
    size = FRAME_LIMIT - overhead + delta
    sandbox, fn = sandbox_for(sc, tmp_path, f'def probe():\n    return "x" * {size}\n')
    async with sc.sessionmaker() as session:
        if delta <= 0:
            assert await sandbox.run(session, fn, {}) == "x" * size
        else:
            with pytest.raises(SandboxError, match=r"frame.*limit"):
                await sandbox.run(session, fn, {})
    assert spawned and all(process.returncode is not None for process in spawned)


async def test_large_invocation_input_can_return_a_small_result(client, tmp_path, spawned):
    _, sc = client
    sandbox, fn = sandbox_for(sc, tmp_path, "def probe(value):\n    return len(value)\n")
    async with sc.sessionmaker() as session:
        assert await sandbox.run(session, fn, {"value": "x" * FRAME_LIMIT}) == FRAME_LIMIT
    assert spawned and all(process.returncode is not None for process in spawned)


async def test_oversized_child_rpc_frame_is_rejected_and_reaped(client, tmp_path, spawned):
    _, sc = client
    source = f'def probe():\n    return ontogeny.query("work-center", filter={{"name": "x" * {FRAME_LIMIT}}})\n'
    sandbox, fn = sandbox_for(sc, tmp_path, source, allowed=["work-center"])
    async with sc.sessionmaker() as session:
        with pytest.raises(SandboxError, match=r"frame.*limit"):
            await sandbox.run(session, fn, {})
    assert spawned and all(process.returncode is not None for process in spawned)


async def seed(sc, object_type, rows):
    async with sc.sessionmaker() as session:
        for row in rows:
            await sc.repo.sync_upsert(session, object_type, row, utcnow())
        await session.commit()


async def test_large_query_rpc_reply_supports_more_than_64k(client, tmp_path):
    _, sc = client
    await seed(sc, "work-center", [{"work_center_id": f"WC-{number:03d}", "name": "x" * 1000} for number in range(100)])
    source = 'def probe():\n    return ontogeny.query("work-center", limit=100)\n'
    sandbox, fn = sandbox_for(sc, tmp_path, source, allowed=["work-center"])
    async with sc.sessionmaker() as session:
        values = await sandbox.run(session, fn, {})
    assert len(values) == 100 and all(len(value["name"]) == 1000 for value in values)


async def test_oversized_child_result_after_large_query_reply_is_rejected_and_reaped(client, tmp_path, spawned):
    _, sc = client
    await seed(sc, "work-center", [{"work_center_id": f"WC-{number}", "name": "x" * 100000} for number in range(3)])
    source = 'def probe():\n    return ontogeny.query("work-center")\n'
    sandbox, fn = sandbox_for(sc, tmp_path, source, allowed=["work-center"])
    async with sc.sessionmaker() as session:
        with pytest.raises(SandboxError, match=r"frame.*limit"):
            await sandbox.run(session, fn, {})
    assert spawned and all(process.returncode is not None for process in spawned)


async def test_child_query_sort_applies_before_limit_one(client, tmp_path):
    _, sc = client
    await seed(
        sc,
        "work-center",
        [
            {"work_center_id": "WC-HIGH", "name": "High", "capacity_per_shift": 200},
            {"work_center_id": "WC-LOW", "name": "Low", "capacity_per_shift": 1},
        ],
    )
    source = """def probe():
    return ontogeny.query("work-center", sort=[["capacity_per_shift", "asc"]], limit=1)[0]["work_center_id"]
"""
    sandbox, fn = sandbox_for(sc, tmp_path, source, allowed=["work-center"])
    async with sc.sessionmaker() as session:
        assert await sandbox.run(session, fn, {}) == "WC-LOW"


async def test_forwarded_sort_keeps_repository_marking_guard(client, tmp_path, spawned):
    _, sc = client
    await seed(sc, "material", [{"material_id": "M-1", "name": "Material", "unit_cost": 10}])
    source = """def probe():
    return ontogeny.query("material", sort=[["unit_cost", "asc"]], limit=1)
"""
    sandbox, fn = sandbox_for(sc, tmp_path, source, allowed=["material"])
    async with sc.sessionmaker() as session:
        with pytest.raises(PolicyDeniedError, match="marked property"):
            await sandbox.run(session, fn, {})
    assert spawned and all(process.returncode is not None for process in spawned)


async def test_large_map_input_can_return_one_hundred_small_values(client, tmp_path, spawned):
    _, sc = client
    sandbox, fn = sandbox_for(sc, tmp_path, 'def probe(obj):\n    return len(obj["text"])\n')
    rows = [{"text": "x" * 3000} for _ in range(100)]
    assert len(json.dumps(rows).encode()) > FRAME_LIMIT
    async with sc.sessionmaker() as session:
        assert await sandbox.map_rows(session, fn, rows) == [3000] * 100
    assert spawned and all(process.returncode is not None for process in spawned)


async def test_large_query_reply_can_be_aggregated_to_a_small_result(client, tmp_path, spawned):
    _, sc = client
    await seed(sc, "work-center", [{"work_center_id": f"WC-{number}", "name": "x" * 100000} for number in range(3)])
    source = 'def probe():\n    return sum(len(row["name"]) for row in ontogeny.query("work-center"))\n'
    sandbox, fn = sandbox_for(sc, tmp_path, source, allowed=["work-center"])
    async with sc.sessionmaker() as session:
        assert await sandbox.run(session, fn, {}) == 300000
    assert spawned and all(process.returncode is not None for process in spawned)
