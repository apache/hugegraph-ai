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

"""Opt-in PostgreSQL fixture for test_agent_atomicity; not loaded by default.

The configured PostgreSQL account must be able to create and drop databases.
Each test gets a fresh database, including in concurrent CI runs.
"""

import os
import uuid

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from ontogeny.config import Settings


@pytest_asyncio.fixture(autouse=True)
async def postgres_agent_database(monkeypatch):
    import test_agent_approval

    url = make_url(os.environ["ONTOGENY_PG_DSN"])
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    name = "ontogeny_agent_test_" + uuid.uuid4().hex
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    database_url = url.set(database=name).render_as_string(hide_password=False)

    def settings(tmp_path, src):
        return Settings(
            dev_auth=True,
            db_dsn=database_url,
            data_dir=str(tmp_path),
            env={"ERP_DSN": f"sqlite+aiosqlite:///{src}", "WMS_WEBHOOK": "https://wms.example.test/hook"},
        )

    monkeypatch.setattr(test_agent_approval, "_sc_settings", settings)
    try:
        yield
    finally:
        async with admin.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            await conn.execute(text(f'DROP DATABASE "{name}"'))
        await admin.dispose()
