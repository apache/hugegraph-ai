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

from ..client_utils import ClientUtils

pytestmark = [pytest.mark.integration, pytest.mark.hugegraph]


class TestGraphsManager(unittest.TestCase):
    client = None
    graph = None

    @classmethod
    def setUpClass(cls):
        cls.client = ClientUtils()
        cls.graphs = cls.client.graphs
        cls.client.init_property_key()
        cls.client.init_vertex_label()
        cls.client.init_edge_label()
        cls.client.init_index_label()

    @classmethod
    def tearDownClass(cls):
        cls.client.clear_graph_all_data()

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_get_all_graphs(self):
        all_graphs = self.graphs.get_all_graphs()
        self.assertTrue("hugegraph" in all_graphs)

    def test_get_version(self):
        version = self.graphs.get_version()
        self.assertIsNotNone(version)

    def test_get_graph_info(self):
        graph_info = self.graphs.get_graph_info()
        self.assertTrue("backend" in graph_info)

    def test_get_graph_config(self):
        graph_config = self.graphs.get_graph_config()
        self.assertIsNotNone(graph_config)
