# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""HTTP Bearer authentication middleware and Actor context injection."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from hugegraph_mcp.runtime import (
    VerifiedClaims,
    actor_from_claims,
    reset_current_actor,
    reset_current_runtime,
    set_current_actor,
    set_current_runtime,
)

if TYPE_CHECKING:
    from hugegraph_mcp.runtime import RuntimeContainer

PUBLIC_PROBE_PATHS = frozenset({"/healthz", "/readyz"})


@runtime_checkable
class BearerTokenVerifier(Protocol):
    async def verify(self, token: str) -> VerifiedClaims | None:
        """Verify a Bearer token and return trusted claims, or None if invalid."""
        ...


class StaticSecretBearerVerifier:
    """Constant-time shared-secret verifier bound to fixed server-side claims."""

    def __init__(
        self,
        expected_token: str,
        *,
        default_subject: str = "bearer-client",
        tenant: str = "default",
        scopes: frozenset[str] = frozenset({"mcp:read", "mcp:write"}),
    ) -> None:
        self._expected_token = expected_token
        self._claims = VerifiedClaims(
            issuer="static-bearer",
            tenant=tenant,
            subject=default_subject,
            scopes=scopes,
        )

    async def verify(self, token: str) -> VerifiedClaims | None:
        if hmac.compare_digest(token.encode("utf-8"), self._expected_token.encode("utf-8")):
            return self._claims
        return None


class ActorContextMiddleware(BaseHTTPMiddleware):
    """Extract verified Bearer identity on HTTP requests and bind Actor to ContextVar."""

    def __init__(
        self,
        app,
        *,
        require_auth: bool = True,
        verifier: BearerTokenVerifier | None = None,
        runtime_getter: Callable[[], RuntimeContainer | None] | None = None,
    ) -> None:
        super().__init__(app)
        self._require_auth = require_auth
        self._verifier = verifier
        self._runtime_getter = runtime_getter

    async def dispatch(self, request: Request, call_next) -> Response:
        rt_token = None
        if self._runtime_getter is not None:
            rt = self._runtime_getter()
            if rt is not None:
                rt_token = set_current_runtime(rt)

        try:
            if request.url.path in PUBLIC_PROBE_PATHS:
                return await call_next(request)

            auth_header = request.headers.get("authorization", "")
            token: str | None = None
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip() or None

            claims: VerifiedClaims | None = None
            if token is not None and self._verifier is not None:
                claims = await self._verifier.verify(token)

            if self._require_auth and claims is None:
                message = "Missing Bearer token" if token is None else "Invalid or unverifiable Bearer token"
                return JSONResponse(
                    {"error": "unauthorized", "message": message},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )

            actor = actor_from_claims(claims)
            actor_token = set_current_actor(actor)
            try:
                return await call_next(request)
            finally:
                reset_current_actor(actor_token)
        finally:
            if rt_token is not None:
                reset_current_runtime(rt_token)
