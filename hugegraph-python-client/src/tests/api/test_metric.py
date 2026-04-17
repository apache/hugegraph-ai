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

from ..client_utils import ClientUtils


class TestMetricsManager(unittest.TestCase):
    client = None
    metrics = None

    @classmethod
    def setUpClass(cls):
        cls.client = ClientUtils()
        cls.metrics = cls.client.metrics
        cls.client.init_property_key()
        cls.client.init_vertex_label()
        cls.client.init_edge_label()
        cls.client.init_index_label()

    @classmethod
    def tearDownClass(cls):
        cls.client.clear_graph_all_data()

    def setUp(self):
        self.client.init_vertices()
        self.client.init_edges()

    def tearDown(self):
        pass

    def test_metrics_operations(self):
        all_basic_metrics = self.metrics.get_all_basic_metrics()
        self.assertEqual(len(all_basic_metrics), 5)

        gauges_metrics = self.metrics.get_gauges_metrics()
        self.assertIsInstance(gauges_metrics, dict)

        counters_metrics = self.metrics.get_counters_metrics()
        self.assertIsInstance(counters_metrics, dict)

        histograms_metrics = self.metrics.get_histograms_metrics()
        self.assertIsInstance(histograms_metrics, dict)

        meters_metrics = self.metrics.get_meters_metrics()
        self.assertIsInstance(meters_metrics, dict)

        timers_metrics = self.metrics.get_timers_metrics()
        self.assertIsInstance(timers_metrics, dict)

        system_metrics = self.metrics.get_system_metrics()
        self.assertIsInstance(system_metrics, dict)

        statistics = self.metrics.get_statistics_metrics()
        self.assertIsInstance(statistics, dict)

        backend_metrics = self.metrics.get_backend_metrics()
        self.assertGreater(len(backend_metrics["hugegraph"]), 1)
