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

from unittest.mock import Mock

import pytest

from hugegraph_llm.retrieval import retrieve_evidence_context

pytestmark = [pytest.mark.unit]


def test_graph_mode_timeout_raises_instead_of_returning_success_empty():
    graph_api = Mock()
    graph_api.get_vertices_by_id.side_effect = TimeoutError("vertex lookup timed out")
    traverser_api = Mock()
    traverser_api.k_neighbor.side_effect = TimeoutError("neighbor lookup timed out")

    with pytest.raises(TimeoutError):
        retrieve_evidence_context(
            query="",
            mode="graph",
            top_k=5,
            seed_ids=["1:alice"],
            graph_target={"graph": "hugegraph", "graphspace": "DEFAULT"},
            graph_api=graph_api,
            traverser_api=traverser_api,
        )


def test_hybrid_mode_surfaces_partial_errors_explicitly():
    graph_api = Mock()
    graph_api.get_vertices_by_id.side_effect = TimeoutError("graph vertices timed out token=secret123")
    traverser_api = Mock()
    traverser_api.k_neighbor.side_effect = RuntimeError("traverser unavailable pwd=supersecret")

    result = retrieve_evidence_context(
        query="alice",
        mode="hybrid",
        top_k=5,
        seed_ids=None,
        graph_target={"graph": "hugegraph", "graphspace": "DEFAULT"},
        graph_api=graph_api,
        traverser_api=traverser_api,
        vector_search_fn=lambda _q, _k: ["1:alice"],
        vid_index_meta={"index_generation": 3, "refreshed_at": "2026-11-18T00:00:00Z"},
    )

    assert result["mode"] == "hybrid"
    assert [item["vid"] for item in result["evidence"]] == ["1:alice"]
    assert result["partial_errors"] == [
        {"stage": "graph_vertices", "error_type": "TimeoutError", "count": 1},
        {"stage": "graph_neighborhood", "seed_id": "1:alice", "error_type": "RuntimeError", "count": 1},
    ]
    assert "secret123" not in repr(result["partial_errors"])
    assert "supersecret" not in repr(result["partial_errors"])
