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

import unittest

import pytest
from pyhugegraph.utils.exceptions import NotFoundError

from ..client_utils import ClientUtils

pytestmark = [pytest.mark.integration, pytest.mark.hugegraph]

# FIXME: isolate graph state per test case; current fixed primary-key fixtures
# and class-level cleanup make exact-count assertions order-dependent.


class TestGraphManager(unittest.TestCase):
    client = None
    graph = None

    @classmethod
    def setUpClass(cls):
        cls.client = ClientUtils()
        cls.graph = cls.client.graph
        cls.client.init_property_key()
        cls.client.init_vertex_label()
        cls.client.init_edge_label()
        cls.client.init_index_label()

    @classmethod
    def tearDownClass(cls):
        cls.client.clear_graph_all_data()

    def test_add_vertex(self):
        vertex = self.graph.add_vertex("person", {"name": "marko", "age": 29, "city": "Beijing"})
        self.assertIsNotNone(vertex)

    def test_add_vertices(self):
        vertices = self.graph.add_vertices(
            [
                ("person", {"name": "vadas", "age": 27, "city": "Hongkong"}),
                ("person", {"name": "marko", "age": 29, "city": "Beijing"}),
            ]
        )
        self.assertEqual(len(vertices), 2)

    def test_append_vertex(self):
        vertex = self.graph.add_vertex("person", {"name": "Alice", "age": 20})
        appended_vertex = self.graph.append_vertex(vertex.id, {"city": "Beijing"})
        self.assertEqual(appended_vertex.properties["city"], "Beijing")

    def test_append_vertex_with_number_id(self):
        vertex = self.graph.add_vertex("department", {"name": "DepartmentA", "headcount": 10, "floor": 1})
        appended_vertex = self.graph.append_vertex(vertex.id, {"headcount": 15})
        self.assertEqual(appended_vertex.properties["headcount"], 15)

    def test_eliminate_vertex(self):
        vertex = self.graph.add_vertex("person", {"name": "marko", "age": 29, "city": "Beijing"})
        self.graph.eliminate_vertex(vertex.id, {"city": "Beijing"})
        eliminated_vertex = self.graph.get_vertex_by_id(vertex.id)
        self.assertIsNone(eliminated_vertex.properties.get("city"))

    def test_eliminate_vertex_with_number_id(self):
        vertex = self.graph.add_vertex("department", {"name": "DepartmentA", "headcount": 10, "floor": 1})
        self.graph.eliminate_vertex(vertex.id, {"floor": 1})
        eliminated_vertex = self.graph.get_vertex_by_id(vertex.id)
        self.assertIsNone(eliminated_vertex.properties.get("floor"))

    def test_get_vertex_by_id(self):
        vertex = self.graph.add_vertex("person", {"name": "Alice", "age": 20})
        retrieved_vertex = self.graph.get_vertex_by_id(vertex.id)
        self.assertEqual(retrieved_vertex.id, vertex.id)

    def test_get_vertex_by_number_id(self):
        vertex = self.graph.add_vertex("department", {"name": "DepartmentA", "headcount": 10, "floor": 1})
        retrieved_vertex = self.graph.get_vertex_by_id(vertex.id)
        self.assertEqual(retrieved_vertex.id, vertex.id)

    def test_get_vertex_by_page(self):
        self.graph.add_vertex("person", {"name": "Alice", "age": 20})
        self.graph.add_vertex("person", {"name": "Bob", "age": 23})
        vertices, next_page = self.graph.get_vertex_by_page("person", 1)
        self.assertEqual(len(vertices), 1)
        self.assertIn(vertices[0].properties["name"], {"Alice", "Bob"})
        self.assertIsNotNone(next_page)

    def test_get_vertex_by_condition(self):
        self.graph.add_vertex("person", {"name": "Alice", "age": 25})
        self.graph.add_vertex("person", {"name": "Bob", "age": 30})
        vertices = self.graph.get_vertex_by_condition("person", properties={"age": "P.gt(29)"})
        self.assertEqual(len(vertices), 1)
        self.assertEqual(vertices[0].properties["name"], "Bob")

    def test_get_vertex_by_condition_with_page(self):
        self.graph.add_vertex("person", {"name": "Condition Page Alice", "age": 25})
        vertices, next_page = self.graph.get_vertex_by_condition_with_page(
            "person",
            limit=1,
            properties={"name": "Condition Page Alice"},
        )
        self.assertEqual(len(vertices), 1)
        self.assertEqual(vertices[0].properties["name"], "Condition Page Alice")
        self.assertIsNone(next_page)

    def test_remove_vertex_by_id(self):
        vertex = self.graph.add_vertex("person", {"name": "Alice", "age": 20})
        self.graph.remove_vertex_by_id(vertex.id)
        try:
            self.graph.get_vertex_by_id(vertex.id)
        except NotFoundError as e:
            self.assertTrue("Alice\\' does not exist" in str(e))

    def test_remove_vertex_by_number_id(self):
        vertex = self.graph.add_vertex("department", {"name": "DepartmentA", "headcount": 10, "floor": 1})
        self.graph.remove_vertex_by_id(vertex.id)
        try:
            self.graph.get_vertex_by_id(vertex.id)
        except NotFoundError as e:
            msg = f"\\'{vertex.id}\\' does not exist"
            self.assertTrue(msg in str(e))
        else:
            self.fail("Expected NotFoundError after removing numeric-id vertex")

    def test_add_edge(self):
        vertex1 = self.graph.add_vertex("person", {"name": "Alice", "age": 20})
        vertex2 = self.graph.add_vertex("person", {"name": "Bob", "age": 23})
        edge = self.graph.add_edge("knows", vertex1.id, vertex2.id, {"date": "2012-01-10"})
        self.assertIsNotNone(edge)

    def test_add_edges(self):
        vertex1 = self.graph.add_vertex("person", {"name": "Alice", "age": 20})
        vertex2 = self.graph.add_vertex("person", {"name": "Bob", "age": 23})

        vertices = self.graph.add_edges(
            [
                ("knows", vertex1.id, vertex2.id, "person", "person", {"date": "2012-01-10"}),
                ("knows", vertex2.id, vertex1.id, "person", "person", {"date": "2012-01-10"}),
            ]
        )
        self.assertEqual(len(vertices), 2)

    def test_append_edge(self):
        vertex1 = self.graph.add_vertex("person", {"name": "Alice", "age": 20})
        vertex2 = self.graph.add_vertex("person", {"name": "Bob", "age": 23})
        edge = self.graph.add_edge("knows", vertex1.id, vertex2.id, {"date": "2012-01-10"})
        appended_edge = self.graph.append_edge(edge.id, {"city": "Beijing"})
        self.assertEqual(appended_edge.properties["city"], "Beijing")

    def test_eliminate_edge(self):
        vertex1 = self.graph.add_vertex("person", {"name": "Alice", "age": 20})
        vertex2 = self.graph.add_vertex("person", {"name": "Bob", "age": 23})
        edge = self.graph.add_edge("knows", vertex1.id, vertex2.id, {"date": "2012-01-10"})
        self.graph.eliminate_edge(edge.id, {"city": "Beijing"})
        eliminated_edge = self.graph.get_edge_by_id(edge.id)
        self.assertIsNone(eliminated_edge.properties.get("city"))

    def test_get_edge_by_id(self):
        vertex1 = self.graph.add_vertex("person", {"name": "Alice", "age": 20})
        vertex2 = self.graph.add_vertex("person", {"name": "Bob", "age": 23})
        edge = self.graph.add_edge("knows", vertex1.id, vertex2.id, {"date": "2012-01-10"})
        retrieved_edge = self.graph.get_edge_by_id(edge.id)
        self.assertEqual(retrieved_edge.id, edge.id)

    def test_get_edge_by_page(self):
        vertex1 = self.graph.add_vertex("person", {"name": "Alice", "age": 20})
        vertex2 = self.graph.add_vertex("person", {"name": "Bob", "age": 23})
        self.graph.add_edge("knows", vertex1.id, vertex2.id, {"date": "2012-01-10"})
        self.graph.add_edge("knows", vertex2.id, vertex1.id, {"date": "2012-01-10"})
        edges, _ = self.graph.get_edge_by_page("knows")
        self.assertEqual(len(edges), 2)

    def test_remove_edge_by_id(self):
        vertex1 = self.graph.add_vertex("person", {"name": "Alice", "age": 20})
        vertex2 = self.graph.add_vertex("person", {"name": "Bob", "age": 23})
        edge = self.graph.add_edge("knows", vertex1.id, vertex2.id, {"date": "2012-01-10"})
        self.graph.remove_edge_by_id(edge.id)
        try:
            self.graph.get_edge_by_id(edge.id)
        except NotFoundError as e:
            self.assertTrue("does not exist" in str(e))

    def test_get_vertices_by_id(self):
        vertex1 = self.graph.add_vertex("person", {"name": "Alice", "age": 20})
        vertex2 = self.graph.add_vertex("person", {"name": "Bob", "age": 23})
        vertices = self.graph.get_vertices_by_id([vertex1.id, vertex2.id])
        self.assertEqual(len(vertices), 2)

    def test_number_id_query_and_traverser_paths(self):
        department1 = self.graph.add_vertex("department", {"name": "DepartmentA", "headcount": 10, "floor": 1})
        department2 = self.graph.add_vertex("department", {"name": "DepartmentB", "headcount": 20, "floor": 2})
        self.graph.add_edge("reports_to", department1.id, department2.id, {"date": "2026-06-20"})

        edges, _ = self.graph.get_edge_by_page("reports_to", department1.id, "OUT")
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].out_v, department1.id)
        self.assertEqual(edges[0].in_v, department2.id)

        vertices = self.graph.get_vertices_by_id([department1.id, department2.id])
        self.assertEqual({vertex.id for vertex in vertices}, {department1.id, department2.id})

        traverser_vertex = self.client.traverser.vertices(department1.id)
        self.assertEqual(traverser_vertex["vertices"][0]["id"], department1.id)

        k_out_result = self.client.traverser.k_out(department1.id, 1)
        self.assertIn(department2.id, k_out_result["vertices"])

    def test_get_edges_by_id(self):
        vertex1 = self.graph.add_vertex("person", {"name": "Alice", "age": 20})
        vertex2 = self.graph.add_vertex("person", {"name": "Bob", "age": 23})
        edge1 = self.graph.add_edge("knows", vertex1.id, vertex2.id, {"date": "2012-01-10"})
        edge2 = self.graph.add_edge("knows", vertex2.id, vertex1.id, {"date": "2012-01-10"})
        edges = self.graph.get_edges_by_id([edge1.id, edge2.id])
        self.assertEqual(len(edges), 2)


def test_graph_supports_primary_key_and_custom_string_id(client_utils):
    graph = client_utils.graph
    graph.add_vertex("person", {"name": "quality_marko", "age": 29, "city": "Beijing"})
    people = graph.get_vertex_by_condition(label="person", properties={"name": "quality_marko"}, limit=1)
    person = people[0]
    assert person.id is not None

    graph.add_vertex("book", {"name": "Quality Book", "price": 100}, id="quality-book-1")
    book = graph.get_vertex_by_id("quality-book-1")
    assert book.id == "quality-book-1"
    assert book.properties["name"] == "Quality Book"
