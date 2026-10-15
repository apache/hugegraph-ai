#  Licensed to the Apache Software Foundation (ASF) under one or more
#  contributor license agreements.  See the NOTICE file distributed with
#  this work for additional information regarding copyright ownership.
#  The ASF licenses this file to You under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance with
#  the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from types import SimpleNamespace

from hugegraph_llm.nodes.hugegraph_node.graph_query_node import GraphQueryNode
from tests.utils.mock import FakeGremlinEndpoint


def _graph_query_node(endpoint):
    node = GraphQueryNode()
    node._client = SimpleNamespace(gremlin=lambda: endpoint)
    node._schema = "Vertex properties: [name: person, properties: []]\nEdge properties: [name: knows, properties: []]\n"
    node._prop_to_match = None
    node._max_deep = 2
    node._max_items = 30
    return node


def test_subgraph_query_escapes_vertex_ids_with_apostrophes():
    # Fuzzy matching returns raw vertex ids from the vid index, so ids like 1:O'Brien reach the node unchanged.
    endpoint = FakeGremlinEndpoint({"1:O'Brien": {"name": "O'Brien"}})
    node = _graph_query_node(endpoint)

    result = node._subgraph_query({"match_vids": ["1:O'Brien"]})

    assert result["graph_result"] == ["1:O'Brien{name: O'Brien}"]
    assert len(endpoint.scripts) == 2
    assert all("'1:O\\'Brien'" in script for script in endpoint.scripts)


def test_subgraph_query_keeps_numeric_vertex_ids_numeric():
    # Graphs with numeric ids store ints in the vid index; HugeGraph treats 123 and '123' as different ids.
    endpoint = FakeGremlinEndpoint({123: {"name": "Tom Hanks"}})
    node = _graph_query_node(endpoint)

    result = node._subgraph_query({"match_vids": [123]})

    assert result["graph_result"] == ["123{name: Tom Hanks}"]
    assert [script.split(")", 1)[0] for script in endpoint.scripts] == ["g.V(123", "g.V(123"]
