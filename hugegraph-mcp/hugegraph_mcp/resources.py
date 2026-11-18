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

"""MCP Resource providers for HugeGraph schema, summary, embeddings, and write plans."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from hugegraph_mcp.artifacts import get_default_artifact_store
from hugegraph_mcp.artifacts.base import ArtifactNotFoundError
from hugegraph_mcp.authorization import authorize_actor_for_route
from hugegraph_mcp.config import MCPConfig, reset_request_config, set_request_config
from hugegraph_mcp.graph_routes import GraphRouteRegistry
from hugegraph_mcp.plan_store import SQLitePlanStore
from hugegraph_mcp.resource_uri import (
    ArtifactResourceURI,
    GraphResourceURI,
    InvalidResourceURIError,
    PlanResourceURI,
    build_artifact_resource_uri,
    build_graph_resource_uri,
    build_plan_resource_uri,
    parse_resource_uri,
)
from hugegraph_mcp.runtime import RuntimeContainer, get_current_actor, get_current_runtime
from hugegraph_mcp.schema_snapshot import bound_schema_payload, compute_schema_fingerprint
from hugegraph_mcp.stores.base import Actor, PlanNotFoundError, SyncToAsyncPlanStoreAdapter
from hugegraph_mcp.tools.inspect_graph import inspect_graph
from hugegraph_mcp.tools.inspect_schema import inspect_schema


def _resolve_target_guard(deployment: str, graphspace: str, graph: str, cfg: MCPConfig) -> MCPConfig:
    if cfg.graph_routes_json:
        route = GraphRouteRegistry.from_config(cfg).resolve()
        authorize_actor_for_route(get_current_actor(), route)
        cfg = route.to_config(cfg)
    expected_dep = cfg.deployment_id
    expected_gs = cfg.graphspace or "DEFAULT"
    if deployment != expected_dep or graphspace != expected_gs or graph != cfg.graph:
        raise InvalidResourceURIError(
            f"Requested target {deployment}/{graphspace}/{graph} does not match "
            f"configured target {expected_dep}/{expected_gs}/{cfg.graph}"
        )
    return cfg


async def _read_with_config(cfg: MCPConfig, read, **kwargs):
    token = set_request_config(cfg)
    try:
        return await asyncio.to_thread(read, **kwargs)
    finally:
        reset_request_config(token)


async def read_schema_resource(
    deployment: str,
    graphspace: str,
    graph: str,
    *,
    runtime: RuntimeContainer | None = None,
) -> str:
    rt = runtime or get_current_runtime()
    cfg = rt.config if rt is not None else MCPConfig.from_env()
    uri = build_graph_resource_uri(deployment, graphspace, graph, "schema")
    parse_resource_uri(uri)
    cfg = _resolve_target_guard(deployment, graphspace, graph, cfg)

    cache_key = (deployment, graphspace, graph, "schema", "public")
    now = time.time()
    if rt is not None:
        cached = rt.resource_cache.get(cache_key, now=now, ttl_s=rt.resource_cache.schema_ttl_s)
        if cached is not None:
            return json.dumps(cached, ensure_ascii=False, indent=2)

    envelope = await _read_with_config(cfg, inspect_schema, include_raw_schema=True)
    if not envelope.get("ok"):
        raise RuntimeError(envelope.get("error", {}).get("message", "Failed to inspect schema"))
    data = dict(envelope.get("data") or {})
    raw_schema = data.get("raw_schema")
    already_bounded = "schema_fingerprint" in data and "truncated" in data
    fingerprint = data.pop("schema_fingerprint", None) or compute_schema_fingerprint(
        raw_schema if isinstance(raw_schema, dict) else data
    )
    truncated = bool(data.get("truncated", False))
    truncation_reason = data.get("truncation_reason")
    if isinstance(raw_schema, dict) and not already_bounded:
        bounded_raw, raw_truncated, raw_reason = bound_schema_payload(raw_schema)
        data["raw_schema"] = bounded_raw
        truncated = truncated or raw_truncated
        truncation_reason = truncation_reason or raw_reason
    payload = {
        "uri": uri,
        "deployment": deployment,
        "graphspace": graphspace,
        "graph": graph,
        "schema_fingerprint": fingerprint,
        "observed_at": now,
        "truncated": truncated,
        "truncation_reason": truncation_reason,
        "schema": data,
    }
    if rt is not None:
        rt.resource_cache.set(cache_key, payload, now=now, fingerprint=fingerprint)
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def read_summary_resource(
    deployment: str,
    graphspace: str,
    graph: str,
    *,
    runtime: RuntimeContainer | None = None,
) -> str:
    rt = runtime or get_current_runtime()
    cfg = rt.config if rt is not None else MCPConfig.from_env()
    uri = build_graph_resource_uri(deployment, graphspace, graph, "summary")
    parse_resource_uri(uri)
    cfg = _resolve_target_guard(deployment, graphspace, graph, cfg)

    cache_key = (deployment, graphspace, graph, "summary", "public")
    now = time.time()
    if rt is not None:
        cached = rt.resource_cache.get(cache_key, now=now, ttl_s=rt.resource_cache.summary_ttl_s)
        if cached is not None:
            return json.dumps(cached, ensure_ascii=False, indent=2)

    envelope = await _read_with_config(cfg, inspect_graph, include_raw_schema=False)
    data = dict(envelope.get("data") or {})
    server_status = data.get("hugegraph_server_status")
    if not envelope.get("ok") or server_status not in (None, "available"):
        payload = {
            "uri": uri,
            "deployment": deployment,
            "graphspace": graphspace,
            "graph": graph,
            "status": "degraded",
            "observed_at": now,
            "error": (
                envelope.get("error", {}).get("message")
                if not envelope.get("ok")
                else f"HugeGraph server status is {server_status!r}"
            ),
            "warnings": list(envelope.get("warnings") or []),
            "summary": data,
        }
    else:
        payload = {
            "uri": uri,
            "deployment": deployment,
            "graphspace": graphspace,
            "graph": graph,
            "status": "ok",
            "observed_at": now,
            "summary": data,
        }
        if rt is not None:
            rt.resource_cache.set(cache_key, payload, now=now)
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def read_embeddings_vid_resource(
    deployment: str,
    graphspace: str,
    graph: str,
    *,
    runtime: RuntimeContainer | None = None,
) -> str:
    rt = runtime or get_current_runtime()
    cfg = rt.config if rt is not None else MCPConfig.from_env()
    uri = build_graph_resource_uri(deployment, graphspace, graph, "embeddings_vid")
    parse_resource_uri(uri)
    _resolve_target_guard(deployment, graphspace, graph, cfg)

    cache_key = (deployment, graphspace, graph, "embeddings_vid", "public")
    now = time.time()
    if rt is not None:
        cached = rt.resource_cache.get(cache_key, now=now, ttl_s=rt.resource_cache.embeddings_ttl_s)
        if cached is not None:
            return json.dumps(cached, ensure_ascii=False, indent=2)

    payload = {
        "uri": uri,
        "deployment": deployment,
        "graphspace": graphspace,
        "graph": graph,
        "allow_ai": cfg.allow_ai,
        "ai_url": cfg.ai_url if cfg.allow_ai else None,
        "observed_at": now,
        "status": "configured" if cfg.allow_ai else "disabled",
    }
    if rt is not None:
        rt.resource_cache.set(cache_key, payload, now=now)
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def read_plan_resource(
    plan_id: str,
    *,
    runtime: RuntimeContainer | None = None,
    actor: Actor | None = None,
) -> str:
    rt = runtime or get_current_runtime()
    effective_actor = actor or get_current_actor()
    uri = build_plan_resource_uri(plan_id)
    parse_resource_uri(uri)

    store = (
        rt.plan_store
        if rt is not None
        else SyncToAsyncPlanStoreAdapter(SQLitePlanStore.from_config(MCPConfig.from_env()))
    )
    try:
        view = await store.read(plan_id, effective_actor)
    except PlanNotFoundError as exc:
        raise ValueError(f"Resource {uri} not found") from exc

    payload = {
        "uri": uri,
        **view.to_public_dict(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def read_artifact_manifest_resource(
    artifact_id: str,
    *,
    runtime: RuntimeContainer | None = None,
    actor: Actor | None = None,
) -> str:
    rt = runtime or get_current_runtime()
    cfg = rt.config if rt is not None else MCPConfig.from_env()
    uri = build_artifact_resource_uri(artifact_id)
    parse_resource_uri(uri)
    effective_actor = actor or get_current_actor()
    try:
        manifest = get_default_artifact_store(cfg).get_manifest(
            artifact_id,
            owner_key=effective_actor.principal_key,
            tenant=effective_actor.tenant,
        )
    except ArtifactNotFoundError as exc:
        raise ValueError(f"Resource {uri} not found") from exc
    return json.dumps({"uri": uri, "manifest": manifest.to_dict()}, ensure_ascii=False, indent=2)


async def read_artifact_part_resource(
    artifact_id: str,
    part_id: int,
    *,
    runtime: RuntimeContainer | None = None,
    actor: Actor | None = None,
) -> str:
    rt = runtime or get_current_runtime()
    cfg = rt.config if rt is not None else MCPConfig.from_env()
    uri = build_artifact_resource_uri(artifact_id, part_id=part_id)
    parse_resource_uri(uri)
    effective_actor = actor or get_current_actor()
    store = get_default_artifact_store(cfg)
    try:
        store.get_manifest(
            artifact_id,
            owner_key=effective_actor.principal_key,
            tenant=effective_actor.tenant,
        )
        part = store.read_part(artifact_id, part_id, owner_key=effective_actor.principal_key)
    except ArtifactNotFoundError as exc:
        raise ValueError(f"Resource {uri} not found") from exc
    return json.dumps(
        {
            "uri": uri,
            "artifact_id": part.artifact_id,
            "part_id": part.part_id,
            "sha256": part.sha256,
            "size_bytes": part.size_bytes,
            "content": part.content,
        },
        ensure_ascii=False,
        indent=2,
    )


def register_resources(mcp_app: Any) -> None:
    """Register HugeGraph MCP Resource templates on a FastMCP instance."""

    @mcp_app.resource(
        "hugegraph://{deployment}/{graphspace}/{graph}/schema",
        name="hugegraph_schema",
        description="Bounded JSON snapshot of the HugeGraph schema with SHA-256 fingerprint.",
        mime_type="application/json",
    )
    async def schema_resource(deployment: str, graphspace: str, graph: str) -> str:
        return await read_schema_resource(deployment, graphspace, graph)

    @mcp_app.resource(
        "hugegraph://{deployment}/{graphspace}/{graph}/summary",
        name="hugegraph_summary",
        description="Graph identity, label summary, and observed counts.",
        mime_type="application/json",
    )
    async def summary_resource(deployment: str, graphspace: str, graph: str) -> str:
        return await read_summary_resource(deployment, graphspace, graph)

    @mcp_app.resource(
        "hugegraph://{deployment}/{graphspace}/{graph}/embeddings/vid",
        name="hugegraph_vid_embeddings",
        description="AI VID embedding index status for the target graph.",
        mime_type="application/json",
    )
    async def embeddings_vid_resource(deployment: str, graphspace: str, graph: str) -> str:
        return await read_embeddings_vid_resource(deployment, graphspace, graph)

    @mcp_app.resource(
        "plan://{plan_id}",
        name="hugegraph_write_plan",
        description="Sanitized read-only projection of a write plan and its durable receipts.",
        mime_type="application/json",
    )
    async def plan_resource(plan_id: str) -> str:
        return await read_plan_resource(plan_id)

    @mcp_app.resource(
        "artifact://{artifact_id}",
        name="hugegraph_artifact_manifest",
        description="Owner-authorized manifest for an immutable extraction or preview artifact.",
        mime_type="application/json",
    )
    async def artifact_manifest_resource(artifact_id: str) -> str:
        return await read_artifact_manifest_resource(artifact_id)

    @mcp_app.resource(
        "artifact://{artifact_id}/parts/{part_id}",
        name="hugegraph_artifact_part",
        description="Bounded part slice of an immutable MCP artifact.",
        mime_type="application/json",
    )
    async def artifact_part_resource(artifact_id: str, part_id: int) -> str:
        return await read_artifact_part_resource(artifact_id, part_id)

    low_level = getattr(mcp_app, "_mcp_server", None)
    if low_level is not None and hasattr(low_level, "add_request_handler"):
        from mcp import types as mcp_types

        def _session_key(session: Any) -> str:
            return str(getattr(session, "session_id", None) or id(getattr(session, "_connection", session)))

        async def _handle_subscribe(
            ctx: Any,
            params: mcp_types.SubscribeRequestParams,
        ) -> mcp_types.EmptyResult:
            uri_str = str(params.uri)
            parsed_uri = parse_resource_uri(uri_str)
            rt = get_current_runtime()
            cfg = rt.config if rt is not None else MCPConfig.from_env()
            if isinstance(parsed_uri, GraphResourceURI):
                _resolve_target_guard(parsed_uri.deployment, parsed_uri.graphspace, parsed_uri.graph, cfg)
            elif isinstance(parsed_uri, PlanResourceURI):
                raise InvalidResourceURIError(f"Resource subscriptions are not supported for plan URIs: {uri_str}")
            elif isinstance(parsed_uri, ArtifactResourceURI):
                effective_actor = get_current_actor()
                get_default_artifact_store(cfg).get_manifest(
                    parsed_uri.artifact_id,
                    owner_key=effective_actor.principal_key,
                    tenant=effective_actor.tenant,
                )
            if rt is not None:
                session = ctx.session
                rt.subscription_manager.subscribe_session(_session_key(session), uri_str, session)
            return mcp_types.EmptyResult()

        async def _handle_unsubscribe(
            ctx: Any,
            params: mcp_types.UnsubscribeRequestParams,
        ) -> mcp_types.EmptyResult:
            rt = get_current_runtime()
            if rt is not None:
                session = ctx.session
                rt.subscription_manager.unsubscribe(_session_key(session), str(params.uri))
            return mcp_types.EmptyResult()

        low_level.add_request_handler(
            "resources/subscribe",
            mcp_types.SubscribeRequestParams,
            _handle_subscribe,
        )
        low_level.add_request_handler(
            "resources/unsubscribe",
            mcp_types.UnsubscribeRequestParams,
            _handle_unsubscribe,
        )
