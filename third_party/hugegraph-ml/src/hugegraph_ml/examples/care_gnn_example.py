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
from hugegraph_ml.models.care_gnn import CAREGNN
from hugegraph_ml.tasks.fraud_detector_caregnn import DetectorCaregnn


def care_gnn_example(n_epochs=200):
    hg2d = HugeGraph2DGL()
    graph = hg2d.convert_hetero_graph(
        vertex_labels=["AMAZON_user_v"],
        edge_labels=[
            "AMAZON_net_upu_e",
            "AMAZON_net_usu_e",
            "AMAZON_net_uvu_e",
        ],
    )
    model = CAREGNN(
        in_dim=graph.ndata["feature"].shape[-1],
        num_classes=graph.ndata["label"].unique().shape[0],
        hid_dim=64,
        num_layers=1,
        activation=torch.tanh,
        step_size=0.02,
        edges=graph.canonical_etypes,
    )
    detector_task = DetectorCaregnn(graph, model)
    detector_task.train(lr=0.005, weight_decay=0.0005, n_epochs=n_epochs)
    print(detector_task.evaluate())


if __name__ == "__main__":
    care_gnn_example()
