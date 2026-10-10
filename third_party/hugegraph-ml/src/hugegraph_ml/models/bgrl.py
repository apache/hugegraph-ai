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

# pylint: disable=C0103,R1705.R1734,E1102

"""
Bootstrapped Graph Latents (BGRL)

References
----------
Paper: https://arxiv.org/abs/2102.06514
Author's code: https://github.com/nerdslab/bgrl
DGL code: https://github.com/dmlc/dgl/tree/master/examples/pytorch/bgrl
"""

import copy
import itertools

import dgl
import numpy as np
import torch
from dgl.nn.pytorch.conv import GraphConv
from dgl.transforms import Compose, DropEdge, FeatMask
from torch import nn
from torch.nn import BatchNorm1d
from torch.nn.functional import cosine_similarity


class MLPPredictor(nn.Module):
    r"""MLP used for predictor. The MLP has one hidden layer.
    Args:
        input_size (int): Size of input features.
        output_size (int): Size of output features.
        hidden_size (int, optional): Size of hidden layer. (default: :obj:`4096`).
    """

    def __init__(self, input_size, output_size, hidden_size=512):
        super().__init__()

        self.net = nn.Sequential(
            nn.Linear(input_size, hidden_size, bias=True),
            nn.PReLU(1),
            nn.Linear(hidden_size, output_size, bias=True),
        )
        self.reset_parameters()

    def forward(self, x):
        return self.net(x)

    def reset_parameters(self):
        # kaiming_uniform
        for m in self.modules():
            if isinstance(m, nn.Linear):
                m.reset_parameters()


class GCN(nn.Module):
    def __init__(self, layer_sizes, batch_norm_mm=0.99):
        super().__init__()

        self.layers = nn.ModuleList()
        for in_dim, out_dim in itertools.pairwise(layer_sizes):
            self.layers.append(GraphConv(in_dim, out_dim))
            self.layers.append(BatchNorm1d(out_dim, momentum=batch_norm_mm))
            self.layers.append(nn.PReLU())

    def forward(self, g, feats):
        x = feats
        for layer in self.layers:
            x = layer(g, x) if isinstance(layer, GraphConv) else layer(x)
        return x

    def reset_parameters(self):
        for layer in self.layers:
            if hasattr(layer, "reset_parameters"):
                layer.reset_parameters()


class BGRL(nn.Module):
    r"""BGRL architecture for Graph representation learning.
    Args:
        encoder (torch.nn.Module): Encoder network to be duplicated and used in both online and target networks.
        predictor (torch.nn.Module): Predictor network used to predict the target projection from the online projection.
    .. note::
        `encoder` must have a `reset_parameters` method, as the weights of the target network will be initialized
        differently from the online network.
    """

    def __init__(self, encoder, predictor):
        super().__init__()
        # online network
        self.online_encoder = encoder
        self.predictor = predictor

        # target network
        self.target_encoder = copy.deepcopy(encoder)

        # reinitialize weights
        self.target_encoder.reset_parameters()

        # stop gradient
        for param in self.target_encoder.parameters():
            param.requires_grad = False

    def trainable_parameters(self):
        r"""Returns the parameters that will be updated via an optimizer."""
        return list(self.online_encoder.parameters()) + list(self.predictor.parameters())

    @torch.no_grad()
    def update_target_network(self, mm):
        r"""Performs a momentum update of the target network's weights.
        Args:
            mm (float): Momentum used in moving average update.
        """
        for param_q, param_k in zip(self.online_encoder.parameters(), self.target_encoder.parameters(), strict=False):
            param_k.data.mul_(mm).add_(param_q.data, alpha=1.0 - mm)

    def forward(self, graph, feat):
        transform_1 = get_graph_drop_transform(drop_edge_p=0.3, feat_mask_p=0.3)
        transform_2 = get_graph_drop_transform(drop_edge_p=0.2, feat_mask_p=0.4)
        online_x = transform_1(graph)
        target_x = transform_2(graph)
        online_x, target_x = dgl.add_self_loop(online_x), dgl.add_self_loop(target_x)
        online_feats, target_feats = online_x.ndata["feat"], target_x.ndata["feat"]
        # forward online network
        online_y1 = self.online_encoder(online_x, online_feats)
        # prediction
        online_q1 = self.predictor(online_y1)
        # forward target network
        with torch.no_grad():
            target_y1 = self.target_encoder(target_x, target_feats).detach()
        # forward online network 2
        online_y2 = self.online_encoder(target_x, target_feats)
        # prediction
        online_q2 = self.predictor(online_y2)
        # forward target network
        with torch.no_grad():
            target_y2 = self.target_encoder(online_x, online_feats).detach()
        loss = (
            2
            - cosine_similarity(online_q1, target_y1.detach(), dim=-1).mean()  # pylint: disable=E1102
            - cosine_similarity(online_q2, target_y2.detach(), dim=-1).mean()  # pylint: disable=E1102
        )
        return loss

    def get_embedding(self, graph, feats):
        """
        Get the node embeddings from the encoder without computing gradients.

        Parameters
        ----------
        graph : dgl.DGLGraph
            The input graph.
        feats : torch.Tensor
            Node features.

        Returns
        -------
        torch.Tensor
            Node embeddings.
        """
        h = self.target_encoder(graph, feats)  # Encode the node features with GCN
        return h.detach()  # Detach from computation graph for evaluation


def compute_representations(net, dataset, device):
    r"""Pre-computes the representations for the entire data.
    Returns:
        [torch.Tensor, torch.Tensor]: Representations and labels.
    """
    net.eval()
    reps = []
    labels = []

    if len(dataset) == 1:
        g = dataset[0]
        g = dgl.add_self_loop(g)
        g = g.to(device)
        with torch.no_grad():
            reps.append(net(g))
            labels.append(g.ndata["label"])
    else:
        for g in dataset:
            # forward
            g = g.to(device)
            with torch.no_grad():
                reps.append(net(g))
                labels.append(g.ndata["label"])

    reps = torch.cat(reps, dim=0)
    labels = torch.cat(labels, dim=0)
    return [reps, labels]


class CosineDecayScheduler:
    def __init__(self, max_val, warmup_steps, total_steps):
        self.max_val = max_val
        self.warmup_steps = warmup_steps
        self.total_steps = total_steps

    def get(self, step):
        if step < self.warmup_steps:
            return self.max_val * step / self.warmup_steps
        elif self.warmup_steps <= step <= self.total_steps:
            return (
                self.max_val
                * (1 + np.cos((step - self.warmup_steps) * np.pi / (self.total_steps - self.warmup_steps)))
                / 2
            )
        else:
            raise ValueError(f"Step ({step}) > total number of steps ({self.total_steps}).")


def get_graph_drop_transform(drop_edge_p, feat_mask_p):
    transforms = []

    # make copy of graph
    transforms.append(copy.deepcopy)

    # drop edges
    if drop_edge_p > 0.0:
        transforms.append(DropEdge(drop_edge_p))

    # drop features
    if feat_mask_p > 0.0:
        transforms.append(FeatMask(feat_mask_p, node_feat_names=["feat"]))

    return Compose(transforms)
