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

from hugegraph_llm.operators.hugegraph_op.fetch_graph_data import FetchGraphData
from hugegraph_llm.retrieval import retrieve_evidence_context


def test_fetch_all_vertex_ids_detects_duplicate_page_token():
    class _GraphAPI:
        def __init__(self) -> None:
            self.calls = 0

        def list_vertices(self, limit=1000, page=""):
            self.calls += 1
            if self.calls == 1:
                return {"vertices": [{"id": "v1"}], "page": "tok-1"}
            return {"vertices": [{"id": "v2"}], "page": "tok-1"}

    class _Client:
        def graph(self):
            return _GraphAPI()

    vids, complete, reason = FetchGraphData(_Client()).fetch_all_vertex_ids_with_status()
    assert vids == ["v1", "v2"]
    assert complete is False
    assert reason == "duplicate_page_token"


def test_retrieve_evidence_context_hybrid_without_gremlin_generation():
    class _GraphAPI:
        def get_vertices_by_id(self, ids):
            return [{"id": vid, "label": "person", "properties": {"name": f"n-{vid}"}} for vid in ids]

    class _TraverserAPI:
        def k_neighbor(self, source_id, max_depth, **kwargs):
            return {"vertices": ["v-neighbor-1"]}

    res = retrieve_evidence_context(
        query="marko",
        mode="hybrid",
        top_k=5,
        seed_ids=None,
        graph_target={"graph": "hugegraph", "graphspace": "DEFAULT"},
        graph_api=_GraphAPI(),
        traverser_api=_TraverserAPI(),
        vector_search_fn=lambda q, k: ["1:marko"],
        vid_index_meta={"index_generation": 3, "refreshed_at": 1700000000},
    )
    assert res["mode"] == "hybrid"
    assert res["index_generation"] == 3
    assert any(item["kind"] == "vector_vid" for item in res["evidence"])
    assert any(item["kind"] == "graph_vertex" for item in res["evidence"])
    assert any(item["kind"] == "graph_neighborhood" for item in res["evidence"])
