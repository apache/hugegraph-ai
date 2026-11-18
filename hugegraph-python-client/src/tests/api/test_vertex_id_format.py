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

import json
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace
from uuid import UUID

import pytest
import requests
from pyhugegraph.api.graph import GraphManager
from pyhugegraph.api.traverser import TraverserManager
from pyhugegraph.utils.huge_requests import HGraphSession
from pyhugegraph.utils.id_format import (
    format_edge_id_path,
    format_vertex_id,
    format_vertex_id_path,
)

pytestmark = [pytest.mark.unit]


class RecordingHTTP(requests.Session):
    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)
        self.requests = []

    def send(self, request, **kwargs):
        self.requests.append(request)
        response = requests.Response()
        response.status_code = 200
        response.request = request
        response._content = json.dumps(self.responses.pop(0) if self.responses else {}).encode()
        response.headers["Content-Type"] = "application/json"
        return response


class FakeSession(HGraphSession):
    """Run the production serializer, URL resolver and requests preparation."""

    def __init__(self, responses=None):
        self.http = RecordingHTTP(responses or [])
        cfg = SimpleNamespace(
            url="http://localhost",
            graph_name="g",
            graphspace=None,
            gs_supported=False,
            username="admin",
            password="pwd",
            timeout=(0.5, 15),
        )
        super().__init__(cfg, session=self.http)

    @property
    def calls(self):
        return [(request.url.split("/graphs/g/", 1)[1], request.method, {}) for request in self.http.requests]


@pytest.mark.parametrize(
    ("vertex_id", "expected"),
    [
        ("person:marko", '"person:marko"'),
        ("1:张三", '"1:张三"'),
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


def test_format_edge_id_path_quotes_edge_id_as_one_url_segment():
    assert format_edge_id_path("S1:alice>11>knows>S2:bob") == "S1%3Aalice%3E11%3Eknows%3ES2%3Abob"


def test_graph_vertex_path_formats_json_literal_ids():
    session = FakeSession(
        responses=[
            {"id": "person:marko", "label": "person", "properties": {}},
            {"id": 123, "label": "department", "properties": {}},
            {"id": "a/b?c#d&e", "label": "book", "properties": {}},
        ]
    )
    graph = GraphManager(session)

    graph.get_vertex_by_id("person:marko")
    graph.get_vertex_by_id(123)
    graph.get_vertex_by_id("a/b?c#d&e")

    assert session.calls[0][0] == "graph/vertices/%22person%3Amarko%22"
    assert session.calls[1][0] == "graph/vertices/123"
    assert session.calls[2][0] == "graph/vertices/%22a%2Fb%3Fc%23d%26e%22"


def test_graph_vertex_path_sends_non_ascii_ids_as_utf8():
    vertex_id = "1:张三"
    session = FakeSession(
        responses=[
            {"id": vertex_id, "label": "person", "properties": {}},
            {"id": vertex_id, "label": "person", "properties": {"city": "Beijing"}},
            {},
            {"vertices": [{"id": vertex_id}]},
        ]
    )
    graph = GraphManager(session)

    graph.get_vertex_by_id(vertex_id)
    graph.append_vertex(vertex_id, {"city": "Beijing"})
    graph.remove_vertex_by_id(vertex_id)
    graph.get_vertices_by_id([vertex_id])

    # Percent-encoded UTF-8, not a JSON "\uXXXX" escape (%5Cu...), which the server rejects.
    encoded = "%221%3A%E5%BC%A0%E4%B8%89%22"
    assert session.calls[0][0] == f"graph/vertices/{encoded}"
    assert session.calls[1][0] == f"graph/vertices/{encoded}?action=append"
    assert session.calls[2][0] == f"graph/vertices/{encoded}"
    assert session.calls[3][0] == f"traversers/vertices?ids={encoded}"


def test_graph_edge_id_paths_encode_reserved_characters():
    edge_id = "S1:alice>11>knows>S2:bob"
    session = FakeSession(
        responses=[
            {"id": edge_id, "label": "knows", "properties": {}},
            {"id": edge_id, "label": "knows", "properties": {"city": "Beijing"}},
            {"id": edge_id, "label": "knows", "properties": {}},
            {},
        ]
    )
    graph = GraphManager(session)

    graph.get_edge_by_id(edge_id)
    graph.append_edge(edge_id, {"city": "Beijing"})
    graph.eliminate_edge(edge_id, {"city": "Beijing"})
    graph.remove_edge_by_id(edge_id)

    encoded = "S1%3Aalice%3E11%3Eknows%3ES2%3Abob"
    assert session.calls[0][0] == f"graph/edges/{encoded}"
    assert session.calls[1][0] == f"graph/edges/{encoded}?action=append"
    assert session.calls[1][1] == "PUT"
    assert session.calls[2][0] == f"graph/edges/{encoded}?action=eliminate"
    assert session.calls[2][1] == "PUT"
    assert session.calls[3][0] == f"graph/edges/{encoded}"
    assert session.calls[3][1] == "DELETE"


def test_graph_edge_page_formats_and_encodes_vertex_id_query():
    session = FakeSession(
        responses=[
            {"edges": [], "page": None},
            {"edges": [], "page": None},
        ]
    )
    graph = GraphManager(session)

    graph.get_edge_by_page("knows", "person:marko", "OUT")
    graph.get_edge_by_page("knows", 123, "OUT")

    assert session.calls[0][0] == "graph/edges?vertex_id=%22person%3Amarko%22&direction=OUT&label=knows&page="
    assert session.calls[1][0] == "graph/edges?vertex_id=123&direction=OUT&label=knows&page="


def test_graph_page_queries_urlencode_reserved_query_values():
    properties = {"name": "Alice & Bob", "city": "A/B?C#D"}
    session = FakeSession(
        responses=[
            {"vertices": [], "page": "next/1?x=y&z"},
            {"vertices": [], "page": "condition/next?x=1"},
            {"edges": [], "page": None},
        ]
    )
    graph = GraphManager(session)

    _, vertex_page = graph.get_vertex_by_page(
        label="person/team",
        limit=10,
        page="page/1?cursor=a&b",
        properties=properties,
    )
    _, condition_page = graph.get_vertex_by_condition_with_page(
        label="person/team",
        limit=5,
        page="page/2?cursor=c&d",
        properties=properties,
    )
    graph.get_edge_by_page(
        label="knows/team",
        vertex_id="person:alice/bob",
        direction="OUT/IN",
        limit=3,
        page="edge/page?x=1&y=2",
        properties=properties,
    )

    assert session.calls[0][0] == (
        "graph/vertices?"
        "label=person%2Fteam&"
        "properties=%7B%22name%22%3A+%22Alice+%26+Bob%22%2C+%22city%22%3A+%22A%2FB%3FC%23D%22%7D&"
        "page=page%2F1%3Fcursor%3Da%26b&limit=10"
    )
    assert session.calls[1][0] == (
        "graph/vertices?"
        "label=person%2Fteam&"
        "properties=%7B%22name%22%3A+%22Alice+%26+Bob%22%2C+%22city%22%3A+%22A%2FB%3FC%23D%22%7D&"
        "page=page%2F2%3Fcursor%3Dc%26d&limit=5"
    )
    assert session.calls[2][0] == (
        "graph/edges?"
        "vertex_id=%22person%3Aalice%2Fbob%22&direction=OUT%2FIN&label=knows%2Fteam&"
        "properties=%7B%22name%22%3A+%22Alice+%26+Bob%22%2C+%22city%22%3A+%22A%2FB%3FC%23D%22%7D&"
        "page=edge%2Fpage%3Fx%3D1%26y%3D2&limit=3"
    )
    assert vertex_page == "next/1?x=y&z"
    assert condition_page == "condition/next?x=1"


def test_graph_edges_by_id_encodes_repeated_edge_id_query_params():
    edge_id = "S1:alice>11>knows>S2:bob"
    session = FakeSession(responses=[{"edges": [{"id": edge_id}]}])
    graph = GraphManager(session)

    edges = graph.get_edges_by_id([edge_id])

    assert [edge.id for edge in edges] == [edge_id]
    assert session.calls[0][0] == "traversers/edges?ids=S1%3Aalice%3E11%3Eknows%3ES2%3Abob"


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

    vertices = graph.get_vertices_by_id([123, "person:marko", "a&b"])

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
