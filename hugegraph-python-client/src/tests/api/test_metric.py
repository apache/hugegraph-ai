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

# Expected server-entry keys for RocksDB backend
# Captured from a real HugeGraph 1.7.0 server response at /metrics/backend
EXPECTED_ROCKSDB_SERVER_KEYS = {
    "mem_unit",
    "disk_unit",
    "mem_used",
    "mem_used_readable",
    "disk_usage",
    "disk_usage_readable",
    "block_cache_usage",
    "block_cache_pinned_usage",
    "block_cache_capacity",
    "estimate_table_readers_mem",
    "size_all_mem_tables",
    "cur_size_all_mem_tables",
    "estimate_live_data_size",
    "total_sst_files_size",
    "live_sst_files_size",
    "estimate_pending_compaction_bytes",
    "estimate_num_keys",
    "num_entries_active_mem_table",
    "num_entries_imm_mem_tables",
    "num_deletes_active_mem_table",
    "num_deletes_imm_mem_tables",
    "num_running_flushes",
    "mem_table_flush_pending",
    "num_running_compactions",
    "compaction_pending",
    "num_immutable_mem_table",
    "num_snapshots",
    "oldest_snapshot_time",
    "num_live_versions",
    "current_super_version_number",
}


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

        # HugeGraph 1.7.0 backend_metrics shape (top-level key may be "<cluster>-<graph>"):
        # { "<cluster>-<graph>": { "backend": str, "nodes": int, "cluster_id": str,
        #                          "servers": { "<server_name>": { <metrics> } } } }
        self.assertIsInstance(backend_metrics, dict, "backend_metrics should be a dict")
        self.assertTrue(backend_metrics, "backend_metrics should not be empty")

        # Select the graph entry deterministically using the configured graph name
        graph_name = self.client.GRAPH
        graph_key = next(
            (k for k in backend_metrics if k == graph_name or k.endswith(f"-{graph_name}")),
            None,
        )
        self.assertIsNotNone(
            graph_key,
            f"Expected a key matching '{graph_name}' in backend_metrics, got: {list(backend_metrics.keys())}",
        )

        graph_entry = backend_metrics[graph_key]
        self.assertIsInstance(graph_entry, dict)

        # Assert required top-level fields in graph entry (backend-agnostic contract)
        self.assertIn("backend", graph_entry, "Missing 'backend' field")
        self.assertIn("nodes", graph_entry, "Missing 'nodes' field")
        self.assertIn("cluster_id", graph_entry, "Missing 'cluster_id' field")
        self.assertIn("servers", graph_entry, "Missing 'servers' field")
        self.assertIsInstance(graph_entry["backend"], str)
        self.assertIsInstance(graph_entry["nodes"], int)
        self.assertIsInstance(graph_entry["cluster_id"], str)
        self.assertIsInstance(graph_entry["servers"], dict)

        # Assert every server entry — branch by backend type for portability
        servers = graph_entry["servers"]
        self.assertTrue(servers, "servers should not be empty")
        backend_type = graph_entry["backend"]
        for server_name, server_entry in servers.items():
            self.assertIsInstance(
                server_entry,
                dict,
                f"backend_metrics server entry for {server_name} should be a dict",
            )
            if backend_type == "rocksdb":
                # Pin RocksDB-specific keys captured from HugeGraph 1.7.0
                missing_keys = EXPECTED_ROCKSDB_SERVER_KEYS - set(server_entry.keys())
                self.assertFalse(
                    missing_keys,
                    f"rocksdb server entry for {server_name} missing expected keys: {sorted(missing_keys)}",
                )
            else:
                # Backend-agnostic: assert non-empty dict only
                self.assertTrue(
                    server_entry,
                    f"server entry for {server_name} should not be empty",
                )
