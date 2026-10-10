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
GRAND (Graph Random Neural Network)

References
----------
Paper: https://arxiv.org/abs/2005.11079
Author's code: https://github.com/THUDM/GRAND
DGL code: https://github.com/dmlc/dgl/tree/master/examples/pytorch/grand
"""

import numpy as np
import torch
import torch.nn.functional as F
from dgl.nn.pytorch import GraphConv
from torch import nn


class GRAND(nn.Module):
    """
    Implementation of the GRAND (Graph Random Neural Network) model for graph representation learning.

    Parameters
    ----------
    n_in_feats : int
        Number of input features per node.
    n_hidden : int
        Number of hidden units in the MLP.
    n_out_feats : int
        Number of output features or classes.
    sample : int
        Number of augmentations (samples) to generate during training.
    order : int
        The number of propagation steps in the graph convolution.
    p_drop_node : float
        Dropout rate for nodes during training.
    p_drop_input : float
        Dropout rate for input features in the MLP.
    p_drop_hidden : float
        Dropout rate for hidden features in the MLP.
    bn : bool
        Whether to use batch normalization in the MLP.
    temp : float
            Temperature parameter for sharpening the probabilities.
    lam : float
        Weight for the consistency loss.
    """

    def __init__(
        self,
        n_in_feats,
        n_out_feats,
        n_hidden=32,
        sample=4,
        order=8,
        p_drop_node=0.5,
        p_drop_input=0.5,
        p_drop_hidden=0.5,
        bn=False,
        temp=0.5,
        lam=1.0,
    ):
        super().__init__()
        self.sample = sample  # Number of augmentations
        self.order = order  # Order of propagation steps

        # MLP for final prediction
        self.mlp = MLP(n_in_feats, n_hidden, n_out_feats, p_drop_input, p_drop_hidden, bn)
        # Graph convolution layer without trainable weights
        self.graph_conv = GraphConv(n_in_feats, n_in_feats, norm="both", weight=False, bias=False)
        self.p_drop_node = p_drop_node  # Dropout rate for nodes
        self.temp = temp
        self.lam = lam

    def consis_loss(self, logits):
        """
        Compute the consistency loss between multiple augmented logits.

        Parameters
        ----------
        logits : list of torch.Tensor
            List of logits from different augmentations.

        Returns
        -------
        torch.Tensor
            The computed consistency loss.
        """
        ps = torch.stack([torch.exp(logit) for logit in logits], dim=2)  # Convert logits to probabilities
        avg_p = torch.mean(ps, dim=2)  # Average the probabilities across augmentations
        sharp_p = torch.pow(avg_p, 1.0 / self.temp)  # Sharpen the probabilities using the temperature
        sharp_p = sharp_p / sharp_p.sum(dim=1, keepdim=True)  # Normalize the sharpened probabilities
        sharp_p = sharp_p.unsqueeze(2).detach()  # Detach to prevent gradients flowing through sharp_p
        loss = self.lam * torch.mean((ps - sharp_p).pow(2).sum(dim=1))  # Compute the consistency loss
        return loss

    def drop_node(self, feats):
        """
        Randomly drop nodes by applying dropout to the node features.

        Parameters
        ----------
        feats : torch.Tensor
            Node features.

        Returns
        -------
        torch.Tensor
            Node features with dropout applied.
        """
        n = feats.shape[0]  # Number of nodes
        drop_rates = torch.FloatTensor(np.ones(n) * self.p_drop_node).to(feats.device)  # Dropout rates for each node
        masks = torch.bernoulli(1.0 - drop_rates).unsqueeze(1)  # Generate dropout masks
        feats = masks.to(feats.device) * feats  # Apply dropout to the node features
        return feats

    def scale_node(self, feats):
        """
        Scale node features to account for dropout.

        Parameters
        ----------
        feats : torch.Tensor
            Node features.

        Returns
        -------
        torch.Tensor
            Scaled node features.
        """
        feats = feats * (1.0 - self.p_drop_node)  # Scale the features
        return feats

    def propagation(self, graph, feats):
        """
        Propagate node features through the graph using graph convolution.

        Parameters
        ----------
        graph : dgl.DGLGraph
            Input graph.
        feats : torch.Tensor
            Node features.

        Returns
        -------
        torch.Tensor
            Node features after propagation.
        """
        y = feats
        for _ in range(self.order):
            feats = self.graph_conv(graph, feats)  # Apply graph convolution
            y = y + feats  # Apply residual connection
        return y / (self.order + 1)  # Normalize the output by the order of propagation

    def loss(self, logits, labels):
        if isinstance(logits, list):
            # calculate supervised loss
            loss_sup = 0
            for k in range(self.sample):
                loss_sup += F.nll_loss(logits[k], labels)
            loss_sup = loss_sup / self.sample
            # calculate consistency loss
            loss_consis = self.consis_loss(logits)
            loss = loss_sup + loss_consis
        else:
            # loss for evaluate
            loss = F.nll_loss(logits, labels)
        return loss

    def forward(self, graph, feats):
        """
        Perform forward pass with multiple augmentations and return logits.

        Parameters
        ----------
        graph : dgl.DGLGraph
            Input graph.
        feats : torch.Tensor
            Node features.

        Returns
        -------
        list of torch.Tensor
            Logits from each augmentation.
        """
        logits_list = []
        for _ in range(self.sample):
            f = self.drop_node(feats)  # Apply node dropout
            y = self.propagation(graph, f)  # Propagate through the graph
            logits_list.append(torch.log_softmax(self.mlp(y), dim=-1))  # Compute logits
        return logits_list

    def inference(self, graph, feats):
        """
        Perform inference without augmentation, scaling the node features.

        Parameters
        ----------
        graph : dgl.DGLGraph
            Input graph.
        feats : torch.Tensor
            Node features.

        Returns
        -------
        torch.Tensor
            Logits after inference.
        """
        f = self.scale_node(feats)  # Scale node features
        y = self.propagation(graph, f)  # Propagate through the graph
        return torch.log_softmax(self.mlp(y), dim=-1)  # Compute final logits


class MLP(nn.Module):
    """
    Multi-Layer Perceptron (MLP) for transforming node features.

    Parameters
    ----------
    n_in_feats : int
        Number of input features.
    n_hidden : int
        Number of hidden units.
    n_out_feats : int
        Number of output features or classes.
    p_input_drop : float
        Dropout rate for input features.
    p_hidden_drop : float
        Dropout rate for hidden features.
    bn : bool
        Whether to use batch normalization.
    """

    def __init__(self, n_in_feats, n_hidden, n_out_feats, p_input_drop, p_hidden_drop, bn):
        super().__init__()
        self.layer1 = nn.Linear(n_in_feats, n_hidden, bias=True)  # First linear layer
        self.layer2 = nn.Linear(n_hidden, n_out_feats, bias=True)  # Second linear layer
        self.input_drop = nn.Dropout(p_input_drop)  # Dropout for input features
        self.hidden_drop = nn.Dropout(p_hidden_drop)  # Dropout for hidden features
        self.bn = bn  # Whether to use batch normalization
        if self.bn:
            self.bn1 = nn.BatchNorm1d(n_in_feats)  # Batch normalization for input features
            self.bn2 = nn.BatchNorm1d(n_hidden)  # Batch normalization for hidden features

    def forward(self, x):
        """
        Forward pass through the MLP.

        Parameters
        ----------
        x : torch.Tensor
            Input node features.

        Returns
        -------
        torch.Tensor
            Transformed node features.
        """
        if self.bn:
            x = self.bn1(x)  # Apply batch normalization to input features
        x = self.input_drop(x)  # Apply dropout to input features
        x = F.relu(self.layer1(x))  # Apply ReLU activation after the first linear layer

        if self.bn:
            x = self.bn2(x)  # Apply batch normalization to hidden features
        x = self.hidden_drop(x)  # Apply dropout to hidden features
        x = self.layer2(x)  # Apply the second linear layer

        return x  # Return final transformed features
