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

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import envelope_err, envelope_ok
from hugegraph_mcp.tools import retrieve_context


def test_retrieve_context_validates_inputs():
    bad_mode = retrieve_context.retrieve_context(query="marko", mode="invalid")
    assert bad_mode["ok"] is False
    assert bad_mode["error"]["type"] == "VALIDATION_ERROR"

    graph_without_seeds = retrieve_context.retrieve_context(mode="graph")
    assert graph_without_seeds["ok"] is False
    assert graph_without_seeds["error"]["type"] == "VALIDATION_ERROR"


def test_retrieve_context_404_maps_to_feature_disabled(monkeypatch):
    monkeypatch.setattr(
        retrieve_context,
        "post",
        lambda path, **kw: envelope_err("SERVER_ERROR", "Not Found", details={"status_code": 404}),
    )
    res = retrieve_context.retrieve_context(query="marko", mode="vector", cfg=MCPConfig(allow_ai=True))
    assert res["ok"] is False
    assert res["error"]["type"] == "FEATURE_DISABLED"


def test_retrieve_context_paginates_snapshot_and_preserves_generation(monkeypatch):
    calls = []

    def fake_post(path, **kw):
        calls.append(path)
        return envelope_ok(
            {
                "mode": "hybrid",
                "evidence": [
                    {"evidence_id": "v:1", "kind": "vector_vid", "vid": 1, "source_rank": 1},
                    {"evidence_id": "v:2", "kind": "vector_vid", "vid": "2", "source_rank": 2},
                    {"evidence_id": "v:3", "kind": "vector_vid", "vid": 3, "source_rank": 3},
                ],
                "index_generation": 7,
                "refreshed_at": 1700000000,
                "coverage_status": "ready",
            }
        )

    monkeypatch.setattr(retrieve_context, "post", fake_post)
    cfg = MCPConfig(allow_ai=True)

    p1 = retrieve_context.retrieve_context(query="marko", mode="hybrid", top_k=10, page_size=2, cfg=cfg)
    assert p1["ok"] is True
    assert [e["vid"] for e in p1["data"]["evidence"]] == [1, "2"]
    assert p1["data"]["has_more"] is True
    assert p1["data"]["index_generation"] == 7

    p2 = retrieve_context.retrieve_context(
        query="marko", mode="hybrid", top_k=10, page_size=2, cursor=p1["data"]["next_cursor"], cfg=cfg
    )
    assert p2["ok"] is True
    assert [e["vid"] for e in p2["data"]["evidence"]] == [3]
    assert p2["data"]["has_more"] is False
    assert p2["data"]["index_generation"] == 7
    assert len(calls) == 1
