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

"""Unit tests for the batched neighbour-traversal gremlin exec in GraphQueryNode."""

import math
from unittest.mock import Mock

from hugegraph_llm.nodes.hugegraph_node.graph_query_node import (
    NEIGHBOR_QUERY_BATCH_SIZE,
    GraphQueryNode,
)

# A parseable schema so _extract_labels_from_schema does not hit the client.
_SCHEMA = "Vertex properties: label: name, id: uuid\nEdge properties: edge: source, target\nRelationships: []\n"


def _node(match_vids: list[str], exec_result: dict | None = None, exec_side_effect=None) -> GraphQueryNode:
    node = GraphQueryNode()
    node._client = Mock()
    if exec_side_effect is not None:
        node._client.gremlin.return_value.exec.side_effect = exec_side_effect
    else:
        node._client.gremlin.return_value.exec.return_value = exec_result or {"data": []}
    node._schema = _SCHEMA
    node._max_deep = 1
    node._max_items = 10
    node._prop_to_match = None  # id-to-match subgraph branch (per-vid loop)
    data_json = {"query": "some query", "match_vids": match_vids, "max_deep": 1, "max_items": 10}
    node.operator_schedule(data_json)
    return node


def test_neighbor_queries_are_batched_across_matched_vids():
    node = _node(["v1", "v2", "v3", "v4", "v5"])
    # vertex full-match exec (1) + one neighbour batch for 5 vids (1) = 2,
    # instead of 1 + 5 per-vid execs.
    assert node._client.gremlin().exec.call_count == 2


def test_neighbor_queries_batch_large_vid_set():
    vids = [f"v{i}" for i in range(1, 26)]
    node = _node(vids)
    # 1 vertex exec + one exec per batch, instead of 1 + 25 executions.
    expected = 1 + math.ceil(len(vids) / NEIGHBOR_QUERY_BATCH_SIZE)
    assert node._client.gremlin().exec.call_count == expected


def test_single_vid_keeps_one_vertex_and_one_neighbor_query():
    node = _node(["only-vid"])
    assert node._client.gremlin().exec.call_count == 2


def test_empty_match_vids_skips_query():
    node = _node([])
    assert node._client.gremlin().exec.call_count == 0


def test_batch_queries_split_vids_in_order():
    vids = [f"v{i}" for i in range(1, 13)]  # 12 vids -> batches of 10 + 2
    first_batch, second_batch = vids[:NEIGHBOR_QUERY_BATCH_SIZE], vids[NEIGHBOR_QUERY_BATCH_SIZE:]
    exec_calls: list[str] = []

    def exec_side_effect(gremlin):
        exec_calls.append(gremlin)
        return {"data": []}

    _node(vids, exec_side_effect=exec_side_effect)
    assert len(exec_calls) == 1 + math.ceil(len(vids) / NEIGHBOR_QUERY_BATCH_SIZE)
    # the full-vertex query is kept as-is, then one query per vid batch
    assert exec_calls[0].startswith(f"g.V({vids}).limit(8)")
    assert all(f"'{vid}'" in exec_calls[1] for vid in first_batch)
    assert all(f"'{vid}'" not in exec_calls[1] for vid in second_batch)
    assert all(f"'{vid}'" in exec_calls[2] for vid in second_batch)


def test_batches_concatenate_paths_in_vid_order(monkeypatch):
    vids = [f"v{i}" for i in range(1, 13)]
    captured_paths: list[list[str]] = []

    def fake_format(self, query_paths):
        captured_paths.append(list(query_paths))
        return set(), [], set()

    monkeypatch.setattr(GraphQueryNode, "_format_graph_query_result", fake_format)
    batches = iter([{"data": []}, {"data": ["p1", "p2"]}, {"data": ["p3"]}])
    _node(vids, exec_side_effect=lambda gremlin: next(batches))
    # batch results are appended in matched_vids order, so ordering is preserved
    assert captured_paths == [["p1", "p2", "p3"]]
