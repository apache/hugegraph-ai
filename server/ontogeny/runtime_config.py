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
"""Persisted runtime knobs the operations console can change without a restart.

Only three third-party endpoints live here for now -- the Ollama gateway and
the HugeGraph endpoint. They are deployment configuration, not ontology, so
they must never be written into a package or a policy file. A single-row table
keeps the demo's SQLite database and Postgres symmetric.
"""
from __future__ import annotations

from sqlalchemy import Integer, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class RuntimeConfigRow(Base):
    __tablename__ = "ontogeny_runtime_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    llm_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Kept under the historical column name for the existing table; the API
    # exposes it as the generic ``storage_url``.
    hugegraph_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Graph-server credentials. A HugeGraph in auth mode refuses anonymous
    # access, and dynamic graph creation on 1.7 *requires* auth mode — so these
    # are what make "the platform creates its own graph" possible at all.
    hugegraph_user: Mapped[str | None] = mapped_column(Text, nullable=True)
    hugegraph_password: Mapped[str | None] = mapped_column(Text, nullable=True)


async def load_runtime_config(session) -> RuntimeConfigRow | None:
    return (await session.execute(
        select(RuntimeConfigRow).where(RuntimeConfigRow.id == 1)
    )).scalar_one_or_none()


async def save_runtime_config(
    session, *,
    llm_provider: str | None,
    llm_base_url: str | None,
    llm_model: str | None,
    llm_api_key: str | None,
    storage_provider: str | None,
    storage_url: str | None,
    storage_user: str | None = None,
    storage_password: str | None = None,
) -> RuntimeConfigRow:
    row = await load_runtime_config(session)
    if row is None:
        row = RuntimeConfigRow(id=1)
        session.add(row)
    row.llm_provider = llm_provider or None
    row.llm_base_url = llm_base_url or None
    row.llm_model = llm_model or None
    row.llm_api_key = llm_api_key or None
    row.storage_provider = storage_provider or None
    row.hugegraph_url = storage_url or None
    row.hugegraph_user = storage_user or None
    row.hugegraph_password = storage_password or None
    return row
