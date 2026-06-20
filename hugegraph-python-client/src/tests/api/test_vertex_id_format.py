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

from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace
from uuid import UUID

import pytest
from pyhugegraph.api.graph import GraphManager
from pyhugegraph.api.traverser import TraverserManager
from pyhugegraph.utils.id_format import format_vertex_id, format_vertex_id_path

pytestmark = [pytest.mark.unit]


class FakeSession:
    def __init__(self, responses=None):
        self.cfg = SimpleNamespace(graphspace=None, gs_supported=False)
        self.calls = []
        self.responses = list(responses or [])

    def request(self, path, method="GET", **kwargs):
        self.calls.append((path, method, kwargs))
        if self.responses:
            return self.responses.pop(0)
        return {}


@pytest.mark.parametrize(
    ("vertex_id", "expected"),
    [
        ("person:marko", '"person:marko"'),
        ('a"b\\c', '"a\\"b\\\\c"'),
        (123, "123"),
        (-(2**63), str(-(2**63))),
        (2**63 - 1, str(2**63 - 1)),
        (UUID("12345678-1234-5678-1234-567812345678"), 'U"12345678-1234-5678-1234-567812345678"'),
    ],
)
def test_format_vertex_id_matches_hugegraph_json_literal_contract(vertex_id, expected):
    assert format_vertex_id(vertex_id) == expected


def test_format_vertex_id_rejects_bool_even_though_bool_is_int():
    with pytest.raises(TypeError):
        format_vertex_id(True)


@pytest.mark.parametrize("vertex_id", [1.5, Decimal("1"), Fraction(1, 1), 1 + 0j, 2**63, -(2**63) - 1])
def test_format_vertex_id_rejects_non_java_long_numeric_values(vertex_id):
    with pytest.raises((TypeError, ValueError)):
        format_vertex_id(vertex_id)


def test_format_vertex_id_allows_none_only_when_requested():
    with pytest.raises(ValueError):
        format_vertex_id(None)
    assert format_vertex_id(None, allow_none=True) is None


def test_format_vertex_id_path_quotes_json_literal_as_one_url_segment():
    assert format_vertex_id_path("a/b?c#d&e") == "%22a%2Fb%3Fc%23d%26e%22"
    assert format_vertex_id_path(123) == "123"
    assert (
        format_vertex_id_path(UUID("12345678-1234-5678-1234-567812345678"))
        == "U%2212345678-1234-5678-1234-567812345678%22"
    )


def test_graph_vertex_path_formats_json_literal_ids():
    session = FakeSession(
        responses=[
            {"id": "person:marko", "label": "person", "properties": {}},
            {"id": 123, "label": "department", "properties": {}},
            {"id": "a/b?c#d&e", "label": "book", "properties": {}},
        ]
    )
    graph = GraphManager(session)

    graph.getVertexById("person:marko")
    graph.getVertexById(123)
    graph.getVertexById("a/b?c#d&e")

    assert session.calls[0][0] == "graph/vertices/%22person%3Amarko%22"
    assert session.calls[1][0] == "graph/vertices/123"
    assert session.calls[2][0] == "graph/vertices/%22a%2Fb%3Fc%23d%26e%22"


def test_graph_edge_page_formats_and_encodes_vertex_id_query():
    session = FakeSession(
        responses=[
            {"edges": [], "page": None},
            {"edges": [], "page": None},
        ]
    )
    graph = GraphManager(session)

    graph.getEdgeByPage("knows", "person:marko", "OUT")
    graph.getEdgeByPage("knows", 123, "OUT")

    assert session.calls[0][0] == "graph/edges?vertex_id=%22person%3Amarko%22&direction=OUT&label=knows&page"
    assert session.calls[1][0] == "graph/edges?vertex_id=123&direction=OUT&label=knows&page"


def test_graph_vertices_by_id_formats_repeated_json_literal_query_params():
    session = FakeSession(
        responses=[
            {
                "vertices": [
                    {"id": 123},
                    {"id": "person:marko"},
                    {"id": "a&b"},
                ]
            }
        ]
    )
    graph = GraphManager(session)

    vertices = graph.getVerticesById([123, "person:marko", "a&b"])

    assert [vertex.id for vertex in vertices] == [123, "person:marko", "a&b"]
    assert session.calls[0][0] == "traversers/vertices?ids=123&ids=%22person%3Amarko%22&ids=%22a%26b%22"


def test_traverser_formats_vertex_id_query_params():
    session = FakeSession(
        responses=[
            {"same_neighbors": []},
            {"path": []},
            {"vertices": []},
        ]
    )
    traverser = TraverserManager(session)

    traverser.same_neighbors("person:marko", 456)
    traverser.shortest_path(123, "person:josh", 3)
    traverser.k_out(123, 2)

    assert session.calls[0][0] == "traversers/sameneighbors?vertex=%22person%3Amarko%22&other=456"
    assert session.calls[1][0] == "traversers/shortestpath?source=123&target=%22person%3Ajosh%22&max_depth=3"
    assert session.calls[2][0] == "traversers/kout?source=123&max_depth=2"
