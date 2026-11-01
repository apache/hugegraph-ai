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

"""Persistence for the document ingestion plane.

Five tables, all platform-owned (``ontogeny_*``): the corpus manifest, one row
per extraction run, one packet per chunk (the raw extracted subgraph, replayable),
one assertion per extracted field (provenance + deletion semantics) and the
review queue. Object/link rows stay in the ordinary compiled tables -- an
accepted extraction is indistinguishable from any other row downstream.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..stores.repo import utcnow


class DocumentRow(Base):
    __tablename__ = "ontogeny_document"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256(bytes)
    store: Mapped[str] = mapped_column(String(200), index=True)
    selector: Mapped[str | None] = mapped_column(Text, nullable=True)
    path: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | removed
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    extracted_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExtractRunRow(Base):
    __tablename__ = "ontogeny_extract_run"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    store: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running")  # running|ok|error|preview
    schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    n_documents: Mapped[int] = mapped_column(Integer, default=0)
    n_chunks: Mapped[int] = mapped_column(Integer, default=0)
    n_objects: Mapped[int] = mapped_column(Integer, default=0)
    n_inserted: Mapped[int] = mapped_column(Integer, default=0)
    n_updated: Mapped[int] = mapped_column(Integer, default=0)
    n_noop: Mapped[int] = mapped_column(Integer, default=0)
    n_links: Mapped[int] = mapped_column(Integer, default=0)
    n_candidates: Mapped[int] = mapped_column(Integer, default=0)
    n_quarantined: Mapped[int] = mapped_column(Integer, default=0)
    n_archived: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExtractPacketRow(Base):
    __tablename__ = "ontogeny_extract_packet"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    doc_id: Mapped[str] = mapped_column(String(64), index=True)
    doc_hash: Mapped[str] = mapped_column(String(64), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    chunk_hash: Mapped[str] = mapped_column(String(64), index=True)
    schema_hash: Mapped[str] = mapped_column(String(64), index=True)
    prompt_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    graph: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    issues: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="final")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractAssertionRow(Base):
    """One extracted fact. Object fields and link assertions share the table:
    ``kind`` tells them apart, so a corpus removal can retract exactly what the
    document asserted and nothing else."""

    __tablename__ = "ontogeny_extract_assertion"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    doc_id: Mapped[str] = mapped_column(String(64), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16), default="object")  # object | link
    object_type: Mapped[str] = mapped_column(String(200), index=True)
    object_id: Mapped[str] = mapped_column(String(500), index=True)
    prop: Mapped[str] = mapped_column(String(200), default="")
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_object: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractOriginRow(Base):
    """Permanent record that an object was created by corpus extraction.

    Assertion rows are deleted when a document is removed, so they cannot
    answer "was this row ours?" at archive time. This table is the durable
    answer: an object that existed before any document is never archived by a
    corpus change, even if the only document that mentioned it is gone.
    """

    __tablename__ = "ontogeny_extract_origin"

    object_type: Mapped[str] = mapped_column(String(200), primary_key=True)
    object_id: Mapped[str] = mapped_column(String(500), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractCandidateRow(Base):
    __tablename__ = "ontogeny_extract_candidate"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    doc_id: Mapped[str] = mapped_column(String(64), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16), default="object")  # object | link
    object_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    link: Mapped[str | None] = mapped_column(String(200), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(String(64), default="REVIEW")
    #: content signature of the proposal, so a rerun refreshes one pending row
    #: instead of filling the queue with identical entries
    signature: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|accepted|rejected
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractionSkillRow(Base):
    """A reusable extraction skill (prompt addendum + examples).

    The built-in generic skill lives in code; this table only holds user-created
    skills. A task always stores its own immutable snapshot, so editing a skill
    never changes a task that already ran.
    """

    __tablename__ = "ontogeny_extract_skill"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    display: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    examples: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentTaskRow(Base):
    """One document, one scope, one skill snapshot, one review/confirm lifecycle."""

    __tablename__ = "ontogeny_extract_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store: Mapped[str] = mapped_column(String(200), index=True)
    doc_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skill: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    skill_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_attempt_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_attempt_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confirmed_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    graph_sync_status: Mapped[str] = mapped_column(String(24), default="not_applied")
    confirm_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DocumentAttemptRow(Base):
    """One agent invocation for a task; raw output is immutable, edits live in
    reviewed_graph and the edit log."""

    __tablename__ = "ontogeny_extract_attempt"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="running")
    agent_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_graph: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reviewed_graph: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    chunks: Mapped[list[Any]] = mapped_column(JSON, default=list)
    issues: Mapped[list[Any]] = mapped_column(JSON, default=list)
    validation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentEditRow(Base):
    """Audit trail for human adjustments to an attempt's reviewed graph."""

    __tablename__ = "ontogeny_extract_edit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(Integer, index=True)
    actor: Mapped[str] = mapped_column(String(200), default="")
    op: Mapped[str] = mapped_column(String(40), default="replace_graph")
    path: Mapped[str] = mapped_column(Text, default="")
    before: Mapped[Any] = mapped_column(JSON, nullable=True)
    after: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
