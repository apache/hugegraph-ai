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

"""Server-side graph alias route registry."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from hugegraph_mcp.config import MCPConfig, get_effective_config
from hugegraph_mcp.target_context import ResolvedTarget


class GraphRouteError(ValueError):
    """Base error for graph alias route configuration or resolution."""


class GraphRouteNotFoundError(GraphRouteError):
    """Raised when a requested graph_alias does not exist."""


class GraphRouteVersionMismatchError(GraphRouteError):
    """Raised when a caller requests a stale route_version."""


@dataclass(frozen=True)
class GraphRoute:
    """Server-owned target definition addressed by an opaque alias."""

    alias: str
    deployment_id: str
    graph_url: str
    graphspace: str
    graph_name: str
    user: str
    password: str = ""
    route_version: int = 1
    allowed_tenants: frozenset[str] = frozenset()
    required_scopes: frozenset[str] = frozenset()
    readonly: bool = False

    def to_resolved_target(self) -> ResolvedTarget:
        return ResolvedTarget(
            deployment_id=self.deployment_id,
            graph_url=self.graph_url,
            graphspace=self.graphspace or "DEFAULT",
            graph_name=self.graph_name,
            principal=self.user,
            alias=self.alias,
            route_version=self.route_version,
        )

    def to_config(self, base: MCPConfig) -> MCPConfig:
        """Return an MCPConfig scoped to this route without overriding global readonly."""
        return replace(
            base,
            deployment_id=self.deployment_id,
            url=self.graph_url,
            graphspace=self.graphspace or "DEFAULT",
            graph=self.graph_name,
            user=self.user,
            password=self.password,
            readonly=base.readonly or self.readonly,
        )


def _as_frozenset(raw: Any) -> frozenset[str]:
    if not raw:
        return frozenset()
    if isinstance(raw, str):
        return frozenset(part.strip() for part in raw.split(",") if part.strip())
    if isinstance(raw, Iterable):
        return frozenset(str(part).strip() for part in raw if str(part).strip())
    return frozenset()


class GraphRouteRegistry:
    """Registry mapping ``graph_alias`` strings to immutable ``GraphRoute`` targets."""

    def __init__(self, routes: Iterable[GraphRoute], *, default_alias: str = "default") -> None:
        self._routes: dict[str, GraphRoute] = {}
        for route in routes:
            if not route.alias.strip():
                raise GraphRouteError("Graph route alias must not be empty")
            if route.alias in self._routes:
                raise GraphRouteError(f"Duplicate graph route alias: {route.alias!r}")
            self._routes[route.alias] = route
        self._default_alias = default_alias

    @classmethod
    def from_config(cls, cfg: MCPConfig | None = None) -> GraphRouteRegistry:
        effective = cfg or get_effective_config()
        routes: list[GraphRoute] = []
        raw_json = getattr(effective, "graph_routes_json", None)
        if raw_json:
            try:
                parsed = json.loads(raw_json)
            except json.JSONDecodeError as exc:
                raise GraphRouteError(f"Invalid HUGEGRAPH_MCP_GRAPH_ROUTES JSON: {exc}") from exc
            if not isinstance(parsed, list):
                raise GraphRouteError("HUGEGRAPH_MCP_GRAPH_ROUTES must be a JSON array")
            for item in parsed:
                if not isinstance(item, Mapping):
                    raise GraphRouteError("Each graph route entry must be a JSON object")
                alias = str(item.get("alias") or "").strip()
                graph_url = str(item.get("graph_url") or item.get("url") or effective.url).strip()
                graph_name = str(item.get("graph_name") or item.get("graph") or "").strip()
                if not alias or not graph_name:
                    raise GraphRouteError("Graph route requires non-empty 'alias' and 'graph_name'")
                routes.append(
                    GraphRoute(
                        alias=alias,
                        deployment_id=str(item.get("deployment_id") or effective.deployment_id),
                        graph_url=graph_url,
                        graphspace=str(item.get("graphspace") or "DEFAULT"),
                        graph_name=graph_name,
                        user=str(item.get("user") or effective.user),
                        password=str(item.get("password") or effective.password),
                        route_version=int(item.get("route_version", 1)),
                        allowed_tenants=_as_frozenset(item.get("allowed_tenants")),
                        required_scopes=_as_frozenset(item.get("required_scopes")),
                        readonly=effective.readonly or bool(item.get("readonly", False)),
                    )
                )

        if not any(route.alias == "default" for route in routes):
            routes.insert(
                0,
                GraphRoute(
                    alias="default",
                    deployment_id=effective.deployment_id,
                    graph_url=effective.url,
                    graphspace=effective.graphspace or "DEFAULT",
                    graph_name=effective.graph,
                    user=effective.user,
                    password=effective.password,
                    route_version=1,
                    readonly=effective.readonly,
                ),
            )
        return cls(routes, default_alias="default")

    def list_aliases(self) -> tuple[str, ...]:
        return tuple(sorted(self._routes))

    def resolve(
        self,
        alias: str | None = None,
        *,
        expected_version: int | None = None,
    ) -> GraphRoute:
        target_alias = (alias or self._default_alias).strip()
        route = self._routes.get(target_alias)
        if route is None:
            raise GraphRouteNotFoundError(f"Unknown graph_alias: {target_alias!r}")
        if expected_version is not None and route.route_version != expected_version:
            raise GraphRouteVersionMismatchError(
                f"Route {target_alias!r} version mismatch: expected {expected_version}, got {route.route_version}"
            )
        return route
