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
"""MCP server: the ontology as an agent tool surface.

Two transports, ONE door. External MCP clients (Claude Desktop, ZCode,
LangGraph, ...) connect over streamable HTTP at ``/mcp``; the builtin LLM
engine drives the same tool surface over an in-memory MCP session. Both
funnel through :meth:`AgentBroker.call_tool` when a session is given, so
budget, catalog, approval gates and the step trail (I4) are IDENTICAL to
the REST session protocol -- MCP is a transport, not a second door.

Call shapes (every catalog tool accepts these reserved arguments):

- ``plugin`` + ``session_id``: execute as the plugin's frozen identity
  inside that session -- budget charged, writes gated, steps recorded.
- no session: read-only exploration. Reads run under the plugin principal
  narrowed to the plugin's own tool list (or the legacy shared
  ``mcp-agent`` identity, which role-gated policy refuses by design);
  writes are refused -- a session is the governed execution container
  (agent-paradigm §1).
- ``thought``: the caller's own reasoning for this step, recorded on the
  trail for human review (I4); never part of tool parameters.

Session-management tools (``agent_open_session`` ...) let a pure MCP client
run the whole lifecycle; approval DECISIONS stay with the human console.

Requires the optional ``mcp`` extra (mcp>=2.2); absent, the surface simply
does not mount and the builtin engine falls back to in-process calls.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, AsyncIterator, Iterable

from .errors import OOError
from .service import ServiceContext

log = logging.getLogger("ontogeny.mcp")

MCP_HTTP_PATH = "/mcp"
#: Comma-separated host allowlist; when set, the SDK's DNS-rebinding
#: protection is enabled for exactly these hosts. Unset (default) matches
#: the REST API's posture: no Host-header policing.
_ALLOWED_HOSTS_ENV = "ONTOGENY_MCP_ALLOWED_HOSTS"

#: The authenticated driver behind the current /mcp request (set by the
#: bearer gate middleware in ontogeny.api.app); tools read it so the session
#: trail records WHO drove, not just that the MCP transport did.
_MCP_DRIVER: ContextVar[dict[str, Any] | None] = ContextVar("ontogeny_mcp_driver", default=None)


def set_mcp_driver(principal: dict[str, Any] | None) -> None:
    _MCP_DRIVER.set(principal)


def current_mcp_driver() -> dict[str, Any] | None:
    return _MCP_DRIVER.get()


#: Header that scopes an MCP client's tools/list to ONE plugin's effective
#: catalog (plus the session tools). Large ontologies compile hundreds of
#: search_* tools; a plugin-scoped client (or an LLM behind it) sees only
#: what its plugin may call. Purely a VIEW filter -- call_tool enforcement
#: is unchanged (broker + frozen catalog).
PLUGIN_SCOPE_HEADER = "x-ontogeny-plugin"

_SESSION_TOOLS = {"agent_open_session", "agent_get_session",
                  "agent_list_sessions", "agent_finish_session"}


class PluginScopeMiddleware:
    """tools/list through a plugin-colored lens (see PLUGIN_SCOPE_HEADER).

    Runs at the context tier where the streamable-HTTP transport has attached
    the raw request; without the header (in-memory engine traffic, plain
    clients) it is a no-op pass-through.
    """

    def __init__(self, sc: ServiceContext) -> None:
        self.sc = sc

    async def __call__(self, ctx, call_next):
        result = await call_next(ctx)
        if ctx.method != "tools/list":
            return result
        plugin = None
        req = getattr(ctx, "request", None)
        getter = getattr(req, "headers", None)
        if getter is not None:
            try:
                plugin = getter.get(PLUGIN_SCOPE_HEADER)
            except Exception:  # noqa: BLE001 -- transport-specific header obj
                plugin = None
        if not plugin:
            return result
        compiled = self.sc.compiled
        plug = compiled.agent_plugins.get(plugin) if compiled else None
        if plug is None:
            from mcp.shared.exceptions import MCPError

            raise MCPError(-32000, f"unknown plugin {plugin!r} in {PLUGIN_SCOPE_HEADER}")
        from .agent.catalog import effective_tools

        keep = set(effective_tools(compiled, plug)) | _SESSION_TOOLS

        def _name(t):
            return t.name if hasattr(t, "name") else t.get("name")

        # the middleware runs pre-serialization: some SDK paths hand the
        # pydantic result, others the wire dict -- filter both shapes
        if hasattr(result, "tools"):
            result.tools = [t for t in result.tools if _name(t) in keep]
        elif isinstance(result, dict) and "tools" in result:
            result["tools"] = [t for t in result["tools"] if _name(t) in keep]
        return result


def mcp_sdk() -> Any:
    """The ``mcp`` 2.x SDK module, or None when the optional extra is absent."""
    try:
        import mcp.server.mcpserver as mod
    except ImportError:
        return None
    return mod


def build_mcp_server(sc: ServiceContext, *, engine_mode: bool = False):
    """Compatibility shim: one server instance, tools built from the current
    compiled snapshot. Returns ``None`` when the extra is missing."""
    surface = McpSurface(sc, engine_mode=engine_mode)
    surface.build()
    return surface.server


def _first_text(content: Iterable[Any]) -> str:
    for block in content or []:
        text = getattr(block, "text", None)
        if text:
            return text
    return ""


# --------------------------------------------------------------------- client


class McpToolClient:
    """A thin envelope decoder over an MCP ``ClientSession``.

    The engine (and tests) use this to speak the MCP protocol without
    caring about wire details: tools return the broker's result envelope
    verbatim as structured content; wire/protocol failures become outcome
    envelopes instead of exceptions, matching the session protocol's
    structured-outcome contract (agent-paradigm §3.1).
    """

    def __init__(self, session: Any) -> None:
        self.session = session

    async def list_tools(self) -> list[dict[str, Any]]:
        res = await self.session.list_tools()
        return [{"name": t.name, "description": t.description or "",
                 "input_schema": getattr(t, "input_schema", None) or getattr(t, "inputSchema", {})
                 or {}} for t in res.tools]

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        from mcp.shared.exceptions import MCPError

        try:
            res = await self.session.call_tool(name, args)
        except MCPError as exc:  # protocol-level refusal (unknown tool, ...)
            text = str(exc)
            if "unknown tool" in text.lower():
                return {"outcome": "NOT_FOUND", "error": text}
            return {"outcome": "MCP_TOOL_ERROR", "error": text}
        if getattr(res, "is_error", False):
            text = _first_text(res.content)
            if text.lower().startswith("unknown tool"):
                return {"outcome": "NOT_FOUND", "error": text}
            return {"outcome": "MCP_TOOL_ERROR", "error": text}
        structured = getattr(res, "structured_content", None)
        if isinstance(structured, dict):
            return structured
        text = _first_text(res.content)
        try:
            decoded = json.loads(text) if text else {}
        except (TypeError, ValueError):
            return {"outcome": "ok", "detail": text}
        return decoded if isinstance(decoded, dict) else {"outcome": "ok", "detail": decoded}


# --------------------------------------------------------------------- surface


class McpSurface:
    """The MCP tool surface over one ServiceContext.

    ``engine_mode=True`` builds the instance the builtin engine drives:
    broker calls carry ``engine=True`` so the driving engine may own a
    ``running`` session (agent-paradigm §2). That instance is reachable
    only over in-process memory streams, never over the wire.
    """

    def __init__(self, sc: ServiceContext, *, engine_mode: bool = False) -> None:
        self.sc = sc
        self.engine_mode = engine_mode
        self.sdk = mcp_sdk()
        self.server: Any = None
        self._mounted = False

    # -------------------------------------------------------------- building

    def build(self) -> None:
        """(Re)build the tool registrations from the CURRENT compiled snapshot.

        Called at mount time and again whenever the ontology is promoted --
        the tool list is a compiled artifact, never hand-maintained.
        """
        if self.sdk is None or self.sc.compiled is None:
            return
        if self.server is None:
            kwargs: dict[str, Any] = {}
            if not self.engine_mode:
                # the wire surface gets the plugin-scope lens; the engine's
                # private surface drives with the session's frozen catalog
                kwargs["middleware"] = [PluginScopeMiddleware(self.sc)]
            self.server = self.sdk.MCPServer(
                "ontogeny",
                title="Ontogeny — operational ontology",
                description="Operational ontology as an agent tool surface",
                instructions=(
                    "Tools mirror the governed session protocol. Pass plugin "
                    "and session_id (see agent_open_session) to run inside a "
                    "session's budget, catalog and approval gates; without a "
                    "session calls are read-only. Send the "
                    f"'{PLUGIN_SCOPE_HEADER}: <plugin>' header on tools/list to "
                    "see only one plugin's effective catalog."
                ),
                **kwargs,
            )
        else:
            for tool in list(self.server._tool_manager.list_tools()):
                self.server.remove_tool(tool.name)
        self._register_catalog_tools()
        self._register_session_tools()

    def refresh(self) -> None:
        """Rebuild tool registrations after the compiled snapshot changed."""
        if self.server is not None:
            self.build()

    def _register_catalog_tools(self) -> None:
        from .agent.catalog import build_catalog

        for name, tdef in sorted(build_catalog(self.sc.compiled).items()):
            self.server.add_tool(
                _catalog_tool_fn(self.sc, name, tdef, self.engine_mode),
                name=name,
                description=tdef.description,
                structured_output=True,
            )

    def _register_session_tools(self) -> None:
        sc, server = self.sc, self.server

        async def agent_open_session(plugin: str, task: str = "") -> dict[str, Any]:
            """Open an agent session for a declared AgentPlugin; returns the
            session view incl. the tools you may call and the id to pass as
            session_id on every tool call."""
            return await sc.agents.open_session(plugin, task or "",
                                                driver=current_mcp_driver())

        async def agent_get_session(session_id: int) -> dict[str, Any]:
            """Session view: status, budget usage, effective tools, full step
            trail (thought + outcome per step) -- the driver's transcript."""
            return await sc.agents.get_session(session_id)

        async def agent_list_sessions(plugin: str | None = None,
                                      limit: int = 50) -> dict[str, Any]:
            """List agent sessions, newest first (optionally per plugin)."""
            return {"sessions": await sc.agents.list_sessions(plugin=plugin,
                                                              limit=min(int(limit), 200))}

        async def agent_finish_session(session_id: int,
                                       result: dict | None = None) -> dict[str, Any]:
            """Finish a session with a final result (the human-facing act)."""
            return await sc.agents.finish_session(session_id, result)

        for fn in (agent_open_session, agent_get_session,
                   agent_list_sessions, agent_finish_session):
            server.add_tool(fn, structured_output=True)

    # --------------------------------------------------------------- serving

    def graft(self, app: Any) -> bool:
        """Attach the streamable-HTTP route(s) to a FastAPI/Starlette app.

        Grafting the routes directly (instead of ``Mount``) serves exactly
        ``/mcp`` with no 307 redirect games; the SPA fallback already
        excludes the path, and MCP clients only ever POST in JSON mode.
        Idempotent per app.
        """
        if self.sdk is None or self.server is None:
            return False
        if self._mounted:
            return True
        kwargs: dict[str, Any] = dict(
            streamable_http_path=MCP_HTTP_PATH,
            # POST + JSON responses, one request per call: survives proxies
            # and test ASGI transports, and matches the stateless call shape
            # (every call carries plugin/session_id anyway)
            json_response=True,
            stateless_http=True,
        )
        # the SDK auto-enables DNS-rebinding protection for localhost hosts;
        # ontogeny's REST surface does no Host policing, so the MCP surface
        # matches it by default and ONTOGENY_MCP_ALLOWED_HOSTS opts INTO a list
        from mcp.server.transport_security import TransportSecuritySettings
        hosts = [h.strip() for h in os.environ.get(_ALLOWED_HOSTS_ENV, "").split(",") if h.strip()]
        kwargs["transport_security"] = (
            TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts)
            if hosts else
            TransportSecuritySettings(enable_dns_rebinding_protection=False)
        )
        starlette = self.server.streamable_http_app(**kwargs)
        existing = {getattr(route, "path", None) for route in app.router.routes}
        for route in starlette.routes:
            if getattr(route, "path", None) not in existing:
                app.router.routes.append(route)
        self._mounted = True
        return True

    @asynccontextmanager
    async def run(self, app: Any) -> AsyncIterator[Any]:
        """Serve: build (if needed), graft, run the HTTP session manager."""
        if self.sdk is None:
            log.info("MCP surface disabled: the optional extra is not installed "
                     "(pip install 'ontogeny[mcp]')")
            yield None
            return
        if self.server is None:
            self.build()
        if self.server is None:  # compiled not ready yet
            yield None
            return
        self.graft(app)
        async with self.server.session_manager.run():
            log.info("MCP surface serving at %s (json, stateless)", MCP_HTTP_PATH)
            yield self.server


@asynccontextmanager
async def mount_mcp(app: Any, sc: ServiceContext) -> AsyncIterator[Any]:
    """Mount + run the external MCP surface on a FastAPI app (lifespan-side).

    The surface is stored on ``sc`` so a later promote can refresh it
    (``sc.mcp_surface.refresh()``).
    """
    surface = McpSurface(sc)
    sc.mcp_surface = surface  # type: ignore[attr-defined]
    async with surface.run(app):
        yield surface


@asynccontextmanager
async def in_process_mcp_session(sc: ServiceContext, *,
                                 engine_mode: bool = True) -> AsyncIterator[McpToolClient]:
    """The builtin engine's transport: a real MCP client session over
    in-memory streams against a private server.

    ``engine_mode=True`` (the default, used by the engine) lets the driving
    engine own a ``running`` session; ``False`` is the in-process stand-in
    for an EXTERNAL client -- tests use it to prove the §2 isolation the
    wire surface enforces.

    Same protocol, same handlers, same governance as the wire surface --
    the reference engine dogfoods the surface external agents use, without
    sockets (tests stay hermetic). Cancellation-safe: the server task is
    always collected.
    """
    from mcp.client.session import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams

    surface = McpSurface(sc, engine_mode=engine_mode)
    surface.build()
    if surface.server is None:
        raise OOError("engine MCP session requires the optional dependency: "
                      "pip install 'ontogeny[mcp]' (and a compiled ontology)",
                      details={"missing": "mcp"})
    low = surface.server._lowlevel_server
    async with create_client_server_memory_streams() as (client_side, server_side):
        server_task = asyncio.create_task(
            low.run(server_side[0], server_side[1], low.create_initialization_options()))
        try:
            async with ClientSession(client_side[0], client_side[1]) as sess:
                await sess.initialize()
                yield McpToolClient(sess)
        finally:
            server_task.cancel()
            try:
                await server_task
            except BaseException:  # noqa: BLE001 -- cancelled server task
                pass


# ------------------------------------------------------------ tool generation

#: catalog input_schema type -> signature annotation. Anything object/array
#: shaped maps to Any: the schema stays permissive, the broker validates.
_SCHEMA_ANN: dict[str, Any] = {
    "integer": int | None, "string": str | None,
    "number": float | None, "boolean": bool | None,
}


def _catalog_tool_fn(sc: ServiceContext, name: str, tdef, engine_mode: bool):
    """One MCP tool = one catalog ToolDef, dispatched through the broker
    when a session is given (the governed path), else read-only direct.

    The tool's signature is generated from the ToolDef's input_schema so
    clients (and the LLM behind them) see the same parameter shape as the
    REST session protocol's ``input_schema``.
    """
    props: dict[str, Any] = (tdef.input_schema or {}).get("properties") or {}

    async def tool(plugin: str | None = None, session_id: int | None = None,
                   thought: str | None = None, **kwargs: Any) -> dict[str, Any]:
        if session_id is not None:
            return await sc.agents.call_tool(int(session_id), name, kwargs,
                                             engine=engine_mode, thought=thought or "")
        return await _readonly_call(sc, name, tdef, plugin, kwargs)

    # the SDK refuses parameters starting with '_', so the reserved transport
    # arguments go bare -- they cannot collide with the catalog vocabulary
    # (filter/limit/parameters/target_id/...); a same-named ontology property
    # would simply be shadowed, which the fixed vocabulary makes impossible
    reserved = {"plugin": str | None, "session_id": int | None, "thought": str | None}
    parameters = [
        inspect.Parameter(pname, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                          default=None, annotation=ann)
        for pname, ann in reserved.items()
    ]
    annotations: dict[str, Any] = dict(reserved)
    for pname, pschema in props.items():
        if pname in reserved:
            continue
        # scalars stay typed; object/array args stay permissive (Any) so the
        # caller's JSON passes validation exactly as the REST path accepts it
        annotation = _SCHEMA_ANN.get(pschema.get("type"), Any)
        default = pschema.get("default") if "default" in pschema else None
        parameters.append(inspect.Parameter(pname, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                            default=default, annotation=annotation))
        annotations[pname] = annotation
    tool.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters, return_annotation=dict[str, Any])
    tool.__annotations__ = {**annotations, "return": dict[str, Any]}
    tool.__doc__ = tdef.description
    tool.__name__ = name
    return tool


async def _readonly_call(sc: ServiceContext, name: str, tdef, plugin_name: str | None,
                         args: dict[str, Any]) -> dict[str, Any]:
    """Session-less calls: reads only, dispatched by the BROKER's read_only_tool
    -- the same dispatcher the session path uses, so telemetry, argument
    strictness and error envelopes cannot drift between the two surfaces.
    Under a plugin principal the tool list is narrowed to the plugin's own
    catalog (I1: a plugin can only narrow). The write refusal is the point:
    sessions are the governed execution containers."""
    return await sc.agents.read_only_tool(name, plugin_name, args)
