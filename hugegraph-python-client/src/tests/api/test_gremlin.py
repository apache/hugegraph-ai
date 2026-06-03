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

import os
import unittest
from unittest import mock

import pytest
from pyhugegraph.utils.exceptions import NotFoundError

from ..client_utils import ClientUtils

pytestmark = [pytest.mark.integration, pytest.mark.hugegraph]


class TestGremlin(unittest.TestCase):
    client = None
    gremlin = None

    @classmethod
    def setUpClass(cls):
        # To run these tests locally, start HugeGraph via Docker:
        #   docker run -d -p 8080:8080 hugegraph/hugegraph:latest
        #
        # To explicitly skip Gremlin tests in CI or locally, set:
        #   SKIP_GREMLIN_TESTS=true
        #
        # Do NOT add automatic skip logic based on connectivity probes.
        # Endpoint failures must surface as FAILED tests, not SKIPPED.
        if os.environ.get("SKIP_GREMLIN_TESTS", "").lower() == "true":
            raise unittest.SkipTest("Skipping Gremlin tests: SKIP_GREMLIN_TESTS=true")

        cls.client = ClientUtils()
        cls.gremlin = cls.client.gremlin
        cls.client.clear_graph_all_data()
        cls.client.init_property_key()
        cls.client.init_vertex_label()
        cls.client.init_edge_label()

    @classmethod
    def tearDownClass(cls):
        cls.client.clear_graph_all_data()

    def setUp(self):
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

    def test_set_up_class_reraises_non_probe_failures(self):
        with mock.patch(f"{TestGremlin.__module__}.ClientUtils") as client_utils_cls:
            client = client_utils_cls.return_value
            client.gremlin = mock.Mock()
            client.clear_graph_all_data.side_effect = RuntimeError("Connection refused during graph cleanup")

            with self.assertRaisesRegex(RuntimeError, "Connection refused during graph cleanup"):
                TestGremlin.setUpClass()

    def test_set_up_class_no_longer_probes_gremlin(self):
        # After removing the probe, setUpClass should NOT call gremlin.exec at all.
        with mock.patch(f"{TestGremlin.__module__}.ClientUtils") as client_utils_cls:
            client = client_utils_cls.return_value
            client.gremlin = mock.Mock()

            TestGremlin.setUpClass()

            client.gremlin.exec.assert_not_called()

    def test_set_up_class_skips_when_env_var_set(self):
        # Explicit opt-in skip via environment variable is supported.
        with mock.patch(f"{TestGremlin.__module__}.ClientUtils") as client_utils_cls:
            client = client_utils_cls.return_value
            client.gremlin = mock.Mock()
            with mock.patch.dict(os.environ, {"SKIP_GREMLIN_TESTS": "true"}), self.assertRaises(unittest.SkipTest):
                TestGremlin.setUpClass()


def test_gremlin_error_surface_is_explicit(client_utils):
    with pytest.raises(NotFoundError) as exc_info:
        client_utils.gremlin.exec("g.V2()")

    message = str(exc_info.value)
    assert "g.V2" in message or "No signature" in message or "NotFound" in message
