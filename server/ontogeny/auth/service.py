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
"""Accounts, sessions and the administrator gate.

One service over two tables (see ``models.py``). It owns:

- **login/logout** — verify a password, mint a bearer token, keep only its
  digest, and resolve a token back into the principal dict the engine consumes;
- **account administration** — create/update/disable/delete users, reset
  passwords, grant or revoke roles;
- **bootstrap** — make sure an administrator exists so a fresh deployment is
  reachable at all.

Session lifetime is deliberately short and sliding-free: an expired session is
re-authenticated, not silently extended.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
from typing import Any

from sqlalchemy import delete, func, select

from ..errors import AuthenticationError, DSLValidationError, NotFoundError
from .models import SessionRow, UserRow
from .passwords import hash_password, new_token, token_fingerprint, verify_password

log = logging.getLogger("ontogeny.auth")

SESSION_TTL = _dt.timedelta(hours=12)
MIN_PASSWORD = 8


class AuthService:
    def __init__(self, sc) -> None:
        self.sc = sc

    # ------------------------------------------------------------------ users

    async def _user(self, session, username: str) -> UserRow | None:
        return (await session.execute(
            select(UserRow).where(UserRow.username == username)
        )).scalar_one_or_none()

    @staticmethod
    def _view(row: UserRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "username": row.username,
            "display": row.display or row.username,
            "roles": list(row.roles or []),
            "site": row.site,
            "markings": list(row.markings or []),
            "status": row.status,
            "is_admin": bool(row.is_admin),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
        }

    async def list_users(self) -> list[dict[str, Any]]:
        async with self.sc.sessionmaker() as session:
            rows = (await session.execute(select(UserRow).order_by(UserRow.username))).scalars().all()
            return [self._view(r) for r in rows]

    async def create_user(self, *, username: str, password: str, display: str = "",
                          roles: list[str] | None = None, site: str | None = None,
                          markings: list[str] | None = None, is_admin: bool = False) -> dict[str, Any]:
        username = (username or "").strip()
        if not username:
            raise DSLValidationError("username is required")
        self._check_password(password)
        async with self.sc.sessionmaker() as session:
            if await self._user(session, username):
                raise DSLValidationError(f"user {username!r} already exists")
            row = UserRow(
                username=username, display=display or username,
                password_hash=hash_password(password),
                roles=sorted(set(roles or [])), site=site or None,
                markings=sorted(set(markings or [])), is_admin=bool(is_admin),
                status="active",
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._view(row)

    async def update_user(self, username: str, patch: dict[str, Any]) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            row = await self._user(session, username)
            if row is None:
                raise NotFoundError(f"user {username!r} not found")
            if "display" in patch and patch["display"] is not None:
                row.display = str(patch["display"])
            if patch.get("roles") is not None:
                row.roles = sorted({str(r) for r in patch["roles"]})
            if "site" in patch:
                row.site = patch["site"] or None
            if patch.get("markings") is not None:
                row.markings = sorted({str(m) for m in patch["markings"]})
            if patch.get("status"):
                if patch["status"] not in ("active", "disabled"):
                    raise DSLValidationError("status must be active or disabled")
                row.status = patch["status"]
            if patch.get("is_admin") is not None:
                row.is_admin = bool(patch["is_admin"])
            if patch.get("password"):
                self._check_password(patch["password"])
                row.password_hash = hash_password(patch["password"])
                # a password change invalidates every existing session for that
                # account: that is the whole point of changing it
                await session.execute(delete(SessionRow).where(SessionRow.user_id == row.id))
            await session.commit()
            await session.refresh(row)
            return self._view(row)

    async def delete_user(self, username: str) -> dict[str, Any]:
        async with self.sc.sessionmaker() as session:
            row = await self._user(session, username)
            if row is None:
                raise NotFoundError(f"user {username!r} not found")
            # Administrator accounts are platform-owned: never deletable, even
            # when another administrator exists. This also protects the
            # bootstrap admin from someone locking themselves out mid-setup.
            if row.is_admin:
                raise DSLValidationError("administrator accounts cannot be deleted (including the last administrator)")
            await session.execute(delete(SessionRow).where(SessionRow.user_id == row.id))
            await session.delete(row)
            await session.commit()
            return {"deleted": username}

    @staticmethod
    def _check_password(password: str) -> None:
        if not password or len(password) < MIN_PASSWORD:
            raise DSLValidationError(f"password must be at least {MIN_PASSWORD} characters")

    # --------------------------------------------------------------- sessions

    async def login(self, username: str, password: str) -> tuple[str, dict[str, Any]]:
        """Verify credentials and mint a session. Returns (token, principal)."""
        async with self.sc.sessionmaker() as session:
            row = await self._user(session, (username or "").strip())
            # same message either way: which half was wrong is not the caller's
            # business, and a disabled account must not be distinguishable
            if row is None or not verify_password(password, row.password_hash):
                raise AuthenticationError("invalid username or password")
            if row.status != "active":
                raise AuthenticationError("this account is disabled")
            token = new_token()
            session.add(SessionRow(
                token_hash=token_fingerprint(token),
                user_id=row.id,
                expires_at=_dt.datetime.now(_dt.timezone.utc) + SESSION_TTL,
            ))
            row.last_login_at = _dt.datetime.now(_dt.timezone.utc)
            await session.commit()
            return token, row.principal()

    async def resolve(self, token: str) -> dict[str, Any] | None:
        """A bearer token -> principal, or None when unknown/expired/disabled."""
        if not token:
            return None
        now = _dt.datetime.now(_dt.timezone.utc)
        async with self.sc.sessionmaker() as session:
            sess = (await session.execute(
                select(SessionRow).where(SessionRow.token_hash == token_fingerprint(token))
            )).scalar_one_or_none()
            if sess is None:
                return None
            expires = sess.expires_at
            if expires is not None and expires.tzinfo is None:
                expires = expires.replace(tzinfo=_dt.timezone.utc)
            if expires is None or expires < now:
                await session.delete(sess)
                await session.commit()
                return None
            user = (await session.execute(
                select(UserRow).where(UserRow.id == sess.user_id)
            )).scalar_one_or_none()
            if user is None or user.status != "active":
                return None
            sess.last_seen = now
            await session.commit()
            return user.principal()

    async def logout(self, token: str) -> None:
        if not token:
            return
        async with self.sc.sessionmaker() as session:
            await session.execute(
                delete(SessionRow).where(SessionRow.token_hash == token_fingerprint(token))
            )
            await session.commit()

    async def list_sessions(self, username: str | None = None) -> list[dict[str, Any]]:
        async with self.sc.sessionmaker() as session:
            stmt = select(SessionRow).order_by(SessionRow.created_at.desc()).limit(200)
            if username:
                user = await self._user(session, username)
                if user is None:
                    return []
                stmt = stmt.where(SessionRow.user_id == user.id)
            rows = (await session.execute(stmt)).scalars().all()
            users = {
                u.id: u.username
                for u in (await session.execute(select(UserRow))).scalars().all()
            }
            return [{
                "token": r.token_hash[:12],
                "user": users.get(r.user_id, "?"),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            } for r in rows]

    # -------------------------------------------------------------- bootstrap

    async def ensure_admin(self) -> dict[str, Any] | None:
        """Make sure at least one active administrator exists.

        On a fresh database this creates the bootstrap account. The username
        defaults to ``admin``; the initial password defaults to the fixed
        bootstrap value ``ontogeny@2026`` unless ``ONTOGENY_ADMIN_PASSWORD`` overrides it.
        """
        async with self.sc.sessionmaker() as session:
            existing = (await session.execute(
                select(func.count()).select_from(UserRow).where(UserRow.is_admin.is_(True))
            )).scalar_one()
            if existing:
                return None

        username = os.environ.get("ONTOGENY_ADMIN_USER", "admin")
        password = os.environ.get("ONTOGENY_ADMIN_PASSWORD") or "ontogeny@2026"
        user = await self.create_user(
            username=username, password=password, display="平台管理员",
            roles=["admin"], is_admin=True,
        )
        log.info(
            "created the bootstrap administrator %r (default password ontogeny@2026; "
            "set ONTOGENY_ADMIN_PASSWORD to override before first start)",
            username,
        )
        return user

    async def user_roles(self) -> list[str]:
        """Every role any account currently carries — one of the three sources
        the role catalogue is built from."""
        async with self.sc.sessionmaker() as session:
            rows = (await session.execute(select(UserRow.roles))).scalars().all()
        out: set[str] = set()
        for roles in rows:
            out.update(roles or [])
        return sorted(out)

    async def users_with_role(self, role: str) -> list[str]:
        async with self.sc.sessionmaker() as session:
            rows = (await session.execute(select(UserRow))).scalars().all()
        return sorted(u.username for u in rows if role in (u.roles or []))
