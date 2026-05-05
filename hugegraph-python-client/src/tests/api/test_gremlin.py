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
from unittest import mock

import pytest
from pyhugegraph.utils.exceptions import NotFoundError

from ..client_utils import ClientUtils


class TestGremlin(unittest.TestCase):
    client = None
    gremlin = None
    skip_gremlin_tests = False

    @classmethod
    def setUpClass(cls):
        cls.client = ClientUtils()
        cls.gremlin = cls.client.gremlin
        cls.client.clear_graph_all_data()
        cls.client.init_property_key()
        cls.client.init_vertex_label()
        cls.client.init_edge_label()

        try:
            # Skip only when the gremlin probe itself shows the endpoint is unavailable.
            cls.gremlin.exec("1 + 1")
        except NotFoundError as e:
            error_str = str(e)
            if any(
                marker in error_str
                for marker in ["404", "Not Found", "timed out", "Connection refused", "Gremlin can't get results"]
            ):
                cls.skip_gremlin_tests = True
            else:
                raise

    @classmethod
    def tearDownClass(cls):
        if not cls.skip_gremlin_tests:
            cls.client.clear_graph_all_data()

    def setUp(self):
        if self.skip_gremlin_tests:
            self.skipTest("Gremlin endpoint not available in this server")
        self.client.init_vertices()
        self.client.init_edges()

    def tearDown(self):
        pass

    def test_query_all_vertices(self):
        vertices = self.gremlin.exec("g.V()")
        lst = vertices.get("data", [])
        self.assertEqual(6, len(lst))

        self.gremlin.exec("g.V().drop()")
        vertices = self.gremlin.exec("g.V()")
        lst = vertices.get("data", [])
        self.assertEqual(0, len(lst))

    def test_query_all_edges(self):
        edges = self.gremlin.exec("g.E()")
        lst = edges.get("data", [])
        self.assertEqual(6, len(lst))

        self.gremlin.exec("g.E().drop()")
        edges = self.gremlin.exec("g.E()")
        lst = edges.get("data", [])
        self.assertEqual(0, len(lst))

    def test_primitive_object(self):
        result = self.gremlin.exec("1 + 2")
        result_set = result.get("data", [])
        self.assertEqual(1, len(result_set))

        data = result_set[0]
        self.assertTrue(isinstance(data, int))
        self.assertEqual(3, data)

    def test_empty_result_set(self):
        result = self.gremlin.exec("g.V().limit(0)")
        lst = result.get("data", [])
        self.assertEqual(0, len(lst))

    def test_invalid_gremlin(self):
        with pytest.raises(NotFoundError):
            self.assertTrue(self.gremlin.exec("g.V2()"))

    def test_security_operation(self):
        with pytest.raises(NotFoundError):
            self.assertTrue(self.gremlin.exec("System.exit(-1)"))


class TestGremlinSetupBehavior(unittest.TestCase):
    def tearDown(self):
        TestGremlin.client = None
        TestGremlin.gremlin = None
        TestGremlin.skip_gremlin_tests = False

    def test_set_up_class_reraises_non_probe_failures(self):
        with mock.patch(f"{TestGremlin.__module__}.ClientUtils") as client_utils_cls:
            client = client_utils_cls.return_value
            client.gremlin = mock.Mock()
            client.clear_graph_all_data.side_effect = RuntimeError("Connection refused during graph cleanup")

            with self.assertRaisesRegex(RuntimeError, "Connection refused during graph cleanup"):
                TestGremlin.setUpClass()

        self.assertFalse(TestGremlin.skip_gremlin_tests)

    def test_set_up_class_skips_when_gremlin_probe_returns_not_found(self):
        with mock.patch(f"{TestGremlin.__module__}.ClientUtils") as client_utils_cls:
            client = client_utils_cls.return_value
            client.gremlin = mock.Mock()
            client.gremlin.exec.side_effect = NotFoundError("404 Not Found")

            TestGremlin.setUpClass()

        self.assertTrue(TestGremlin.skip_gremlin_tests)
