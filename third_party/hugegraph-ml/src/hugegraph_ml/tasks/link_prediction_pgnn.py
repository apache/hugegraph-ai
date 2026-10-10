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

import dgl
import torch
from torch import nn

from hugegraph_ml.models.pgnn import (
    eval_model,
    get_dataset,
    preselect_anchor,
    train_model,
)


class LinkPredictionPGNN:
    def __init__(self, graph, model: nn.Module):
        self.graph = graph
        self._model = model
        self._device = ""

    def train(
        self,
        lr: float = 1e-3,
        weight_decay: float = 0,
        n_epochs: int = 200,
        gpu: int = -1,
    ):
        self._device = f"cuda:{gpu}" if gpu != -1 and torch.cuda.is_available() else "cpu"
        self._model.to(self._device)
        data = get_dataset(self.graph)
        # pre-sample anchor nodes and compute shortest distance values for all epochs
        (
            g_list,
            anchor_eid_list,
            dist_max_list,
            edge_weight_list,
        ) = preselect_anchor(data)
        optimizer = torch.optim.Adam(self._model.parameters(), lr=lr, weight_decay=weight_decay)
        loss_func = nn.BCEWithLogitsLoss()
        best_auc_val = -1
        for epoch in range(n_epochs):
            if epoch == 200:
                for param_group in optimizer.param_groups:
                    param_group["lr"] /= 10

            g = dgl.graph(g_list[epoch])
            g.ndata["feat"] = torch.FloatTensor(data["feature"])
            g.edata["sp_dist"] = torch.FloatTensor(edge_weight_list[epoch])
            g_data = {
                "graph": g.to(self._device),
                "anchor_eid": anchor_eid_list[epoch],
                "dists_max": dist_max_list[epoch],
            }

            train_model(data, self._model, loss_func, optimizer, self._device, g_data)

            _loss_train, _auc_train, auc_val, _auc_test = eval_model(data, g_data, self._model, loss_func, self._device)
            if auc_val > best_auc_val:
                best_auc_val = auc_val

            if epoch % 100 == 0:
                pass
