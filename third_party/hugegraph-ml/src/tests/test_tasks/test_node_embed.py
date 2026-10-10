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

from hugegraph_ml.data.hugegraph2dgl import HugeGraph2DGL
from hugegraph_ml.models.dgi import DGI
from hugegraph_ml.tasks.node_embed import NodeEmbed


class TestNodeEmbed(unittest.TestCase):
    def setUp(self):
        self.hg2d = HugeGraph2DGL()
        self.graph = self.hg2d.convert_graph(vertex_label="CORA_vertex", edge_label="CORA_edge")
        self.embed_size = 512

    def test_check_graph(self):
        try:
            NodeEmbed(
                graph=self.graph,
                model=DGI(n_in_feats=self.graph.ndata["feat"].shape[1], n_hidden=self.embed_size),
            )
        except ValueError as e:
            self.fail(f"_check_graph failed: {e!s}")

    def test_train_and_embed(self):
        node_embed_task = NodeEmbed(
            graph=self.graph,
            model=DGI(n_in_feats=self.graph.ndata["feat"].shape[1], n_hidden=self.embed_size),
        )
        self.graph = node_embed_task.train_and_embed(n_epochs=5, patience=5)
        embed_feat_dim = self.graph.ndata["feat"].shape[1]
        self.assertEqual(
            embed_feat_dim,
            self.embed_size,
            f"Expected node feature dimension {self.embed_size}, but got {embed_feat_dim}.",
        )
