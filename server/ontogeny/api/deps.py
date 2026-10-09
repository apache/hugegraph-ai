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
"""Shared FastAPI dependencies and identity resolution (cookie > bearer > dev
header). Extracted from app.py so every route module shares ONE definition."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Depends, Request

from ..service import ServiceContext

UI_DIR_ENV = "ONTOGENY_UI_DIR"
DEFAULT_UI_DIR = Path(__file__).resolve().parents[3] / "web" / "dist"  # <repo>/web/dist


def resolve_ui_dir(explicit: str | Path | None = None) -> Path | None:
    """Where the built SPA lives, or None when the API runs UI-less."""
    candidate = Path(explicit) if explicit else Path(os.environ.get(UI_DIR_ENV, DEFAULT_UI_DIR))
    return candidate if (candidate / "index.html").is_file() else None


def get_sc(request: Request) -> ServiceContext:
    return request.app.state.sc


#: Cookie carrying the session token. HttpOnly + SameSite=Lax: the browser
#: never hands the token to script, and a cross-site POST cannot ride it.
SESSION_COOKIE = "ontogeny_session"


def session_cookie_max_age() -> float:
    """Cookie lifetime, kept in step with the server-side session TTL so the
    browser drops a cookie the server would refuse anyway."""
    from ..auth import SESSION_TTL
    return SESSION_TTL.total_seconds()


async def get_principal(request: Request) -> dict:
    """Resolve the caller: session cookie, then Bearer token, then the dev header.

    A logged-in account IS a principal -- ``AuthService`` turns the row into the
    same ``{id, Role, site, markings}`` dict the engine has always consumed, so
    nothing downstream learns a new concept. Two programmatic paths share that
    shape: the ``Authorization: Bearer`` token that ``/auth/login`` mints (so CI
    can skip the cookie jar), and the ``X-Ontogeny-Principal`` header as an explicitly
    opt-in development/CI path (``ONTOGENY_DEV_AUTH=1``; off by default) where tests drive
    the API without any account at all. Turn ``dev_auth`` off in production and
    the only ways in are an account cookie or a bearer token.

    Every resolution is tagged ``via`` so the UI can say *which* identity won:
    the Access page's identity tab turns an otherwise invisible precedence into
    a visible fact.

    An unauthenticated caller is still ``anonymous`` rather than a 401: the
    public read surfaces (meta, the graph explorer, the dashboard) are meant to
    render for a visitor, and every *write* is already decided by Cedar, which
    denies an anonymous principal by default.
    """
    sc: ServiceContext | None = getattr(request.app.state, "sc", None)
    token = request.cookies.get(SESSION_COOKIE)
    if token and sc is not None and getattr(sc, "auth", None) is not None:
        principal = await sc.auth.resolve(token)
        if principal is not None:
            principal["via"] = "session"
            return principal

    # Below the cookie on purpose: a browser that also carries a client token
    # must keep its session, not silently switch to whatever the token names.
    if sc is not None and getattr(sc, "auth", None) is not None:
        authz = request.headers.get("Authorization", "")
        if authz.startswith("Bearer "):
            principal = await sc.auth.resolve(authz[len("Bearer "):].strip())
            if principal is not None:
                principal["via"] = "bearer"
                return principal

    if sc is not None and getattr(sc.settings, "dev_auth", True):
        raw = request.headers.get("X-Ontogeny-Principal")
        if raw:
            try:
                p = json.loads(raw)
                if isinstance(p, dict) and p.get("id"):
                    p.setdefault("authenticated", False)
                    p["via"] = "dev-header"
                    return p
            except json.JSONDecodeError:
                pass
    return {"id": "anonymous", "Role": [], "authenticated": False, "is_admin": False,
            "via": "anonymous"}


async def require_admin(principal: dict = Depends(get_principal)) -> dict:
    """The administrator gate for account/role administration.

    A platform-administration flag, deliberately NOT a Cedar role: managing who
    exists and what roles they carry must not be something a business policy can
    grant. Business authorization stays in Cedar, untouched by this."""
    if not principal.get("is_admin"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="administrator account required")
    return principal


async def require_authenticated(principal: dict = Depends(get_principal)) -> dict:
    """The floor for surfaces that are not public reads: the caller must be a
    real session/bearer principal, or an explicit dev-header simulation
    (dev_auth). The anonymous visitor the read surfaces allow must not reach
    audit trails, agent session listings, event streams or the LLM."""
    if principal.get("via") == "anonymous":
        from fastapi import HTTPException
        raise HTTPException(
            status_code=401,
            detail="authentication required (sign in, or send the bearer token from /auth/login)")
    return principal
