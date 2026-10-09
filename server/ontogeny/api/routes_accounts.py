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
"""Auth + account administration routes."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ..errors import DSLValidationError
from ..service import ServiceContext
from .deps import SESSION_COOKIE, get_principal, get_sc, require_admin, session_cookie_max_age
from .schemas import LoginBody, RuntimeConfigBody, UserCreateBody, UserUpdateBody


def register(r: APIRouter, sc: ServiceContext) -> None:
    @r.post("/auth/login")
    async def auth_login(body: LoginBody, response: Response,
                         sc: ServiceContext = Depends(get_sc)):
        """Verify credentials and start a session.

        The token goes out as an HttpOnly cookie, so the browser never exposes it
        to script; the same token is also returned in the body for non-browser
        callers (the CLI, a test) that have no cookie jar.
        """
        # AuthenticationError is an OOError, so the app's own handler renders it
        # (401 with the platform's error envelope) -- no bespoke status mapping
        token, principal = await sc.auth.login(body.username, body.password)
        response.set_cookie(
            SESSION_COOKIE, token, httponly=True, samesite="lax", path="/",
            max_age=int(session_cookie_max_age()),
        )
        return {"token": token, "principal": principal}

    @r.post("/auth/logout")
    async def auth_logout(request: Request, response: Response,
                          sc: ServiceContext = Depends(get_sc)):
        await sc.auth.logout(request.cookies.get(SESSION_COOKIE, ""))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @r.get("/auth/me")
    async def auth_me(principal: dict = Depends(get_principal),
                      sc: ServiceContext = Depends(get_sc)):
        """Who am I? The shell asks once on boot; 401 means "show the login page".

        A dev-header principal passes while dev_auth is on: the simulation has to
        be able to open the console, or an acting-as picker could only ever
        decorate requests the browser never makes. ``authenticated`` stays False
        and ``via`` says ``dev-header`` — the shell shows it as a simulation, not
        as an account.
        """
        if not principal.get("authenticated") and principal.get("via") != "dev-header":
            raise HTTPException(status_code=401, detail="not signed in")
        # `dev_auth` lets the shell show the development principal override only
        # where it actually does something
        return {"principal": principal, "dev_auth": bool(sc.settings.dev_auth)}

    @r.get("/auth/sessions")
    async def auth_sessions(username: str | None = None,
                            _: dict = Depends(require_admin),
                            sc: ServiceContext = Depends(get_sc)):
        return {"sessions": await sc.auth.list_sessions(username)}

    # ---- account administration -------------------------------------------

    @r.get("/admin/users")
    async def admin_users(_: dict = Depends(require_admin),
                          sc: ServiceContext = Depends(get_sc)):
        return {"users": await sc.auth.list_users()}

    @r.post("/admin/users")
    async def admin_user_create(body: UserCreateBody, _: dict = Depends(require_admin),
                                sc: ServiceContext = Depends(get_sc)):
        return await sc.auth.create_user(**body.model_dump())

    @r.patch("/admin/users/{username}")
    async def admin_user_update(username: str, body: UserUpdateBody,
                                _: dict = Depends(require_admin),
                                sc: ServiceContext = Depends(get_sc)):
        return await sc.auth.update_user(username, body.model_dump(exclude_unset=True))

    @r.delete("/admin/users/{username}")
    async def admin_user_delete(username: str, _: dict = Depends(require_admin),
                                sc: ServiceContext = Depends(get_sc)):
        return await sc.auth.delete_user(username)

    @r.get("/admin/runtime-config")
    async def admin_runtime_config(_: dict = Depends(require_admin),
                                   sc: ServiceContext = Depends(get_sc)):
        return await sc.runtime_config()

    @r.put("/admin/runtime-config")
    async def admin_runtime_config_save(body: RuntimeConfigBody,
                                        _: dict = Depends(require_admin),
                                        sc: ServiceContext = Depends(get_sc)):
        return await sc.configure_runtime(**body.model_dump(exclude_unset=True))

    def _ensure_published(result) -> None:
        """Turn a rejected publish into a real error.

        ``builder_save`` answers 422 with a JSONResponse (so the Scenario Builder
        can show per-resource errors); a role save that hit that path would
        otherwise report success while writing nothing."""
        if isinstance(result, JSONResponse) and result.status_code >= 400:
            payload = json.loads(bytes(result.body).decode("utf-8"))
            detail = payload.get("errors") or payload
            raise DSLValidationError(f"policy was rejected: {detail}", details={"errors": detail})
