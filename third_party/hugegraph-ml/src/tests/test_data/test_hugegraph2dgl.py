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

import torch
from dgl.data import CoraGraphDataset, GINDataset

from hugegraph_ml.data.hugegraph2dgl import HugeGraph2DGL
from hugegraph_ml.utils.dgl2hugegraph_utils import load_acm_raw


class TestHugegraph2dDGL(unittest.TestCase):
    def setUp(self):
        self.cora_data = CoraGraphDataset()[0]
        self.mutag_dataset = GINDataset(name="MUTAG", self_loop=True)
        self.acm_data = load_acm_raw()
        self.ntype_map = {
            "author": "ACM_author_v",
            "field": "ACM_field_v",
            "paper": "ACM_paper_v",
        }
        self.etype_map = {
            "ap": "ACM_ap_e",
            "fp": "ACM_fp_e",
            "pa": "ACM_pa_e",
            "pf": "ACM_pf_e",
        }

    def test_convert_graph(self):
        hg2d = HugeGraph2DGL()
        graph = hg2d.convert_graph(vertex_label="CORA_vertex", edge_label="CORA_edge")
        self.assertEqual(graph.number_of_nodes(), self.cora_data.number_of_nodes(), "Number of nodes does not match.")

        self.assertEqual(graph.number_of_edges(), self.cora_data.number_of_edges(), "Number of edges does not match.")

        self.assertEqual(
            graph.ndata["feat"].shape, self.cora_data.ndata["feat"].shape, "Node feature dimensions do not match."
        )

        self.assertEqual(
            graph.ndata["label"].unique().shape[0],
            self.cora_data.ndata["label"].unique().shape[0],
            "Number of classes does not match.",
        )

        self.assertTrue(
            torch.equal(graph.ndata["train_mask"], self.cora_data.ndata["train_mask"]), "Train mask does not match."
        )

        self.assertTrue(
            torch.equal(graph.ndata["val_mask"], self.cora_data.ndata["val_mask"]), "Validation mask does not match."
        )

        self.assertTrue(
            torch.equal(graph.ndata["test_mask"], self.cora_data.ndata["test_mask"]), "Test mask does not match."
        )

        self.assertEqual(
            graph.number_of_nodes(), self.cora_data.number_of_nodes(), "Number of nodes in graph_info does not match."
        )

        self.assertEqual(
            graph.number_of_edges(), self.cora_data.number_of_edges(), "Number of edges in graph_info does not match."
        )

    def test_convert_graph_dataset(self):
        hg2d = HugeGraph2DGL()
        dataset_dgl = hg2d.convert_graph_dataset(
            graph_vertex_label="MUTAG_graph_vertex",
            vertex_label="MUTAG_vertex",
            edge_label="MUTAG_edge",
        )

        self.assertEqual(len(dataset_dgl), len(self.mutag_dataset), "Number of graphs does not match.")

        self.assertEqual(dataset_dgl.info["n_graphs"], len(self.mutag_dataset), "Number of graphs does not match.")

        self.assertEqual(
            dataset_dgl.info["n_classes"], self.mutag_dataset.gclasses, "Number of graph classes does not match."
        )
        self.assertEqual(
            dataset_dgl.info["n_feat_dim"], self.mutag_dataset.dim_nfeats, "Node feature dimensions do not match."
        )

    def test_convert_hetero_graph(self):
        hg2d = HugeGraph2DGL()
        hetero_graph = hg2d.convert_hetero_graph(
            vertex_labels=["ACM_paper_v", "ACM_author_v", "ACM_field_v"],
            edge_labels=["ACM_ap_e", "ACM_fp_e", "ACM_pa_e", "ACM_pf_e"],
        )

        for ntype in self.acm_data.ntypes:
            self.assertIn(
                self.ntype_map[ntype], hetero_graph.ntypes, f"Node type {ntype} is missing in converted graph."
            )
            acm_node_count = self.acm_data.num_nodes(ntype)
            hetero_node_count = hetero_graph.num_nodes(self.ntype_map[ntype])
            self.assertEqual(
                acm_node_count,
                hetero_node_count,
                f"Node count for type {ntype} does not match: {acm_node_count} != {hetero_node_count}",
            )

        for c_etypes in self.acm_data.canonical_etypes:
            mapped_c_etypes = (self.ntype_map[c_etypes[0]], self.etype_map[c_etypes[1]], self.ntype_map[c_etypes[2]])
            self.assertIn(
                mapped_c_etypes,
                hetero_graph.canonical_etypes,
                f"Edge type {mapped_c_etypes} is missing in converted graph.",
            )
            acm_edge_count = self.acm_data.num_edges(etype=c_etypes)
            hetero_edge_count = hetero_graph.num_edges(etype=mapped_c_etypes)
            self.assertEqual(
                acm_edge_count,
                hetero_edge_count,
                f"Edge count for type {mapped_c_etypes} does not match: {acm_edge_count} != {hetero_edge_count}",
            )
