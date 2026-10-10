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
from hugegraph_ml.models.jknet import JKNet
from hugegraph_ml.tasks.node_classify import NodeClassify


class TestNodeClassify(unittest.TestCase):
    def setUp(self):
        self.hg2d = HugeGraph2DGL()
        self.graph = self.hg2d.convert_graph(vertex_label="CORA_vertex", edge_label="CORA_edge")

    def test_check_graph(self):
        try:
            NodeClassify(
                graph=self.graph,
                model=JKNet(
                    n_in_feats=self.graph.ndata["feat"].shape[1],
                    n_out_feats=self.graph.ndata["label"].unique().shape[0],
                ),
            )
        except ValueError as e:
            self.fail(f"_check_graph failed: {e!s}")

    def test_train_and_evaluate(self):
        node_classify_task = NodeClassify(
            graph=self.graph,
            model=JKNet(
                n_in_feats=self.graph.ndata["feat"].shape[1], n_out_feats=self.graph.ndata["label"].unique().shape[0]
            ),
        )
        node_classify_task.train(n_epochs=10, patience=3)
        metrics = node_classify_task.evaluate()
        self.assertTrue("accuracy" in metrics)
        self.assertTrue("loss" in metrics)


if __name__ == "__main__":
    unittest.main()
