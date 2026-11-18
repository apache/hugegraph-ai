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

"""Semantic VID embedding similarity search via HugeGraph-AI."""

from typing import Any

from hugegraph_mcp.config import MCPConfig, get_effective_config
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.hugegraph_ai_client import post
from hugegraph_mcp.tools.refresh_vid_embeddings import _unwrap_ai_payload

_MAX_QUERY_LENGTH = 500
_MAX_TOP_K = 50


def _effective_graphspace(graphspace: str | None) -> str:
    return graphspace.strip() if graphspace and graphspace.strip() else "DEFAULT"


def search_vid_embeddings(
    query: str,
    top_k: int = 10,
    *,
    cfg: MCPConfig | None = None,
) -> dict[str, Any]:
    """Search indexed vertex IDs semantically similar to ``query``."""
    if not isinstance(query, str) or not query.strip():
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "query must be a non-empty string.",
            suggestion="Provide a non-empty query string for semantic VID search.",
            retryable=False,
        )
    query_text = query.strip()
    if len(query_text) > _MAX_QUERY_LENGTH:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"query exceeds maximum length of {_MAX_QUERY_LENGTH} characters.",
            suggestion=f"Shorten query to at most {_MAX_QUERY_LENGTH} characters.",
            retryable=False,
        )

    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1 or top_k > _MAX_TOP_K:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"top_k must be an integer between 1 and {_MAX_TOP_K}.",
            suggestion=f"Pass top_k between 1 and {_MAX_TOP_K}.",
            retryable=False,
        )

    cfg = cfg or get_effective_config()
    ai_result = post(
        "/v1/vid-embeddings/search",
        cfg=cfg,
        json={
            "query": query_text,
            "top_k": top_k,
            "expected_graph": cfg.graph,
            "expected_graphspace": cfg.graphspace,
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
                "AI VID embedding search endpoint is unavailable.",
                suggestion="Upgrade HugeGraph-AI to support /v1/vid-embeddings/search.",
                details={"status_code": status_code},
            )
        return ai_result

    payload = _unwrap_ai_payload(ai_result.get("data"))
    if isinstance(payload, dict) and payload.get("ok") is False:
        return payload

    if not isinstance(payload, dict) or not isinstance(payload.get("vids"), list):
        return envelope_err(
            ErrorType.SERVER_ERROR,
            "HugeGraph-AI returned an invalid VID search payload.",
            suggestion="Check HugeGraph-AI service compatibility and logs.",
            retryable=False,
        )

    expected_graphspace = _effective_graphspace(cfg.graphspace)
    returned_graph = payload.get("graph")
    returned_graphspace = payload.get("graphspace")
    if (returned_graph is not None and returned_graph != cfg.graph) or (
        returned_graphspace is not None and _effective_graphspace(str(returned_graphspace)) != expected_graphspace
    ):
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "HugeGraph-AI returned search results for a different graph target.",
            suggestion="Ensure HugeGraph-AI and HugeGraph-MCP point to the same graph and graphspace.",
            retryable=False,
        )

    vids = payload["vids"][:top_k]
    return envelope_ok(
        {
            "vids": vids,
            "count": len(vids),
            "query": query_text,
            "top_k": top_k,
            "index_generation": payload.get("index_generation", 0),
            "refreshed_at": payload.get("refreshed_at"),
            "graph_target": {
                "graph": cfg.graph,
                "graphspace": expected_graphspace,
            },
        }
    )
