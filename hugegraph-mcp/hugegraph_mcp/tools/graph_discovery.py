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

"""Read-only HugeGraph multi-graph discovery tool."""

from __future__ import annotations

import json
from contextlib import nullcontext
from typing import Any

from pyhugegraph.client import PyHugeClient

from hugegraph_mcp.config import MCPConfig, get_effective_config
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.error_mapping import classify_hugegraph_exception
from hugegraph_mcp.hugegraph_client import build_hugegraph_client

MAX_GRAPHS_LIMIT = 100
MAX_GRAPHS_RESPONSE_BYTES = 1024 * 1024
GRAPHS_DEADLINE_SECONDS = 10.0


def _build_client(cfg: MCPConfig) -> Any:
    return build_hugegraph_client(
        cfg,
        client_cls=PyHugeClient,
        request_timeout_seconds=min(cfg.read_timeout_seconds, GRAPHS_DEADLINE_SECONDS),
    )


def list_graphs(*, prefix: str | None = None, limit: int = 50) -> dict[str, Any]:
    """List HugeGraph graphs in the configured graphspace with prefix filtering."""
    cfg = get_effective_config()
    hard_limit = max(1, min(MAX_GRAPHS_LIMIT, cfg.max_result_items))
    if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= hard_limit):
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"limit must be an integer between 1 and {hard_limit}.",
            details={"reason": "budget_exceeded", "field": "limit", "max": hard_limit},
        )
    if prefix is not None and not isinstance(prefix, str):
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "prefix must be a string when provided.",
            details={"reason": "invalid_prefix"},
        )

    try:
        client = _build_client(cfg)
        sess = getattr(client, "session", None) or getattr(client, "_session", None)
        guard = (
            sess.request_guard(
                max_response_bytes=max(1, min(MAX_GRAPHS_RESPONSE_BYTES, cfg.max_result_bytes)),
                deadline_seconds=GRAPHS_DEADLINE_SECONDS,
                retries=False,
            )
            if sess is not None and hasattr(sess, "request_guard")
            else nullcontext()
        )
        with guard:
            raw_text = client.graphs().get_all_graphs()
    except Exception as exc:
        classified = classify_hugegraph_exception(exc)
        return envelope_err(
            classified.error_type,
            f"Failed to list graphs: {exc}",
            suggestion=classified.suggestion,
            retryable=classified.retryable,
            details={"reason": classified.reason},
        )

    try:
        parsed = json.loads(raw_text) if isinstance(raw_text, str) else raw_text
    except ValueError as exc:
        return envelope_err(
            ErrorType.SERVER_ERROR,
            f"Failed to parse graphs response JSON: {exc}",
            details={"reason": "invalid_graphs_response"},
        )

    if not isinstance(parsed, dict) or not isinstance(parsed.get("graphs"), list):
        return envelope_err(
            ErrorType.SERVER_ERROR,
            "HugeGraph graphs response must be a JSON object with a 'graphs' list.",
            details={"reason": "invalid_graphs_response"},
        )

    graphs = [g for g in parsed["graphs"] if isinstance(g, str)]
    if len(graphs) != len(parsed["graphs"]):
        return envelope_err(
            ErrorType.SERVER_ERROR,
            "HugeGraph graphs response contained non-string graph names.",
            details={"reason": "invalid_graphs_response"},
        )

    if prefix:
        graphs = [g for g in graphs if g.startswith(prefix)]

    truncated = len(graphs) > limit
    return envelope_ok(
        {
            "graphs": graphs[:limit],
            "count": min(len(graphs), limit),
            "total_matched": len(graphs),
            "truncated": truncated,
            "graphspace": cfg.graphspace or "DEFAULT",
        }
    )
