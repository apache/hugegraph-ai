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

import datetime as dt
import os
import uuid

import pytest
from sqlalchemy import text
from test_stores import env as env

from ontogeny.core.models import SourceRef, SyncCfg, WatermarkCfg
from ontogeny.stores.sources import SqlSource
from ontogeny.stores.sync import SyncStateRow


@pytest.mark.skipif(not os.environ.get("ONTOGENY_PG_DSN"), reason="PostgreSQL integration requires ONTOGENY_PG_DSN")
@pytest.mark.parametrize("kind", ["integer", "timestamp", "timestamptz"])
async def test_postgres_repeated_watermark_sync_includes_late_equal_rows(env, kind):
    dsn = os.environ["ONTOGENY_PG_DSN"]
    table = f"watermark_{uuid.uuid4().hex}"
    sql_type = {"integer": "INTEGER", "timestamp": "TIMESTAMP", "timestamptz": "TIMESTAMPTZ"}[kind]
    if kind == "integer":
        first, second, third = 9, 10, 11
    else:
        first = dt.datetime(2026, 10, 30, tzinfo=dt.UTC if kind == "timestamptz" else None)
        second, third = first + dt.timedelta(seconds=1), first + dt.timedelta(seconds=2)

    source = SqlSource(env["compiled"].stores["mes"], dsn)
    engine = await source._eng()
    async with engine.begin() as conn:
        await conn.execute(
            text(f"CREATE TABLE {table} (work_center_id TEXT PRIMARY KEY, name TEXT NOT NULL, mark {sql_type})")
        )
        await conn.execute(text(f"INSERT INTO {table} VALUES ('a', 'First', :wm)"), {"wm": first})

    backing = env["compiled"].objects["work-center"].spec.backing
    backing.source = SourceRef(table=table)
    backing.sync = SyncCfg(strategy="watermark", watermark=WatermarkCfg(column="mark"))
    env["sync"].source_factory = lambda _: source
    try:

        async def sync():
            async with env["maker"]() as s:
                result = await env["sync"].sync(s, "work-center")
                await s.commit()
                return result

        assert (await sync())["inserted"] == 1
        async with engine.begin() as conn:
            await conn.execute(text(f"INSERT INTO {table} VALUES ('b', 'Late equal', :wm)"), {"wm": first})
            await conn.execute(text(f"INSERT INTO {table} VALUES ('c', 'New high', :wm)"), {"wm": second})
        assert (await sync())["inserted"] == 2
        async with env["maker"]() as s:
            state = await s.get(SyncStateRow, {"store": "mes", "object_type": "work-center"})
            assert state.watermark == str(second)
        async with engine.begin() as conn:
            await conn.execute(text(f"INSERT INTO {table} VALUES ('d', 'Late second', :wm)"), {"wm": second})
            await conn.execute(text(f"INSERT INTO {table} VALUES ('e', 'Next high', :wm)"), {"wm": third})
        assert (await sync())["inserted"] == 2
        async with env["maker"]() as s:
            assert await env["repo"].alive_ids(s, "work-center") == {"a", "b", "c", "d", "e"}
            state = await s.get(SyncStateRow, {"store": "mes", "object_type": "work-center"})
            assert state.watermark == str(third)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE {table}"))
        await source.dispose()


@pytest.mark.skipif(not os.environ.get("ONTOGENY_PG_DSN"), reason="PostgreSQL integration requires ONTOGENY_PG_DSN")
async def test_postgres_watermark_stream_keeps_one_snapshot(env):
    dsn = os.environ["ONTOGENY_PG_DSN"]
    table = f"watermark_{uuid.uuid4().hex}"
    source = SqlSource(env["compiled"].stores["mes"], dsn)
    engine = await source._eng()
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, mark INTEGER NOT NULL)"))
        await conn.execute(text(f"INSERT INTO {table} VALUES (1, 9), (2, 9), (3, 9)"))
    try:
        seen = []
        async for row in source.fetch(SourceRef(table=table), watermark_col="mark", after="9", batch=1):
            seen.append(row["id"])
            if len(seen) == 1:
                async with engine.begin() as conn:
                    await conn.execute(text(f"INSERT INTO {table} VALUES (4, 9)"))
        assert seen == [1, 2, 3]
        assert [
            r["id"] async for r in source.fetch(SourceRef(table=table), watermark_col="mark", after="9", batch=1)
        ] == [1, 2, 3, 4]
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE {table}"))
        await source.dispose()
