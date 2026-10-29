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

"""Real PostgreSQL transactions cannot concurrently remove every admin."""

import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ontogeny.auth.models import SessionRow, UserRow
from ontogeny.auth.service import AuthService
from ontogeny.db import make_sessionmaker
from ontogeny.errors import ConflictError

pytestmark = pytest.mark.skipif(
    not os.environ.get("ONTOGENY_PG_DSN"), reason="PostgreSQL integration requires ONTOGENY_PG_DSN"
)


@pytest_asyncio.fixture()
async def pg_auth():
    url = os.environ["ONTOGENY_PG_DSN"]
    schema = "auth_test_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as conn:
            await conn.run_sync(UserRow.__table__.create)
            await conn.run_sync(SessionRow.__table__.create)
        auth = AuthService(SimpleNamespace(sessionmaker=make_sessionmaker(engine)))
        async with auth.sc.sessionmaker() as session:
            session.add_all(
                [
                    UserRow(username="admin-a", password_hash="unused", roles=[], is_admin=True, status="active"),
                    UserRow(username="admin-b", password_hash="unused", roles=[], is_admin=True, status="active"),
                    UserRow(username="member", password_hash="unused", roles=[], is_admin=False, status="active"),
                ]
            )
            await session.commit()
        yield auth
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest.mark.parametrize(
    "patches",
    [
        ({"is_admin": False}, {"is_admin": False}),
        ({"status": "disabled"}, {"status": "disabled"}),
        ({"is_admin": False}, {"status": "disabled"}),
    ],
)
async def test_concurrent_admin_removal_preserves_last_admin(pg_auth, monkeypatch, patches):
    execute = AsyncSession.execute
    sessions = set()

    async def expose_overlap(session, statement, *args, **kwargs):
        result = await execute(session, statement, *args, **kwargs)
        sql = str(statement).lower()
        if "count(" in sql and "ontogeny_user" in sql:
            sessions.add(id(session))
            # Permit the competing transaction to reach its real count query.
            # With correct database serialization it cannot proceed until commit.
            await asyncio.sleep(0.2)
        return result

    monkeypatch.setattr(AsyncSession, "execute", expose_overlap)
    outcomes = await asyncio.gather(
        pg_auth.update_user("admin-a", patches[0]),
        pg_auth.update_user("admin-b", patches[1]),
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in outcomes) == 1, outcomes
    assert sum(isinstance(r, ConflictError) for r in outcomes) == 1, outcomes
    assert len(sessions) == 2
    async with pg_auth.sc.sessionmaker() as session:
        admins = (
            await session.scalars(select(UserRow).where(UserRow.is_admin.is_(True), UserRow.status == "active"))
        ).all()
        assert len(admins) == 1
    user = await pg_auth.update_user("member", {"display": "Updated", "roles": ["operator"]})
    assert user["display"] == "Updated" and user["roles"] == ["operator"]
