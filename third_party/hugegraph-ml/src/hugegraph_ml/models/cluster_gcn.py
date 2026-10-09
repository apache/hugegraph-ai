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
Cluster-GCN

References
----------
Paper: https://arxiv.org/abs/1905.07953
Author's code: https://github.com/google-research/google-research/tree/master/cluster_gcn
DGL code: https://github.com/dmlc/dgl/tree/master/examples/pytorch/cluster_gcn
"""

import dgl.nn as dglnn
import torch.nn.functional as F
from torch import nn


class SAGE(nn.Module):
    # pylint: disable=E1101
    def __init__(self, in_feats, n_hidden, n_classes):
        super().__init__()
        self.layers = nn.ModuleList()
        self.layers.append(dglnn.SAGEConv(in_feats, n_hidden, "mean"))
        self.layers.append(dglnn.SAGEConv(n_hidden, n_hidden, "mean"))
        self.layers.append(dglnn.SAGEConv(n_hidden, n_classes, "mean"))
        self.dropout = nn.Dropout(0.5)

    def forward(self, sg, x):
        h = x
        for layer_idx, layer in enumerate(self.layers):
            h = layer(sg, h)
            if layer_idx != len(self.layers) - 1:
                h = F.relu(h)
                h = self.dropout(h)
        return h

    def loss(self, logits, labels):
        return nn.CrossEntropyLoss()(logits, labels)

    def inference(self, sg, x):
        return self.forward(sg, x)
