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

# pylint: disable=too-many-branches

import torch.nn.functional as F
from dgl.nn.pytorch.conv import GINConv
from dgl.nn.pytorch.glob import AvgPooling, GlobalAttentionPooling, MaxPooling, Set2Set, SumPooling
from torch import nn


class GIN(nn.Module):
    def __init__(self, n_in_feats, n_out_feats, n_hidden=16, n_layers=5, p_drop=0.5, pooling="sum"):
        super().__init__()
        self.gin_layers = nn.ModuleList()
        self.batch_norms = nn.ModuleList()
        self.criterion = nn.CrossEntropyLoss()
        # five-layer GCN with two-layer MLP aggregator and sum-neighbor-pooling scheme
        assert n_layers >= 2, "The number of GIN layers must be at least 2."
        for layer in range(n_layers - 1):
            mlp = _MLP(n_in_feats, n_hidden, n_hidden) if layer == 0 else _MLP(n_hidden, n_hidden, n_hidden)
            self.gin_layers.append(GINConv(mlp, learn_eps=False))  # set to True if learning epsilon
            self.batch_norms.append(nn.BatchNorm1d(n_hidden))
        # linear functions for graph sum pooling of output of each layer
        self.linear_prediction = nn.ModuleList()
        for layer in range(n_layers):
            if layer == 0:
                self.linear_prediction.append(nn.Linear(n_in_feats, n_out_feats))
            else:
                # adapt set2set pooling dim
                if pooling == "set2set":
                    self.linear_prediction.append(nn.Linear(2 * n_hidden, n_out_feats))
                else:
                    self.linear_prediction.append(nn.Linear(n_hidden, n_out_feats))
        self.drop = nn.Dropout(p_drop)
        if pooling == "sum":
            self.pool = SumPooling()
        elif pooling == "mean":
            self.pool = AvgPooling()
        elif pooling == "max":
            self.pool = MaxPooling()
        elif pooling == "global_attention":
            gate_nn = nn.Linear(n_hidden, 1)
            self.pool = GlobalAttentionPooling(gate_nn)
        elif pooling == "set2set":
            self.pool = Set2Set(n_hidden, n_iters=2, n_layers=1)
        else:
            raise ValueError(f"Unsupported pooling type: {pooling}")

    def loss(self, logits, labels):
        loss = self.criterion(logits, labels)
        return loss

    def forward(self, g, h):
        # list of hidden representation at each layer (including the input layer)
        hidden_rep = [h]
        for i, layer in enumerate(self.gin_layers):
            h = layer(g, h)
            h = self.batch_norms[i](h)
            h = F.relu(h)
            hidden_rep.append(h)
        score_over_layer = 0
        # perform graph sum pooling over all nodes in each layer
        for i, _h in enumerate(hidden_rep):
            if i > 0:
                pooled_h = self.pool(g, _h)
                score_over_layer += self.drop(self.linear_prediction[i](pooled_h))
        return score_over_layer


class _MLP(nn.Module):
    def __init__(self, n_in_feats, n_hidden, n_out_feats):
        super().__init__()
        # two-layer MLP
        self.fc1 = nn.Linear(n_in_feats, n_hidden, bias=False)
        self.fc2 = nn.Linear(n_hidden, n_out_feats, bias=False)
        self.batch_norm = nn.BatchNorm1d(n_hidden)

    def forward(self, x):
        h = x
        h = F.relu(self.batch_norm(self.fc1(h)))
        return self.fc2(h)
