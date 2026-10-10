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
"""Account & role storage.

Two tables, deliberately narrow:

- ``ontogeny_user``    one account: credentials, the roles it carries, and the
  attributes (site, markings) the Cedar policies read. A user IS a principal —
  login resolves a row into exactly the ``{id, Role, site, markings}`` dict the
  engine already consumes, so nothing downstream learns a new concept.
- ``ontogeny_session`` one logged-in browser: a *hash* of the bearer token (the raw
  token never touches the database), with an expiry and a last-seen stamp.

``is_admin`` is a platform-administration flag, not a business role: it gates
managing accounts and roles, which is not something a Cedar policy should be
able to grant to a business principal by accident. The business roles a user
carries live in ``roles`` and are enforced by the ordinary policy plane.
"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class UserRow(Base):
    __tablename__ = "ontogeny_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(400))
    # business roles, in the same vocabulary the Cedar policies reference
    roles: Mapped[list] = mapped_column(JSON, default=list)
    site: Mapped[str | None] = mapped_column(String(100), nullable=True)
    markings: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def principal(self) -> dict:
        """The engine's principal shape — the only translation in this module."""
        return {
            "id": self.username,
            "Role": list(self.roles or []),
            "roles": list(self.roles or []),
            "site": self.site,
            "markings": list(self.markings or []),
            # UI-only facts: the shell shows who is signed in and whether the
            # account may administer. The engine ignores unknown keys.
            "display": self.display or self.username,
            "is_admin": bool(self.is_admin),
            "authenticated": True,
        }


class SessionRow(Base):
    __tablename__ = "ontogeny_session"
    __table_args__ = (Index("ix_oo_session_user", "user_id"),)

    # sha256 of the bearer token: a leaked database cannot be replayed
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
