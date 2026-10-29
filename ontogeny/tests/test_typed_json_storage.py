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
import json
import os
import sqlite3
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ontogeny.action.runtime import ActionRuntime
from ontogeny.config import Settings
from ontogeny.core import load_package
from ontogeny.core.models import PropertyDef, SourceRef, SyncCfg
from ontogeny.db import init_schema, make_engine, make_sessionmaker
from ontogeny.engine.service import QueryService
from ontogeny.policy.engine import PolicyEngine
from ontogeny.registry.compiled import compile_package
from ontogeny.stores.repo import ObjectRepository
from ontogeny.stores.sources import SqlSource
from ontogeny.stores.sync import SyncEngine


@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
async def test_typed_nested_json_roundtrips_sync_and_action(golden_pkg_path, tmp_path, dialect):
    dsn = os.environ.get("ONTOGENY_PG_DSN")
    if dialect == "postgres" and not dsn:
        pytest.skip("PostgreSQL integration requires ONTOGENY_PG_DSN")
    schema = f"typed_json_{uuid.uuid4().hex}"
    admin = None
    previous_converter = sqlite3.converters.get("ONTOJSON")
    if dialect == "postgres":
        admin = create_async_engine(dsn)
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(dsn, connect_args={"server_settings": {"search_path": schema}})
        source_engine = engine
    else:
        sqlite3.register_converter("ONTOJSON", lambda raw: json.loads(raw))
        source_path = tmp_path / "source.db"
        dsn = f"sqlite+aiosqlite:///{source_path}"
        source_engine = create_async_engine(dsn, connect_args={"detect_types": sqlite3.PARSE_DECLTYPES})
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'target.db'}")

    compiled = compile_package(load_package(golden_pkg_path))
    obj = compiled.objects["material"].model_copy(deep=True)
    obj.metadata.name = "typed-record"
    obj.spec.properties["dates"] = PropertyDef(type="array(date)")
    obj.spec.properties["meta"] = PropertyDef(
        type="struct{at:timestamp, days:array(date), nested:struct{day:date}, label:string, amount:decimal(8,2)}"
    )
    obj.spec.properties["entries"] = PropertyDef(type="array(struct{at:timestamp, day:date})")
    obj.spec.backing.source = SourceRef(table="typed_source")
    obj.spec.backing.mapping = {}
    obj.spec.backing.sync = SyncCfg(strategy="snapshot")
    action = compiled.actions["receive-material"].model_copy(deep=True)
    action.spec.target = "typed-record"
    template = action.spec.parameters["note"]
    action.spec.parameters = {
        name: template.model_copy(update={"type": prop.type, "required": True})
        for name, prop in obj.spec.properties.items()
        if name in {"dates", "meta", "entries"}
    }
    action.spec.rules = []
    action.spec.effects[0].set = {name: f"parameters.{name}" for name in action.spec.parameters}
    compiled = replace(
        compiled,
        content_hash=uuid.uuid4().hex,
        objects={**compiled.objects, "typed-record": obj},
        actions={**compiled.actions, "receive-material": action},
    )
    repo = ObjectRepository(compiled)
    source = SqlSource(compiled.stores["mes"], dsn)
    source.engine = source_engine
    maker = make_sessionmaker(engine)
    values = {
        "dates": ["2026-01-03", "2026-01-04"],
        "meta": {
            "at": "2026-01-03T12:30:00+00:00",
            "days": ["2026-02-05"],
            "nested": {"day": "2026-03-06"},
            "label": "2026-01-01",
            "amount": 12.5,
        },
        "entries": [{"at": "2026-04-07T08:00:00+00:00", "day": "2026-04-08"}],
    }
    try:
        await init_schema(engine)
        async with maker() as session:
            await repo.ensure(session)
            await session.commit()
        async with source_engine.begin() as connection:
            column_type = "JSON" if dialect == "postgres" else "ONTOJSON"
            await connection.execute(
                text(
                    f"CREATE TABLE typed_source (material_id TEXT PRIMARY KEY, name TEXT, "
                    f"dates {column_type}, meta {column_type}, entries {column_type})"
                )
            )
            bind = (
                "CAST(:dates AS JSON), CAST(:meta AS JSON), CAST(:entries AS JSON)"
                if dialect == "postgres"
                else ":dates, :meta, :entries"
            )
            await connection.execute(
                text(f"INSERT INTO typed_source VALUES ('key', 'original', {bind})"),
                {name: json.dumps(value) for name, value in values.items()},
            )
        sync = SyncEngine(compiled, Settings(), repo, lambda _: source)
        policy = PolicyEngine(compiled)
        query = QueryService(compiled, repo, policy)
        async with maker() as session:
            assert (await sync.sync(session, "typed-record"))["inserted"] == 1
            await session.commit()
        async with maker() as session:
            row = await query.get(session, "typed-record", "key", {"id": "planner", "Role": ["planner"]})
            assert row["dates"] == [dt.date(2026, 1, 3), dt.date(2026, 1, 4)]
            assert row["meta"]["at"] == dt.datetime(2026, 1, 3, 12, 30, tzinfo=dt.UTC)
            assert row["meta"]["nested"]["day"] == dt.date(2026, 3, 6)
            assert row["meta"]["label"] == "2026-01-01" and row["meta"]["amount"] == 12.5
            assert row["entries"][0]["day"] == dt.date(2026, 4, 8)
            changed = {
                "dates": ["2030-01-01"],
                "meta": {
                    "at": "2030-01-02T03:04:05+00:00",
                    "days": ["2030-01-03"],
                    "nested": {"day": "2030-01-04"},
                    "label": "0012",
                    "amount": 42.75,
                },
                "entries": [{"at": "2030-01-05T00:00:00+00:00", "day": "2030-01-06"}],
            }
            await ActionRuntime(compiled, repo, policy, Settings()).execute(
                session, "receive-material", {"id": "planner", "Role": ["planner"]}, changed, "key"
            )
            await session.commit()
        async with maker() as session:
            row = await repo.get(session, "typed-record", "key")
            assert row["dates"] == [dt.date(2030, 1, 1)]
            assert row["meta"]["at"] == dt.datetime(2030, 1, 2, 3, 4, 5, tzinfo=dt.UTC)
            assert row["meta"]["days"] == [dt.date(2030, 1, 3)]
            assert row["meta"]["label"] == "0012" and row["meta"]["amount"] == 42.75
            assert row["entries"][0]["day"] == dt.date(2030, 1, 6)
    finally:
        if source_engine is not engine:
            await source_engine.dispose()
        await engine.dispose()
        if previous_converter is None:
            sqlite3.converters.pop("ONTOJSON", None)
        else:
            sqlite3.converters["ONTOJSON"] = previous_converter
        if admin:
            async with admin.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()
