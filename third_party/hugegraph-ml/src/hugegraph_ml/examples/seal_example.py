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

import torch

from hugegraph_ml.data.hugegraph2dgl import HugeGraph2DGL
from hugegraph_ml.models.seal import DGCNN, data_prepare
from hugegraph_ml.tasks.link_prediction_seal import LinkPredictionSeal


def seal_example(n_epochs=200):
    torch.manual_seed(2021)
    hg2d = HugeGraph2DGL()
    graph, split_edge = hg2d.convert_graph_ogb(
        vertex_label="ogbl-collab_vertex",
        edge_label="ogbl-collab_edge",
        split_label="ogbl-collab_split_edge",
    )
    node_attribute, edge_weight = data_prepare(graph=graph, split_edge=split_edge)
    model = DGCNN(
        num_layers=3,
        hidden_units=32,
        k=30,
        gcn_type="gcn",
        node_attributes=node_attribute,
        edge_weights=edge_weight,
        node_embedding=None,
        use_embedding=True,
        num_nodes=graph.num_nodes(),
        dropout=0.5,
    )
    link_pre_task = LinkPredictionSeal(graph, split_edge, model)
    link_pre_task.train(lr=0.005, n_epochs=n_epochs)

    # After training, the final epoch's evaluation is calculated by train and
    # stored in summary_test.
    # Print a message indicating that training is complete.
    print("Training completed. Evaluation metrics were calculated during training.")


if __name__ == "__main__":
    seal_example()
