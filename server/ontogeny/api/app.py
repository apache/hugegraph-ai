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
"""HTTP shell: FastAPI app over ServiceContext. One governance path.

This module only ASSEMBLES the app: identity deps, request schemas and the
route groups live in their own modules (routes_<domain>.py), and the heavy
platform operations behind them live in the service layer (builder_ops,
evolve.ops). The rule the split enforces: a route body orchestrates a call,
it does not own file I/O, SQL or loop logic.

When a built frontend is available it is served from the same origin (single
port, no CORS): static assets under /assets and an SPA fallback for
client-side routes. The fallback deliberately excludes /api and /mcp so the
governed surfaces can never be shadowed by the UI.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from ..errors import OOError
from ..service import ServiceContext
from .deps import require_admin, resolve_ui_dir
from .routes_accounts import register as register_accounts
from .routes_admin import register as register_admin
from .routes_agent import register as register_agent
from .routes_data import register as register_data
from .routes_evolve import register as register_evolve
from .routes_objects import register as register_objects


def build_app(sc: ServiceContext) -> FastAPI:
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        # The MCP tool surface (/mcp): mounted at startup so the compiled
        # snapshot exists; when the optional extra is absent this is a no-op
        # and /mcp simply has no route. api_factory WRAPS this lifespan with
        # sc.initialize() -- see ontogeny.api_factory.
        from ..mcp_server import mount_mcp

        async with mount_mcp(app, sc):
            yield

    app = FastAPI(title="Ontogeny", version="0.3.0", lifespan=_lifespan)
    app.state.sc = sc

    @app.middleware("http")
    async def mcp_bearer_gate(request: Request, call_next):
        """The MCP surface's driver gate (A2): with dev_auth off, /mcp demands
        the same bearer token the REST surface does; with it on (explicit
        opt-in, CI/demo) any caller may connect and the resolved identity is
        simply recorded on the session trail. Parity with the REST agent
        endpoints, one check."""
        if request.url.path.rstrip("/") == "/mcp":
            from ..mcp_server import set_mcp_driver

            set_mcp_driver(None)
            auth = getattr(sc, "auth", None)
            token = ""
            header = request.headers.get("authorization", "")
            if header.startswith("Bearer "):
                token = header[len("Bearer "):].strip()
            principal = await auth.resolve(token) if (auth is not None and token) else None
            if principal is not None:
                principal.setdefault("via", "bearer")
                set_mcp_driver(principal)
            elif not sc.settings.dev_auth:
                return JSONResponse(status_code=401, content={
                    "code": "MCP_DRIVER_UNAUTHENTICATED",
                    "message": "the MCP surface requires an authenticated driver: send "
                               "Authorization: Bearer <token from /api/v1/auth/login>"})
        return await call_next(request)

    r = APIRouter(prefix="/api/v1")
    # The admin and evolution planes rewrite the ontology itself (builder save,
    # publish, promote hot-swaps the compiled snapshot), so the gate is the
    # router, not each handler's memory: a route added tomorrow cannot
    # accidentally ship ungated the way the first ~15 of these did.
    admin_r = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(require_admin)])
    evolve_r = APIRouter(prefix="/api/v1/evolve", dependencies=[Depends(require_admin)])

    register_accounts(r, sc)
    register_objects(r, sc)
    register_agent(r, sc)
    register_data(app, r, sc)
    register_evolve(evolve_r, sc)
    register_admin(r, admin_r, sc)

    app.include_router(r)
    app.include_router(admin_r)
    app.include_router(evolve_r)

    @app.exception_handler(OOError)
    async def ontogeny_error_handler(request: Request, exc: OOError):
        return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    # ---- built SPA (same origin, single port) ------------------------------

    ui_dir = resolve_ui_dir(getattr(sc, "ui_dir", None))
    if ui_dir is not None:
        assets = ui_dir / "assets"
        # HTML must always revalidate: a stale cached shell/docs page survives
        # rebuilds and users keep seeing old content. Assets under /assets are
        # content-hashed filenames, so they may cache hard.
        NO_CACHE = {"Cache-Control": "no-cache"}

        @app.get("/assets/{path:path}", include_in_schema=False)
        async def _assets(path: str):
            target = (assets / path).resolve()
            if assets.resolve() not in target.parents and target != assets.resolve():
                return JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": "bad asset path"})
            if not target.is_file():
                return JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": "asset not found"})
            return FileResponse(target)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def _spa(full_path: str):
            # never shadow the governed surfaces
            if full_path.startswith(("api/", "mcp")) or full_path in ("api", "mcp"):
                return JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": f"no route for /{full_path}"})
            # the legacy in-app docs page is retired; docs live in the repo's
            # docs/ markdown tree now -- never serve it, even from a stale
            # UI dir, and never let /docs/* fall through to the SPA shell
            if full_path == "docs.html" or full_path.startswith("docs/"):
                return JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": f"no route for /{full_path}"})
            candidate = (ui_dir / full_path).resolve()
            if full_path and ui_dir.resolve() in candidate.parents and candidate.is_file():
                if candidate.suffix.lower() in (".html", ".htm"):
                    return FileResponse(candidate, headers=NO_CACHE)
                return FileResponse(candidate)
            return FileResponse(ui_dir / "index.html", headers=NO_CACHE)

    return app
