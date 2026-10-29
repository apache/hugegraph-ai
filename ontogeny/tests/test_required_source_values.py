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

"""Invalid required source values quarantine only that row, preserving good data."""

import sqlite3

import pytest
from sqlalchemy import select
from test_stores import env as env

from ontogeny.stores.sync import QuarantineRow


@pytest.mark.parametrize("mapped_name", [False, True])
async def test_required_null_preserves_previous_object_and_commits_valid_rows(env, mapped_name):
    env["compiled"].objects["work-center"].spec.properties["process"].owner = "source"
    async with env["maker"]() as session:
        await env["sync"].sync(session, "work-center")
        await session.commit()
        original = await env["repo"].get(session, "work-center", "WC-01")
    with sqlite3.connect(env["src"]) as source:
        if mapped_name:
            source.execute("ALTER TABLE work_centers ADD COLUMN source_name TEXT")
            source.execute("UPDATE work_centers SET source_name=name")
            env["compiled"].objects["work-center"].spec.backing.mapping["name"] = "source_name"
        field = "source_name" if mapped_name else "name"
        source.execute(f"UPDATE work_centers SET {field}=NULL WHERE work_center_id='WC-01'")
        source.execute(f"UPDATE work_centers SET {field}='valid change', process=NULL WHERE work_center_id='WC-02'")
    async with env["maker"]() as session:
        result = await env["sync"].sync(session, "work-center")
        await session.commit()
        unchanged = await env["repo"].get(session, "work-center", "WC-01")
        changed = await env["repo"].get(session, "work-center", "WC-02")
        quarantined = (await session.execute(select(QuarantineRow))).scalars().all()
    assert result["quarantined"] == 1 and result["updated"] == 1 and result["archived"] == 0
    assert unchanged == original
    assert changed["name"] == "valid change" and changed["process"] is None
    assert quarantined[0].code == "REQUIRED_PROPERTY"
    assert quarantined[0].source_pk == "WC-01"
    assert "name" in quarantined[0].reason


async def test_unmapped_required_property_is_quarantined_before_insert(env):
    env["compiled"].objects["work-center"].spec.backing.mapping["name"] = "missing_source_column"
    async with env["maker"]() as session:
        result = await env["sync"].sync(session, "work-center")
        await session.commit()
        assert await env["repo"].alive_ids(session, "work-center") == set()
        errors = (await session.execute(select(QuarantineRow))).scalars().all()
    assert result["quarantined"] == 3 and result["inserted"] == 0
    assert all(row.code == "REQUIRED_PROPERTY" for row in errors)
