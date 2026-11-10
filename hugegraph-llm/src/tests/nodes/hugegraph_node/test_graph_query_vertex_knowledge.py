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

from hugegraph_llm.nodes.hugegraph_node.graph_query_node import GraphQueryNode

ALICE_PATH = "A{name: alice}--[knows]-->B{name: bob}"


def _vertex(vid, **props):
    return {"label": "person", "id": vid, "props": props}


def _edge(out_v, in_v, label="knows", **props):
    return {"label": label, "inV": in_v, "outV": out_v, "props": props}


def _path(*objects):
    return {"objects": list(objects)}


def _alice_bob_path():
    return _path(_vertex("A", name="alice"), _edge("A", "B"), _vertex("B", name="bob"))


def test_same_vertex_dedups_between_path_and_vertex_query():
    node = GraphQueryNode()
    vertex_knowledge = node._format_graph_from_vertex([{"id": "A", "properties": {"name": "alice", "role": ""}}])
    assert vertex_knowledge == {"A{name: alice}"}

    subgraph, vertex_degree_list, _ = node._format_graph_query_result([_alice_bob_path()])
    node._merge_vertex_knowledge(vertex_knowledge, subgraph, vertex_degree_list)

    assert subgraph == {ALICE_PATH}
    assert vertex_degree_list[0] == {"A{name: alice}"}
    assert vertex_degree_list[1] == {"B{name: bob}"}


def test_isolated_matched_vertex_stays_in_graph_result():
    node = GraphQueryNode()
    vertex_knowledge = node._format_graph_from_vertex(
        [
            {"id": "A", "properties": {"name": "alice"}},
            {"id": "Z", "properties": {"name": "zoe"}},
        ]
    )

    subgraph, vertex_degree_list, _ = node._format_graph_query_result([_alice_bob_path()])
    node._merge_vertex_knowledge(vertex_knowledge, subgraph, vertex_degree_list)

    assert subgraph == {ALICE_PATH, "Z{name: zoe}"}
    assert vertex_degree_list[0] == {"A{name: alice}", "Z{name: zoe}"}


def test_covered_matched_vertex_does_not_add_standalone_entry():
    node = GraphQueryNode()
    vertex_knowledge = node._format_graph_from_vertex([{"id": "A", "properties": {"name": "alice"}}])

    subgraph, vertex_degree_list, _ = node._format_graph_query_result([_alice_bob_path()])
    node._merge_vertex_knowledge(vertex_knowledge, subgraph, vertex_degree_list)

    assert subgraph == {ALICE_PATH}
    assert vertex_degree_list[0] == {"A{name: alice}"}


def test_without_paths_all_matched_vertices_become_knowledge():
    node = GraphQueryNode()
    vertex_knowledge = node._format_graph_from_vertex([{"id": "A", "properties": {"name": "alice"}}])

    subgraph, vertex_degree_list, _ = node._format_graph_query_result([])
    node._merge_vertex_knowledge(vertex_knowledge, subgraph, vertex_degree_list)

    assert subgraph == vertex_knowledge
    assert vertex_degree_list == [{"A{name: alice}"}]
