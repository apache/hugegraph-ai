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
DeeperGCN

References
----------
Paper: https://arxiv.org/abs/2006.07739
Author's code: https://github.com/lightaime/deep_gcns_torch
DGL code: https://github.com/dmlc/dgl/tree/master/examples/pytorch/deepergcn
"""

import dgl.function as fn
import torch
import torch.nn.functional as F
from dgl.nn.functional import edge_softmax
from torch import nn

# pylint: disable=E1101,E0401


class DeeperGCN(nn.Module):
    r"""

    Description
    -----------
    Parameters
    ----------
    node_feat_dim: int
        Size of node feature.
    edge_feat_dim: int
        Size of edge feature.
    hid_dim: int
        Size of hidden representations.
    out_dim: int
        Size of output.
    num_layers: int
        Number of graph convolutional layers.
    dropout: float
        Dropout rate. Default is 0.
    beta: float
        A continuous variable called an inverse temperature. Default is 1.0.
    learn_beta: bool
        Whether beta is a learnable weight. Default is False.
    aggr: str
        Type of aggregation. Default is 'softmax'.
    mlp_layers: int
        Number of MLP layers in message normalization. Default is 1.
    """

    def __init__(
        self,
        node_feat_dim,
        edge_feat_dim,
        hid_dim,
        out_dim,
        num_layers,
        dropout=0.0,
        beta=1.0,
        learn_beta=False,
        aggr="softmax",
        mlp_layers=1,
    ):
        super().__init__()

        self.num_layers = num_layers
        self.dropout = dropout
        self.gcns = nn.ModuleList()
        self.norms = nn.ModuleList()

        for _ in range(self.num_layers):
            conv = GENConv(
                edge_feat_dim=edge_feat_dim,
                in_dim=hid_dim,
                out_dim=hid_dim,
                aggregator=aggr,
                beta=beta,
                learn_beta=learn_beta,
                mlp_layers=mlp_layers,
            )

            self.gcns.append(conv)
            self.norms.append(nn.BatchNorm1d(hid_dim, affine=True))

        # self.node_encoder = AtomEncoder(hid_dim)
        self.node_encoder = torch.nn.Sequential(
            torch.nn.Linear(node_feat_dim, 512),
            torch.nn.ReLU(),
            torch.nn.Linear(512, hid_dim),
        )
        # self.pooling = AvgPooling()
        self.output = nn.Linear(hid_dim, out_dim)

        self.criterion = nn.CrossEntropyLoss()

    def forward(self, g, edge_feats, node_feats=None):
        with g.local_scope():
            hv = self.node_encoder(node_feats.float())
            he = edge_feats

            for layer in range(self.num_layers):
                hv1 = self.norms[layer](hv)
                hv1 = F.relu(hv1)
                hv1 = F.dropout(hv1, p=self.dropout, training=self.training)
                hv = self.gcns[layer](g, hv1, he) + hv

            # h_g = self.pooling(g, hv)

            return self.output(hv)

    def loss(self, logits, labels):
        return self.criterion(logits, labels)

    def inference(self, g, edge_feats, node_feats):
        return self.forward(g, edge_feats, node_feats)


class GENConv(nn.Module):
    r"""

    Description
    -----------
    Parameters
    ----------
    in_dim: int
        Input size.
    out_dim: int
        Output size.
    aggregator: str
        Type of aggregation. Default is 'softmax'.
    beta: float
        A continuous variable called an inverse temperature. Default is 1.0.
    learn_beta: bool
        Whether beta is a learnable variable or not. Default is False.
    p: float
        Initial power for power mean aggregation. Default is 1.0.
    learn_p: bool
        Whether p is a learnable variable or not. Default is False.
    msg_norm: bool
        Whether message normalization is used. Default is False.
    learn_msg_scale: bool
        Whether s is a learnable scaling factor or not in message normalization. Default is False.
    mlp_layers: int
        The number of MLP layers. Default is 1.
    eps: float
        A small positive constant in message construction function. Default is 1e-7.
    """

    def __init__(
        self,
        edge_feat_dim,
        in_dim,
        out_dim,
        aggregator="softmax",
        beta=1.0,
        learn_beta=False,
        p=1.0,
        learn_p=False,
        msg_norm=False,
        learn_msg_scale=False,
        mlp_layers=1,
        eps=1e-7,
    ):
        super().__init__()

        self.aggr = aggregator
        self.eps = eps

        channels = [in_dim]
        for _ in range(mlp_layers - 1):
            channels.append(in_dim * 2)
        channels.append(out_dim)

        self.mlp = MLP(channels)
        self.msg_norm = MessageNorm(learn_msg_scale) if msg_norm else None

        self.beta = (
            nn.Parameter(torch.Tensor([beta]), requires_grad=True) if learn_beta and self.aggr == "softmax" else beta
        )
        self.p = nn.Parameter(torch.Tensor([p]), requires_grad=True) if learn_p else p

        # self.edge_encoder = BondEncoder(in_dim)
        self.edge_encoder = torch.nn.Sequential(
            torch.nn.Linear(edge_feat_dim, 512),
            torch.nn.ReLU(),
            torch.nn.Linear(512, in_dim),
        )

    def forward(self, g, node_feats, edge_feats):
        with g.local_scope():
            # Node and edge feature size need to match.
            g.ndata["h"] = node_feats
            g.edata["h"] = self.edge_encoder(edge_feats.float())
            g.apply_edges(fn.u_add_e("h", "h", "m"))

            if self.aggr == "softmax":
                g.edata["m"] = F.relu(g.edata["m"]) + self.eps
                g.edata["a"] = edge_softmax(g, g.edata["m"] * self.beta)
                g.update_all(
                    lambda edge: {"x": edge.data["m"] * edge.data["a"]},
                    fn.sum("x", "m"),
                )

            elif self.aggr == "power":
                minv, maxv = 1e-7, 1e1
                torch.clamp_(g.edata["m"], minv, maxv)
                g.update_all(
                    lambda edge: {"x": torch.pow(edge.data["m"], self.p)},
                    fn.mean("x", "m"),
                )
                torch.clamp_(g.ndata["m"], minv, maxv)
                g.ndata["m"] = torch.pow(g.ndata["m"], self.p)

            else:
                raise NotImplementedError(f"Aggregator {self.aggr} is not supported.")

            if self.msg_norm is not None:
                g.ndata["m"] = self.msg_norm(node_feats, g.ndata["m"])

            feats = node_feats + g.ndata["m"]

            return self.mlp(feats)


class MLP(nn.Sequential):
    def __init__(self, channels, act="relu", dropout=0.0, bias=True):
        layers = []

        for i in range(1, len(channels)):
            layers.append(nn.Linear(channels[i - 1], channels[i], bias))
            if i < len(channels) - 1:
                layers.append(nn.BatchNorm1d(channels[i], affine=True))
                layers.append(nn.ReLU())
                layers.append(nn.Dropout(dropout))

        super().__init__(*layers)


class MessageNorm(nn.Module):
    r"""

    Description
    -----------
    Parameters
    ----------
    learn_scale: bool
        Whether s is a learnable scaling factor or not. Default is False.
    """

    def __init__(self, learn_scale=False):
        super().__init__()
        self.scale = nn.Parameter(torch.FloatTensor([1.0]), requires_grad=learn_scale)

    def forward(self, feats, msg, p=2):
        msg = F.normalize(msg, p=2, dim=-1)
        feats_norm = feats.norm(p=p, dim=-1, keepdim=True)
        return msg * feats_norm * self.scale
