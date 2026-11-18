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

from __future__ import annotations

import asyncio
import json

import pytest

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.graph_routes import (
    GraphRouteNotFoundError,
    GraphRouteRegistry,
    GraphRouteVersionMismatchError,
)
from hugegraph_mcp.stores.base import Actor, ActorAuthorizationError
from hugegraph_mcp.target_context import resolve_authorized_target


def test_public_query_uses_the_authorized_backend_and_reports_it(monkeypatch):
    from unittest.mock import Mock

    from hugegraph_mcp import server
    from hugegraph_mcp.runtime import reset_current_actor, set_current_actor
    from hugegraph_mcp.tools import query_graph_data

    route = {
        "alias": "default",
        "graph_name": "routed",
        "graphspace": "SPACE",
        "graph_url": "http://routed:8080",
        "user": "routed-reader",
        "password": "route-fixture",
        "allowed_tenants": ["team"],
    }
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "fallback")
    monkeypatch.setenv("HUGEGRAPH_MCP_GRAPH_ROUTES", json.dumps([route]))
    client = Mock()
    client.return_value.graph.return_value.get_vertex_by_id.return_value = {"id": "vertex"}
    monkeypatch.setattr(query_graph_data, "PyHugeClient", client)

    def query(tenant):
        token = set_current_actor(Actor(issuer="local", tenant=tenant, subject="user", scopes=frozenset({"mcp:read"})))
        try:
            return server.query_graph_data_tool(target="vertex", operation="get_by_id", id="vertex")
        finally:
            reset_current_actor(token)

    denied = query("other")
    assert denied["error"]["type"] == "AUTHORIZATION_FAILED"
    client.assert_not_called()
    result = query("team")
    assert result["ok"] and result["meta"]["graph"] == "routed"
    args = client.call_args.kwargs
    assert (args["url"], args["graph"], args["graphspace"], args["user"], args["pwd"]) == (
        "http://routed:8080",
        "routed",
        "SPACE",
        "routed-reader",
        "route-fixture",
    )


def test_schema_resource_authorizes_default_route_before_cache_lookup(tmp_path, monkeypatch):
    from hugegraph_mcp import resources
    from hugegraph_mcp.config import get_effective_config
    from hugegraph_mcp.runtime import build_runtime, reset_current_actor, set_current_actor

    route = {"alias": "default", "graph_name": "routed", "allowed_tenants": ["team"]}
    cfg = MCPConfig.from_env(
        {
            "HUGEGRAPH_GRAPH": "fallback",
            "HUGEGRAPH_MCP_GRAPH_ROUTES": json.dumps([route]),
            "HUGEGRAPH_MCP_STATE_DIR": str(tmp_path),
        }
    )
    runtime = build_runtime(cfg)
    seen = []

    def inspect(**_kwargs):
        seen.append(get_effective_config().graph)
        return {"ok": True, "data": {"raw_schema": {}, "schema_fingerprint": "fp", "truncated": False}}

    monkeypatch.setattr(resources, "inspect_schema", inspect)

    def read(tenant):
        token = set_current_actor(Actor(issuer="local", tenant=tenant, subject="user", scopes=frozenset({"mcp:read"})))
        try:
            return asyncio.run(resources.read_schema_resource("default", "DEFAULT", "routed", runtime=runtime))
        finally:
            reset_current_actor(token)

    assert json.loads(read("team"))["graph"] == "routed"
    with pytest.raises(ActorAuthorizationError):
        read("other")
    assert seen == ["routed"]


def _config_with_routes() -> MCPConfig:
    routes = [
        {
            "alias": "analytics",
            "graph_url": "http://hg-analytics:8080",
            "graphspace": "PROD",
            "graph_name": "social_graph",
            "user": "svc-analytics",
            "route_version": 2,
            "allowed_tenants": ["acme", "beta"],
            "required_scopes": ["graph:analytics"],
            "readonly": True,
        },
        {
            "alias": "ingest",
            "graph_url": "http://hg-ingest:8080",
            "graph_name": "ingest_graph",
            "user": "svc-ingest",
            "route_version": 1,
            "allowed_tenants": ["acme"],
            "required_scopes": ["mcp:write"],
            "readonly": False,
        },
    ]
    return MCPConfig.from_env({"HUGEGRAPH_MCP_GRAPH_ROUTES": json.dumps(routes), "HUGEGRAPH_MCP_READONLY": "false"})


def test_graph_route_registry_resolves_alias_and_default() -> None:
    cfg = _config_with_routes()
    registry = GraphRouteRegistry.from_config(cfg)

    assert registry.list_aliases() == ("analytics", "default", "ingest")
    analytics = registry.resolve("analytics", expected_version=2)
    assert analytics.graph_name == "social_graph"
    assert analytics.graphspace == "PROD"
    assert analytics.readonly is True

    default_route = registry.resolve()
    assert default_route.alias == "default"
    assert default_route.graph_name == "hugegraph"


def test_graph_route_registry_rejects_unknown_alias_and_version_mismatch() -> None:
    cfg = _config_with_routes()
    registry = GraphRouteRegistry.from_config(cfg)

    with pytest.raises(GraphRouteNotFoundError):
        registry.resolve("missing")

    with pytest.raises(GraphRouteVersionMismatchError):
        registry.resolve("analytics", expected_version=1)


def test_resolve_authorized_target_enforces_tenant_scope_and_readonly() -> None:
    cfg = _config_with_routes()

    authorized_reader = Actor(
        issuer="https://idp.example",
        tenant="acme",
        subject="alice",
        scopes=frozenset({"mcp:read", "graph:analytics"}),
    )
    target = resolve_authorized_target(
        cfg,
        alias="analytics",
        expected_route_version=2,
        actor=authorized_reader,
        write=False,
    )
    assert target.alias == "analytics"
    assert target.route_version == 2
    assert target.graph_name == "social_graph"

    # Readonly route blocks write even if actor has mcp:write
    writer_on_readonly = Actor(
        issuer="https://idp.example",
        tenant="acme",
        subject="alice",
        scopes=frozenset({"mcp:read", "mcp:write", "graph:analytics"}),
    )
    with pytest.raises(ActorAuthorizationError, match="read-only"):
        resolve_authorized_target(cfg, alias="analytics", actor=writer_on_readonly, write=True)

    # Wrong tenant is blocked
    wrong_tenant = Actor(
        issuer="https://idp.example",
        tenant="other-tenant",
        subject="bob",
        scopes=frozenset({"mcp:read", "mcp:write"}),
    )
    with pytest.raises(ActorAuthorizationError, match="Tenant"):
        resolve_authorized_target(cfg, alias="ingest", actor=wrong_tenant, write=True)

    # Missing required scope is blocked
    missing_scope = Actor(
        issuer="https://idp.example",
        tenant="acme",
        subject="carol",
        scopes=frozenset({"mcp:read"}),
    )
    with pytest.raises(ActorAuthorizationError, match="scopes"):
        resolve_authorized_target(cfg, alias="analytics", actor=missing_scope, write=False)
