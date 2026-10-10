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

"""
Attention-based Graph Neural Network (AGNN)

References
----------
Paper: https://arxiv.org/abs/1803.03735
Author's code:
DGL code: https://github.com/dmlc/dgl/blob/master/python/dgl/nn/pytorch/conv/agnnconv.py
"""

import torch.nn.functional as F
from dgl.nn.pytorch.conv import AGNNConv
from torch import nn


class AGNN(nn.Module):
    def __init__(self, num_layers, in_dim, hid_dim, out_dim, dropout):
        super().__init__()
        self.num_layers = num_layers
        self.embedding_layer = nn.Linear(in_dim, hid_dim, bias=False)

        self.attention_layers = nn.ModuleList()
        # 2-layer AGNN
        for _ in range(self.num_layers):
            self.attention_layers.append(AGNNConv())

        self.output_layer = nn.Linear(hid_dim, out_dim, bias=False)

        self.dropout = nn.Dropout(dropout)

        self.criterion = nn.CrossEntropyLoss()

    def forward(self, graph, features):
        h = F.relu(self.embedding_layer(features))
        for i in range(self.num_layers):
            self.attention_layers[i](graph, h)
        h = self.output_layer(h)
        h = self.dropout(h)
        return h

    def loss(self, logits, labels):
        return self.criterion(logits, labels)

    def inference(self, graph, feats):
        return self.forward(graph, feats)
