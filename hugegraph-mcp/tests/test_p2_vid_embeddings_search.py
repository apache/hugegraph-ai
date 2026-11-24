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

"""Unit tests for Phase P2: VID embedding search & refresh reliability."""

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import Mock

from fastmcp import Client

from hugegraph_mcp import server
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.tools.search_vid_embeddings import search_vid_embeddings


def _cfg(*, allow_ai: bool = True) -> MCPConfig:
    return MCPConfig(
        url="http://127.0.0.1:8080",
        graph="hugegraph",
        graphspace="DEFAULT",
        allow_ai=allow_ai,
        ai_url="http://127.0.0.1:8002",
        readonly=True,
    )


def test_search_vid_embeddings_validates_inputs():
    cfg = _cfg(allow_ai=True)
    for bad_query in ("", "   ", 123, "x" * 501):
        res = search_vid_embeddings(bad_query, cfg=cfg)  # type: ignore[arg-type]
        assert res["ok"] is False
        assert res["error"]["type"] == "VALIDATION_ERROR"

    for bad_top_k in (0, -1, 51, True, "5"):
        res = search_vid_embeddings("alice", top_k=bad_top_k, cfg=cfg)  # type: ignore[arg-type]
        assert res["ok"] is False
        assert res["error"]["type"] == "VALIDATION_ERROR"


def test_search_vid_embeddings_requires_allow_ai():
    res = search_vid_embeddings("alice", cfg=_cfg(allow_ai=False))
    assert res["ok"] is False
    assert res["error"]["type"] == "FEATURE_DISABLED"


def test_search_vid_embeddings_maps_404_and_target_mismatch(monkeypatch):
    monkeypatch.setattr(
        "hugegraph_mcp.tools.search_vid_embeddings.post",
        lambda *_a, **_k: {
            "ok": False,
            "error": {"type": "SERVER_ERROR", "message": "not found", "details": {"status_code": 404}},
        },
    )
    res = search_vid_embeddings("alice", cfg=_cfg())
    assert res["ok"] is False
    assert res["error"]["type"] == "FEATURE_DISABLED"

    monkeypatch.setattr(
        "hugegraph_mcp.tools.search_vid_embeddings.post",
        lambda *_a, **_k: {
            "ok": True,
            "data": {
                "ok": True,
                "data": {
                    "vids": ["1:alice"],
                    "graph": "other_graph",
                    "graphspace": "DEFAULT",
                },
            },
        },
    )
    mismatch = search_vid_embeddings("alice", cfg=_cfg())
    assert mismatch["ok"] is False
    assert mismatch["error"]["type"] == "VALIDATION_ERROR"


def test_search_vid_embeddings_returns_ranked_vids_and_tool_works(monkeypatch):
    captured = {}

    def _fake_post(path, *, cfg, json):
        captured["path"] = path
        captured["json"] = json
        return {
            "ok": True,
            "data": {
                "ok": True,
                "data": {
                    "vids": ["1:alice", "1:alicia", "1:bob"],
                    "index_generation": 3,
                    "refreshed_at": "2026-11-14T15:00:00+00:00",
                    "graph": "hugegraph",
                    "graphspace": "DEFAULT",
                },
            },
        }

    monkeypatch.setattr("hugegraph_mcp.tools.search_vid_embeddings.post", _fake_post)
    res = search_vid_embeddings("  alice  ", top_k=2, cfg=_cfg())
    assert res["ok"] is True
    assert captured["path"] == "/v1/vid-embeddings/search"
    assert captured["json"] == {
        "query": "alice",
        "top_k": 2,
        "expected_graph": "hugegraph",
        "expected_graphspace": "DEFAULT",
    }
    assert res["data"]["vids"] == ["1:alice", "1:alicia"]
    assert res["data"]["count"] == 2
    assert res["data"]["index_generation"] == 3
    assert res["data"]["refreshed_at"] == "2026-11-14T15:00:00+00:00"
    assert "scores" not in res["data"]

    async def _call():
        async with Client(server.mcp) as client:
            return (await client.call_tool("search_vid_embeddings_tool", {"query": "alice", "top_k": 2})).data

    monkeypatch.setenv("HUGEGRAPH_MCP_ALLOW_AI", "true")
    tool_res = asyncio.run(_call())
    assert tool_res["ok"] is True
    assert tool_res["data"]["vids"] == ["1:alice", "1:alicia"]


def test_fetch_graph_data_paginates_all_vertex_ids():
    fetch_path = (
        Path(__file__).resolve().parents[2]
        / "hugegraph-llm"
        / "src"
        / "hugegraph_llm"
        / "operators"
        / "hugegraph_op"
        / "fetch_graph_data.py"
    )
    spec = importlib.util.spec_from_file_location("test_fetch_graph_data_mod", fetch_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    pages = [
        {"vertices": [{"id": f"1:v{i}"} for i in range(3)], "page": "p2"},
        {"vertices": [{"id": f"1:v{i}"} for i in range(3, 5)], "page": None},
    ]
    mock_graph = Mock()
    mock_graph.graph.return_value.list_vertices.side_effect = pages
    fetcher = mod.FetchGraphData(mock_graph)
    summary = fetcher.run({}, fetch_all_vids=True)
    assert summary["vertex_num"] == 5
    assert summary["vertices"] == ["1:v0", "1:v1", "1:v2", "1:v3", "1:v4"]
    assert mock_graph.graph.return_value.list_vertices.call_count == 2
    assert mock_graph.graph.return_value.list_vertices.call_args_list[0].kwargs["page"] == ""
    assert mock_graph.graph.return_value.list_vertices.call_args_list[1].kwargs["page"] == "p2"
