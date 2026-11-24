# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Controlled graph/vector/hybrid evidence retriever."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

VALID_RETRIEVAL_MODES = frozenset({"graph", "vector", "hybrid"})


@dataclass(frozen=True)
class RetrievalContext:
    """Scoped retrieval request context carrying target and actor provenance."""

    query: str
    mode: str = "hybrid"
    top_k: int = 10
    seed_ids: tuple[Any, ...] = ()
    graph_target: dict[str, Any] | None = None
    actor_principal: str | None = None
    route_alias: str | None = None


def _serialize_vertex(vertex: Any) -> Any:
    if isinstance(vertex, dict):
        return vertex
    if hasattr(vertex, "to_dict") and callable(vertex.to_dict):
        return vertex.to_dict()
    if hasattr(vertex, "id") and hasattr(vertex, "properties"):
        raw_props = getattr(vertex, "properties", None)
        if callable(raw_props):
            raw_props = raw_props()
        props = dict(raw_props) if isinstance(raw_props, dict) else {}
        return {
            "id": getattr(vertex, "id", None),
            "label": getattr(vertex, "label", None),
            "properties": props,
        }
    return str(vertex)


def retrieve_evidence_context(
    *,
    query: str,
    mode: str,
    top_k: int,
    seed_ids: list[Any] | None,
    graph_target: dict[str, Any],
    graph_api: Any | None = None,
    traverser_api: Any | None = None,
    vector_search_fn: Callable[[str, int], list[Any]] | None = None,
    vid_index_meta: dict[str, Any] | None = None,
    context: RetrievalContext | None = None,
) -> dict[str, Any]:
    """Retrieve bounded, provenance-tagged evidence without Gremlin generation or LLM synthesis."""

    if context is not None:
        query = context.query
        mode = context.mode
        top_k = context.top_k
        seed_ids = list(context.seed_ids) if context.seed_ids else seed_ids
        if context.graph_target is not None:
            graph_target = dict(context.graph_target)

    if mode not in VALID_RETRIEVAL_MODES:
        raise ValueError(f"Unsupported retrieval mode: {mode!r}")

    meta = dict(vid_index_meta or {})
    index_generation = meta.get("index_generation")
    refreshed_at = meta.get("refreshed_at")
    coverage_status = meta.get("coverage_status") or ("ready" if index_generation else "missing")
    if mode in {"vector", "hybrid"} and vector_search_fn is None:
        coverage_status = "missing"

    evidence: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    candidate_vids: list[Any] = list(seed_ids or [])
    partial_errors: list[dict[str, Any]] = []
    graph_exceptions: list[Exception] = []

    if mode in {"vector", "hybrid"} and vector_search_fn is not None and query.strip():
        vector_vids = vector_search_fn(query.strip(), top_k)
        for rank, vid in enumerate(vector_vids, start=1):
            key = f"vertex:{vid!r}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            if vid not in candidate_vids:
                candidate_vids.append(vid)
            evidence.append(
                {
                    "evidence_id": key,
                    "kind": "vector_vid",
                    "graph_target": graph_target,
                    "vid": vid,
                    "source_rank": rank,
                    "index_generation": index_generation,
                    "refreshed_at": refreshed_at,
                    "coverage_status": coverage_status,
                }
            )

    if mode in {"graph", "hybrid"} and candidate_vids:
        bounded_seeds = candidate_vids[:top_k]
        if graph_api is not None and hasattr(graph_api, "get_vertices_by_id"):
            try:
                vertices = graph_api.get_vertices_by_id(bounded_seeds) or []
            except Exception as exc:  # pylint: disable=broad-except
                log.warning("Failed to fetch vertices by id for seeds=%s: %s", bounded_seeds, exc)
                graph_exceptions.append(exc)
                partial_errors.append(
                    {
                        "stage": "graph_vertices",
                        "error_type": type(exc).__name__,
                        "count": len(bounded_seeds),
                    }
                )
                vertices = []
            for rank, vertex in enumerate(vertices, start=1):
                serialized_vertex = _serialize_vertex(vertex)
                vid = serialized_vertex.get("id") if isinstance(serialized_vertex, dict) else serialized_vertex
                key = f"graph_vertex:{vid!r}"
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                evidence.append(
                    {
                        "evidence_id": key,
                        "kind": "graph_vertex",
                        "graph_target": graph_target,
                        "vertex": serialized_vertex,
                        "source_rank": rank,
                        "index_generation": index_generation if mode == "hybrid" else None,
                        "refreshed_at": refreshed_at if mode == "hybrid" else None,
                        "coverage_status": coverage_status if mode == "hybrid" else "live_graph",
                    }
                )
        if traverser_api is not None and hasattr(traverser_api, "k_neighbor"):
            for seed in bounded_seeds[: min(3, len(bounded_seeds))]:
                try:
                    neighbors_raw = traverser_api.k_neighbor(seed, 1, direction="BOTH", max_degree=16, limit=top_k)
                except Exception as exc:  # pylint: disable=broad-except
                    log.warning("k_neighbor lookup failed for seed=%r: %s", seed, exc)
                    graph_exceptions.append(exc)
                    partial_errors.append(
                        {
                            "stage": "graph_neighborhood",
                            "seed_id": seed,
                            "error_type": type(exc).__name__,
                            "count": 1,
                        }
                    )
                    continue
                neighbor_items = (
                    neighbors_raw.get("vertices") or neighbors_raw.get("ids") or []
                    if isinstance(neighbors_raw, dict)
                    else []
                )
                key = f"neighbors:{seed!r}"
                if key not in seen_ids:
                    seen_ids.add(key)
                    evidence.append(
                        {
                            "evidence_id": key,
                            "kind": "graph_neighborhood",
                            "graph_target": graph_target,
                            "seed_id": seed,
                            "neighbors": list(neighbor_items)[:top_k],
                            "source_rank": len(evidence) + 1,
                            "index_generation": index_generation if mode == "hybrid" else None,
                            "refreshed_at": refreshed_at if mode == "hybrid" else None,
                            "coverage_status": coverage_status if mode == "hybrid" else "live_graph",
                        }
                    )

    if mode == "graph" and graph_exceptions and not evidence:
        raise graph_exceptions[0]

    max_evidence = top_k * 3 if mode == "hybrid" else top_k
    result: dict[str, Any] = {
        "mode": mode,
        "evidence": evidence[:max_evidence],
        "index_generation": index_generation,
        "refreshed_at": refreshed_at,
        "coverage_status": coverage_status,
    }
    if partial_errors:
        result["partial_errors"] = partial_errors
    if context is not None:
        result["actor_principal"] = context.actor_principal
        result["route_alias"] = context.route_alias
    return result
