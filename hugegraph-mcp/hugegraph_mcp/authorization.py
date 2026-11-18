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

"""Actor scope and graph-route authorization checks."""

from __future__ import annotations

from hugegraph_mcp.graph_routes import GraphRoute
from hugegraph_mcp.stores.base import Actor, ActorAuthorizationError


def authorize_tool_access(actor: Actor, *, is_write: bool) -> None:
    """Enforce coarse read/write scope gates for an authenticated Actor."""
    if is_write:
        if actor.is_anonymous:
            raise ActorAuthorizationError("Anonymous actor is not permitted to perform write operations")
        if "mcp:write" not in actor.scopes:
            raise ActorAuthorizationError("Actor lacks required 'mcp:write' scope")
        return
    if not actor.is_anonymous and "mcp:read" not in actor.scopes and "mcp:write" not in actor.scopes:
        raise ActorAuthorizationError("Actor lacks required 'mcp:read' scope")


def authorize_actor_for_route(
    actor: Actor,
    route: GraphRoute,
    *,
    write: bool = False,
) -> None:
    """Enforce tenant, scope, and readonly gates for a resolved GraphRoute."""
    authorize_tool_access(actor, is_write=write)
    if write and route.readonly:
        raise ActorAuthorizationError(f"Graph route {route.alias!r} is read-only")
    if route.allowed_tenants and actor.tenant not in route.allowed_tenants:
        raise ActorAuthorizationError(f"Tenant {actor.tenant!r} is not authorized for graph route {route.alias!r}")
    if route.required_scopes and not route.required_scopes.issubset(actor.scopes):
        missing = sorted(route.required_scopes - actor.scopes)
        raise ActorAuthorizationError(f"Actor missing required scopes {missing} for graph route {route.alias!r}")
