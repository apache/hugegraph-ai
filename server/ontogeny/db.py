# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Async database infrastructure: engine, session factory, declarative base.

Portable by design: the same code runs on SQLite (tests / demo) and Postgres
(production); Postgres-only affordances (pgvector, LISTEN/NOTIFY) live behind
capability checks in the layers that use them.
"""
from __future__ import annotations


from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for every ontogeny_* table."""


def make_engine(dsn: str, *, echo: bool = False) -> AsyncEngine:
    return create_async_engine(dsn, echo=echo, future=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# Additive columns for the platform's own tables. `create_all` never alters an
# existing table, so a column added to a model would be missing on any database
# that predates it (the demo's .ontogeny-demo/ontogeny.db survives upgrades). Object tables
# already migrate additively in `stores/ddl.py`; this is the same idea for the
# system tables, kept to portable types (TEXT/INTEGER work on SQLite+Postgres).
ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "ontogeny_agent_session": {
        "expires_at": "TEXT",
        "run_count": "INTEGER",
        "driver": "TEXT",
        "run_started_at": "TEXT",
        "tools_json": "TEXT",
    },
    "ontogeny_agent_step": {
        "thought": "TEXT",
        "run_no": "INTEGER",
        "driver": "TEXT",
    },
    "ontogeny_evolve_proposal": {
        # the model's own reasoning, persisted even when it DECLINED the
        # mutation -- the decline rationale is often the most valuable part
        "llm_analysis": "TEXT",
        # human rejection reason (feeds the proposer's memory) / winner id when
        # a sibling candidate from the same signal was promoted instead
        "rejected_reason": "TEXT",
        "superseded_by": "INTEGER",
    },
    "ontogeny_runtime_config": {
        "llm_provider": "TEXT",
        "llm_api_key": "TEXT",
        "storage_provider": "TEXT",
        # HugeGraph credentials, stored exactly like llm_api_key: written by the
        # console and never handed back out. Needed by any deployment whose
        # graph server enforces auth — which is also the only kind of 1.7 server
        # where the platform may create a graph.
        "hugegraph_user": "TEXT",
        "hugegraph_password": "TEXT",
    },
}


async def init_schema(engine: AsyncEngine) -> None:
    """Create all tables declared against Base, then top up new columns."""
    import importlib

    from . import registry  # noqa: F401 -- core metadata tables

    for mod in ("stores", "action", "telemetry", "evolve", "agent.models", "auth.models", "runtime_config"):
        try:
            importlib.import_module(f".{mod}", package="ontogeny")
        except ModuleNotFoundError:
            pass  # layer not implemented yet; its tables register once it exists

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _add_missing_columns(conn)


async def _add_missing_columns(conn) -> None:
    from sqlalchemy import inspect, text

    def missing(sync_conn) -> list[tuple[str, str, str]]:
        insp = inspect(sync_conn)
        out: list[tuple[str, str, str]] = []
        for table, columns in ADDITIVE_COLUMNS.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            out.extend((table, name, ddl) for name, ddl in columns.items() if name not in have)
        return out

    for table, name, ddl in await conn.run_sync(missing):
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


class Tx:
    """Explicit transactional scope helper around AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            await self.session.commit()
        else:
            await self.session.rollback()
