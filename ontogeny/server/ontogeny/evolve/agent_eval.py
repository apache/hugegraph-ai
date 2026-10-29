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

"""Private, disposable database and services for one scripted agent eval."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

from sqlalchemy import select

from ..action.runtime import ActionRuntime
from ..agent.broker import AgentBroker
from ..agent.catalog import effective_tools
from ..core.models import JoinTableJoin
from ..db import init_schema, make_engine, make_sessionmaker
from ..engine.service import QueryService
from ..policy.engine import PolicyEngine
from ..stores.ddl import ensure_tables, link_table, object_table
from ..stores.repo import ObjectRepository
from ..telemetry.service import TelemetryService


def require_safe_script(compiled, case):
    """Never execute functions during eval: they can call external services."""
    plugin = compiled.agent_plugins.get(case.plugin)
    if plugin is None:
        raise ValueError(f"unknown plugin {case.plugin!r}")
    tools = effective_tools(compiled, plugin)
    for step in case.script:
        tool = tools.get(str(step.get("tool")))
        if tool is None:  # the broker reports disallowed/unknown tools normally
            continue
        if tool.kind == "call" or (tool.kind == "act" and compiled.actions[tool.target].spec.execution is not None):
            raise ValueError(f"agent eval cannot execute function-backed tool {tool.name!r}")


async def _copy_table(source_session, target_session, source, target):
    source_cols = {c.name: c for c in source.columns}
    target_cols = {c.name: c for c in target.columns}
    if {c.name for c in source.primary_key} != {c.name for c in target.primary_key}:
        raise ValueError(f"incompatible eval snapshot: primary key changed for {target.name}")
    for name, col in target_cols.items():
        previous = source_cols.get(name)
        if previous is None:
            if not col.nullable:
                raise ValueError(f"incompatible eval snapshot: required column {target.name}.{name} is new")
        elif previous.type._type_affinity is not col.type._type_affinity:
            raise ValueError(f"incompatible eval snapshot: type changed for {target.name}.{name}")
    rows = (await source_session.execute(select(source))).mappings()
    batch = []
    for row in rows:
        batch.append({name: row[name] for name in target_cols if name in source_cols})
        if len(batch) == 500:
            await target_session.execute(target.insert(), batch)
            batch.clear()
    if batch:
        await target_session.execute(target.insert(), batch)


@asynccontextmanager
async def isolated_agent_broker(source_session, live_compiled, candidate, case):
    """Copy source history using typed SQL; all broker commits land in SQLite."""
    require_safe_script(candidate, case)
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    try:
        await init_schema(engine)
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: ensure_tables(c, candidate))
        sessions = make_sessionmaker(engine)
        async with sessions() as dest:
            for name, obj in candidate.objects.items():
                if obj.spec.backing is None or name not in live_compiled.objects:
                    continue
                old = live_compiled.objects[name]
                if old.spec.backing is None:
                    raise ValueError(f"incompatible eval snapshot: {name} had no stored table")
                await _copy_table(
                    source_session, dest, object_table(live_compiled, name), object_table(candidate, name)
                )
            for name, link in candidate.links.items():
                if name not in live_compiled.links:
                    continue
                was_join_table = isinstance(live_compiled.links[name].spec.join, JoinTableJoin)
                is_join_table = isinstance(link.spec.join, JoinTableJoin)
                if was_join_table != is_join_table:
                    raise ValueError(f"incompatible eval snapshot: link {name} changed join type")
                if is_join_table:
                    await _copy_table(
                        source_session, dest, link_table(live_compiled, name), link_table(candidate, name)
                    )
            await dest.commit()

        repo = ObjectRepository(candidate)
        policy = PolicyEngine(candidate)
        sc = SimpleNamespace(
            compiled=candidate,
            sessionmaker=sessions,
            query=QueryService(candidate, repo, policy),
            policy=policy,
            runtime=ActionRuntime(candidate, repo, policy, settings=None),
            telemetry=TelemetryService(candidate),
        )
        yield AgentBroker(sc)
    finally:
        await engine.dispose()
