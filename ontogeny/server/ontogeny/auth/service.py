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
# specific language governing permissions and
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
import secrets
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from ..errors import AuthenticationError, ConflictError, DSLValidationError, NotFoundError, StoreError
from .models import SessionRow, UserRow
from .passwords import hash_password, new_token, token_fingerprint, verify_password

log = logging.getLogger("ontogeny.auth")

SESSION_TTL = _dt.timedelta(hours=12)
MIN_PASSWORD = 6


def bootstrap_password_path(settings) -> Path:
    """Choose a persistent location for a generated bootstrap credential."""
    if settings.data_dir:
        directory = Path(settings.data_dir)
    else:
        from sqlalchemy.engine import make_url

        url = make_url(settings.db_dsn)
        if url.drivername.startswith("sqlite") and url.database and url.database != ":memory:":
            directory = Path(url.database).parent
        else:
            directory = Path(".ontogeny")
    return directory.absolute() / "admin-bootstrap-password"


def _write_bootstrap_password(path: Path, password: str) -> None:
    """Create a private file without following or overwriting an existing path."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise StoreError(
            f"bootstrap credential file already exists: {path}; "
            "remove it after securing it or set ONTOGENY_ADMIN_PASSWORD"
        ) from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(password + "\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class AuthService:
    def __init__(self, sc) -> None:
        self.sc = sc

    # ------------------------------------------------------------------ users

    async def _user(self, session, username: str) -> UserRow | None:
        return (await session.execute(select(UserRow).where(UserRow.username == username))).scalar_one_or_none()

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

    async def create_user(
        self,
        *,
        username: str,
        password: str,
        display: str = "",
        roles: list[str] | None = None,
        site: str | None = None,
        markings: list[str] | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        username = (username or "").strip()
        if not username:
            raise DSLValidationError("username is required")
        self._check_password(password)
        async with self.sc.sessionmaker() as session:
            if await self._user(session, username):
                raise DSLValidationError(f"user {username!r} already exists")
            row = UserRow(
                username=username,
                display=display or username,
                password_hash=hash_password(password),
                roles=sorted(set(roles or [])),
                site=site or None,
                markings=sorted(set(markings or [])),
                is_admin=bool(is_admin),
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
            was_active_admin = row.is_admin and row.status == "active"
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
            # demoting or disabling the LAST active administrator locks the
            # deployment out after the next restart; refuse it outright
            is_still_active_admin = row.is_admin and row.status == "active"
            if was_active_admin and not is_still_active_admin:
                other_active_admins = (
                    await session.execute(
                        select(func.count())
                        .select_from(UserRow)
                        .where(
                            UserRow.is_admin.is_(True),
                            UserRow.status == "active",
                            UserRow.id != row.id,
                        )
                    )
                ).scalar_one()
                if other_active_admins == 0:
                    raise ConflictError(
                        f"cannot demote or disable {username!r}: it is the last active administrator",
                        details={"username": username},
                    )
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
            session.add(
                SessionRow(
                    token_hash=token_fingerprint(token),
                    user_id=row.id,
                    expires_at=_dt.datetime.now(_dt.UTC) + SESSION_TTL,
                )
            )
            row.last_login_at = _dt.datetime.now(_dt.UTC)
            await session.commit()
            return token, row.principal()

    async def resolve(self, token: str) -> dict[str, Any] | None:
        """A bearer token -> principal, or None when unknown/expired/disabled."""
        if not token:
            return None
        now = _dt.datetime.now(_dt.UTC)
        async with self.sc.sessionmaker() as session:
            sess = (
                await session.execute(select(SessionRow).where(SessionRow.token_hash == token_fingerprint(token)))
            ).scalar_one_or_none()
            if sess is None:
                return None
            expires = sess.expires_at
            if expires is not None and expires.tzinfo is None:
                expires = expires.replace(tzinfo=_dt.UTC)
            if expires is None or expires < now:
                await session.delete(sess)
                await session.commit()
                return None
            user = (await session.execute(select(UserRow).where(UserRow.id == sess.user_id))).scalar_one_or_none()
            if user is None or user.status != "active":
                return None
            sess.last_seen = now
            await session.commit()
            return user.principal()

    async def logout(self, token: str) -> None:
        if not token:
            return
        async with self.sc.sessionmaker() as session:
            await session.execute(delete(SessionRow).where(SessionRow.token_hash == token_fingerprint(token)))
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
            users = {u.id: u.username for u in (await session.execute(select(UserRow))).scalars().all()}
            return [
                {
                    "token": r.token_hash[:12],
                    "user": users.get(r.user_id, "?"),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                    "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                }
                for r in rows
            ]

    # -------------------------------------------------------------- bootstrap

    async def ensure_admin(self) -> dict[str, Any] | None:
        """Make sure at least one active administrator exists.

        On a fresh database this creates the bootstrap account. The username
        defaults to ``admin``. Unless ``ONTOGENY_ADMIN_PASSWORD`` is set, a
        random password is written to an owner-only credential file.
        """
        async with self.sc.sessionmaker() as session:
            existing = (
                await session.execute(
                    select(func.count())
                    .select_from(UserRow)
                    .where(UserRow.is_admin.is_(True), UserRow.status == "active")
                )
            ).scalar_one()
            if existing:
                return None

        username = os.environ.get("ONTOGENY_ADMIN_USER", "admin")
        # Never silently restore privileges to a disabled or demoted account.
        # A deployment with this inconsistent state needs explicit recovery.
        async with self.sc.sessionmaker() as session:
            row = await self._user(session, username)
            if row is not None:
                raise ConflictError(
                    f"no active administrator exists and bootstrap user {username!r} already exists; "
                    "restore an administrator explicitly or select a new ONTOGENY_ADMIN_USER"
                )
        configured_password = os.environ.get("ONTOGENY_ADMIN_PASSWORD")
        password = configured_password or f"{secrets.randbelow(1_000_000):06d}"
        credential_path = None if configured_password else bootstrap_password_path(self.sc.settings)
        if credential_path is not None:
            _write_bootstrap_password(credential_path, password)
        # Keep the file if account creation fails: an error or cancellation can
        # occur after the database commit, and deleting it could lock the user out.
        user = await self.create_user(
            username=username,
            password=password,
            display="平台管理员",
            roles=["admin"],
            is_admin=True,
        )
        if configured_password:
            log.info("created the bootstrap administrator %r with the configured password", username)
        else:
            log.warning("created bootstrap administrator %r; credential file: %s", username, credential_path)
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
