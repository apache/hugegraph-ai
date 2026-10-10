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
"""Outbox and revision tables -- the durable core of the kinetic layer.

Both live in ``ontogeny.action.models`` because they are written by the action
runtime AND by the sync engine (sync-driven changes are outbox events too, so
projections stay consistent regardless of who wrote the object).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _bigid() -> BigInteger:
    """BIGINT primary key that still autoincrements on SQLite (INTEGER PK)."""
    return BigInteger().with_variant(Integer(), "sqlite")


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class RevisionRow(Base):
    """Immutable audit record of one action execution (or approval step)."""

    __tablename__ = "ontogeny_revision"

    id: Mapped[int] = mapped_column(_bigid(), primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(200), index=True)
    object_type: Mapped[str] = mapped_column(String(200), index=True)
    object_id: Mapped[str] = mapped_column(String(500), index=True)
    principal: Mapped[str] = mapped_column(String(200))
    params: Mapped[dict[str, Any]] = mapped_column(JSON)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    rules_hit: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    policy_decision: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), default="executed")  # executed | rejected_rule | denied_policy | pending_approval | approved
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), index=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # The partial unique index must exist on BOTH dialects: sqlite_where alone
    # is a SQLite-only argument, so Postgres silently got no constraint at all
    # and a concurrent same-key replay produced two executed revisions.
    __table_args__ = (
        Index(
            "uq_revision_idem", "idempotency_key", unique=True,
            sqlite_where=idempotency_key.is_not(None),
            postgresql_where=idempotency_key.is_not(None),
        ),
    )


class OutboxRow(Base):
    """Transactional-outbox: the ONLY bridge from committed state to the world."""

    __tablename__ = "ontogeny_outbox"

    id: Mapped[int] = mapped_column(_bigid(), primary_key=True, autoincrement=True)
    object_type: Mapped[str] = mapped_column(String(200), index=True)
    object_id: Mapped[str] = mapped_column(String(500))
    op: Mapped[str] = mapped_column(String(32))  # upsert | archive | link | event
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    revision_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    published_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboxConsumerRow(Base):
    """Per-consumer cursor for independent replay (webhook/projection/sse)."""

    __tablename__ = "ontogeny_outbox_cursor"

    consumer: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_id: Mapped[int] = mapped_column(BigInteger, default=0)
    failures: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
