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

"""Controlled graph/vector/hybrid evidence retrieval via HugeGraph-AI."""

from __future__ import annotations

from typing import Any

from hugegraph_mcp.config import MCPConfig, get_effective_config
from hugegraph_mcp.cursor_store import (
    CursorError,
    compute_query_hash,
    get_default_cursor_store,
)
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.hugegraph_ai_client import post
from hugegraph_mcp.pagination import ItemTooLargeError, pack_paginated_items
from hugegraph_mcp.read_budget import ReadBudgetExceededError, read_budget_from_config
from hugegraph_mcp.runtime import get_current_actor
from hugegraph_mcp.stores.base import default_stdio_actor
from hugegraph_mcp.target_context import resolve_target_from_config
from hugegraph_mcp.tools.refresh_vid_embeddings import _unwrap_ai_payload

VALID_MODES = frozenset({"graph", "vector", "hybrid"})
_MAX_QUERY_LENGTH = 500
_MAX_TOP_K = 50


def retrieve_context(
    *,
    query: str = "",
    mode: str = "hybrid",
    top_k: int = 10,
    seed_ids: list[Any] | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
    cfg: MCPConfig | None = None,
) -> dict[str, Any]:
    """Retrieve bounded, provenance-tagged evidence for client-side reasoning."""

    if mode not in VALID_MODES:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"Unsupported mode: {mode!r}; expected graph, vector, or hybrid.",
            details={"mode": mode},
        )
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1 or top_k > _MAX_TOP_K:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"top_k must be an integer between 1 and {_MAX_TOP_K}.",
            details={"top_k": top_k},
        )
    query_text = query.strip() if isinstance(query, str) else ""
    if len(query_text) > _MAX_QUERY_LENGTH:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"query exceeds maximum length of {_MAX_QUERY_LENGTH} characters.",
        )
    if seed_ids is not None and not isinstance(seed_ids, list):
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "seed_ids must be a list when provided.",
            details={"seed_ids_type": type(seed_ids).__name__},
        )
    if page_size is not None and (isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1):
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "page_size must be a positive integer.",
            details={"page_size": page_size},
        )
    if mode == "graph" and not seed_ids:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "seed_ids is required for mode='graph'.",
            suggestion="Provide seed_ids or use mode='hybrid'/'vector' with a query.",
        )
    if mode in {"vector", "hybrid"} and not query_text:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"query is required for mode={mode!r}.",
        )

    effective_cfg = cfg or get_effective_config()
    actor = get_current_actor() or default_stdio_actor()
    resolved_target = resolve_target_from_config(effective_cfg)
    query_hash = compute_query_hash({"query": query_text, "mode": mode, "top_k": top_k, "seed_ids": seed_ids or []})
    store = get_default_cursor_store()
    max_items_cap = min(effective_cfg.max_result_items, top_k * 3) if mode == "hybrid" else top_k
    eff_page_size = min(page_size or max_items_cap, max_items_cap)
    budget = read_budget_from_config(effective_cfg, max_items=eff_page_size)

    if cursor is not None:
        try:
            record = store.consume(
                cursor,
                actor_key=actor.principal_key,
                target=resolved_target.as_tuple(),
                query_hash=query_hash,
                fields=None,
                route_version=resolved_target.route_version,
            )
        except CursorError as exc:
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                str(exc),
                details={"reason_code": exc.reason_code},
            )
        evidence_items = list(record.buffered_items)
        raw_gen = record.backend_next_page
        index_generation = int(raw_gen) if raw_gen is not None and raw_gen.isdigit() else raw_gen
        refreshed_at = None
        coverage_status = "snapshot"
    else:
        ai_result = post(
            "/v1/retrieve-context",
            cfg=effective_cfg,
            json={
                "query": query_text,
                "mode": mode,
                "top_k": top_k,
                "seed_ids": seed_ids,
                "expected_graph": effective_cfg.graph,
                "expected_graphspace": effective_cfg.graphspace,
            },
        )
        if not ai_result.get("ok"):
            error = ai_result.get("error") or {}
            status_code = (error.get("details") or {}).get("status_code")
            if status_code in {404, 405} and error.get("type") not in {
                "AUTHENTICATION_FAILED",
                "AUTHORIZATION_FAILED",
                "FEATURE_DISABLED",
            }:
                return envelope_err(
                    ErrorType.FEATURE_DISABLED,
                    "AI /v1/retrieve-context endpoint is unavailable.",
                    suggestion="Upgrade HugeGraph-AI to support /v1/retrieve-context.",
                    details={"status_code": status_code},
                )
            return ai_result

        payload = _unwrap_ai_payload(ai_result.get("data"))
        if isinstance(payload, dict) and payload.get("ok") is False:
            return payload
        if not isinstance(payload, dict) or not isinstance(payload.get("evidence"), list):
            return envelope_err(
                ErrorType.SERVER_ERROR,
                "HugeGraph-AI returned an invalid retrieve-context payload.",
            )
        evidence_items = list(payload["evidence"])
        index_generation = payload.get("index_generation")
        refreshed_at = payload.get("refreshed_at")
        coverage_status = payload.get("coverage_status")

    try:
        budget.ensure_available()
    except ReadBudgetExceededError as exc:
        return envelope_err(
            ErrorType.TIMEOUT,
            str(exc),
            retryable=True,
            details={"reason_code": exc.reason_code},
        )

    try:
        packed, overflow, byte_truncated = pack_paginated_items(
            evidence_items,
            max_items=eff_page_size,
            max_bytes=effective_cfg.max_result_bytes,
        )
    except ItemTooLargeError as exc:
        return envelope_err(ErrorType.VALIDATION_ERROR, str(exc), details={"reason_code": "SINGLE_ITEM_TOO_LARGE"})

    next_cursor: str | None = None
    if overflow:
        next_cursor = store.issue(
            actor_key=actor.principal_key,
            target=resolved_target.as_tuple(),
            query_hash=query_hash,
            fields=None,
            continuation_scope="snapshot",
            buffered_items=overflow,
            backend_next_page=str(index_generation) if index_generation is not None else None,
            exhausted_backend=True,
            route_version=resolved_target.route_version,
        )

    return envelope_ok(
        {
            "mode": mode,
            "evidence": packed,
            "count": len(packed),
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
            "truncated": byte_truncated,
            "index_generation": index_generation,
            "refreshed_at": refreshed_at,
            "coverage_status": coverage_status,
            "continuation_scope": "snapshot",
        }
    )
