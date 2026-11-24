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

"""Immutable target context and plan-target verification helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hugegraph_mcp.config import MCPConfig, get_effective_config
from hugegraph_mcp.write_plan import GraphTarget, WritePlan


@dataclass(frozen=True)
class ResolvedTarget:
    """Normalized, immutable representation of the active HugeGraph target."""

    deployment_id: str
    graph_url: str
    graphspace: str
    graph_name: str
    principal: str
    alias: str | None = None
    route_version: int = 1

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (
            self.graph_url,
            self.graph_name,
            self.graphspace or "DEFAULT",
            self.principal,
        )


def resolve_target_from_config(
    cfg: MCPConfig | None = None,
    *,
    alias: str | None = None,
    route_version: int | None = None,
) -> ResolvedTarget:
    """Resolve the active single-target configuration into a ``ResolvedTarget``."""

    effective = cfg or get_effective_config()
    if alias is not None or getattr(effective, "graph_routes_json", None):
        from hugegraph_mcp.graph_routes import GraphRouteRegistry

        route = GraphRouteRegistry.from_config(effective).resolve(alias, expected_version=route_version)
        return route.to_resolved_target()
    return ResolvedTarget(
        deployment_id=effective.deployment_id,
        graph_url=effective.url,
        graphspace=effective.graphspace or "DEFAULT",
        graph_name=effective.graph,
        principal=effective.user,
        alias=alias,
        route_version=route_version or 1,
    )


def resolve_authorized_target(
    cfg: MCPConfig | None = None,
    *,
    alias: str | None = None,
    expected_route_version: int | None = None,
    actor: Any | None = None,
    write: bool = False,
) -> ResolvedTarget:
    """Resolve ``alias`` via ``GraphRouteRegistry`` and enforce actor authorization if provided."""
    from hugegraph_mcp.authorization import authorize_actor_for_route
    from hugegraph_mcp.graph_routes import GraphRouteRegistry

    effective = cfg or get_effective_config()
    route = GraphRouteRegistry.from_config(effective).resolve(
        alias,
        expected_version=expected_route_version,
    )
    if actor is not None:
        authorize_actor_for_route(actor, route, write=write)
    return route.to_resolved_target()


def plan_target_tuple(
    graph_target: GraphTarget | Mapping[str, Any] | None,
    principal: str | None,
) -> tuple[str, str, str, str]:
    """Normalize a persisted plan's target and principal into a comparison tuple."""

    if graph_target is None:
        return ("", "", "DEFAULT", str(principal or ""))
    if isinstance(graph_target, Mapping):
        graph_url = str(graph_target.get("graph_url") or "")
        graph_name = str(graph_target.get("graph_name") or "")
        graphspace = str(graph_target.get("graphspace") or "DEFAULT")
    else:
        graph_url = str(getattr(graph_target, "graph_url", None) or "")
        graph_name = str(getattr(graph_target, "graph_name", None) or "")
        graphspace = str(getattr(graph_target, "graphspace", None) or "DEFAULT")
    return (graph_url, graph_name, graphspace, str(principal or ""))


def target_matches_plan(target: ResolvedTarget, plan: WritePlan | Mapping[str, Any]) -> bool:
    """Return True when ``target`` matches the target and principal bound on ``plan``."""

    if isinstance(plan, Mapping):
        planned = plan_target_tuple(plan.get("graph_target"), str(plan.get("principal") or ""))
    else:
        planned = plan_target_tuple(plan.graph_target, plan.principal)
    return target.as_tuple() == planned


def target_mismatch_details(target: ResolvedTarget, plan: WritePlan | Mapping[str, Any]) -> dict[str, Any] | None:
    """Return structured mismatch details if ``target`` does not match ``plan``."""

    if isinstance(plan, Mapping):
        planned = plan_target_tuple(plan.get("graph_target"), str(plan.get("principal") or ""))
    else:
        planned = plan_target_tuple(plan.graph_target, plan.principal)
    if target.as_tuple() == planned:
        return None
    return {
        "reason_code": "TARGET_CHANGED",
        "expected_target": {
            "graph_url": planned[0],
            "graph_name": planned[1],
            "graphspace": planned[2],
            "principal": planned[3],
        },
        "current_target": {
            "graph_url": target.graph_url,
            "graph_name": target.graph_name,
            "graphspace": target.graphspace,
            "principal": target.principal,
        },
    }
