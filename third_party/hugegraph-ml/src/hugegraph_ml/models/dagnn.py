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

# pylint: disable=C0103

"""
Deep Adaptive Graph Neural Network (DAGNN)

References
----------
Paper: https://arxiv.org/abs/2007.09296
Author's code: https://github.com/divelab/DeeperGNN
DGL code: https://github.com/dmlc/dgl/tree/master/examples/pytorch/dagnn
"""

import dgl.function as fn
import torch
from torch import nn
from torch.nn import Parameter
from torch.nn import functional as F


class DAGNNConv(nn.Module):
    def __init__(self, in_dim, k):
        super().__init__()

        self.s = Parameter(torch.FloatTensor(in_dim, 1))
        self.k = k

        self.reset_parameters()

    def reset_parameters(self):
        gain = nn.init.calculate_gain("sigmoid")
        nn.init.xavier_uniform_(self.s, gain=gain)

    def forward(self, graph, feats):
        with graph.local_scope():
            results = [feats]

            degs = graph.in_degrees().float()
            norm = torch.pow(degs, -0.5)
            norm = norm.to(feats.device).unsqueeze(1)

            for _ in range(self.k):
                feats = feats * norm
                graph.ndata["h"] = feats
                graph.update_all(fn.copy_u("h", "m"), fn.sum("m", "h"))  # pylint: disable=E1101
                feats = graph.ndata["h"]
                feats = feats * norm
                results.append(feats)

            H = torch.stack(results, dim=1)
            S = F.sigmoid(torch.matmul(H, self.s))
            S = S.permute(0, 2, 1)
            H = torch.matmul(S, H).squeeze()

            return H


class MLPLayer(nn.Module):
    def __init__(self, in_dim, out_dim, bias=True, activation=None, dropout=0):
        super().__init__()

        self.linear = nn.Linear(in_dim, out_dim, bias=bias)
        self.activation = activation
        self.dropout = nn.Dropout(dropout)
        self.reset_parameters()

    def reset_parameters(self):
        gain = 1.0
        if self.activation is F.relu:
            gain = nn.init.calculate_gain("relu")
        nn.init.xavier_uniform_(self.linear.weight, gain=gain)
        if self.linear.bias is not None:
            nn.init.zeros_(self.linear.bias)

    def forward(self, feats):
        feats = self.dropout(feats)
        feats = self.linear(feats)
        if self.activation:
            feats = self.activation(feats)

        return feats


class DAGNN(nn.Module):
    def __init__(
        self,
        k,
        in_dim,
        hid_dim,
        out_dim,
        bias=True,
        activation=F.relu,
        dropout=0,
    ):
        super().__init__()
        self.mlp = nn.ModuleList()
        self.mlp.append(
            MLPLayer(
                in_dim=in_dim,
                out_dim=hid_dim,
                bias=bias,
                activation=activation,
                dropout=dropout,
            )
        )
        self.mlp.append(
            MLPLayer(
                in_dim=hid_dim,
                out_dim=out_dim,
                bias=bias,
                activation=None,
                dropout=dropout,
            )
        )
        self.dagnn = DAGNNConv(in_dim=out_dim, k=k)

        self.criterion = nn.CrossEntropyLoss()

    def forward(self, graph, feats):
        for layer in self.mlp:
            feats = layer(feats)
        feats = self.dagnn(graph, feats)
        return feats

    def loss(self, logits, labels):
        return self.criterion(logits, labels)

    def inference(self, graph, feats):
        return self.forward(graph, feats)
