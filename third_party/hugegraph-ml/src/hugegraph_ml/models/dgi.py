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
Deep Graph Infomax (DGI)

References
----------
Paper: https://arxiv.org/abs/1809.10341
Author's code: https://github.com/PetarV-/DGI
DGL code: https://github.com/dmlc/dgl/tree/master/examples/pytorch/dgi
"""

import math

import torch
from dgl.nn.pytorch import GraphConv
from torch import nn


class DGI(nn.Module):
    r"""
    Deep Graph InfoMax (DGI) model that maximizes mutual information between node embeddings and a graph summary.

    Parameters
    ----------
    n_in_feats : int
        Number of input features per node.
    n_hidden : int, optional
        Dimension of the hidden layers. Default is 512.
    n_layers : int, optional
        Number of GNN layers in the encoder. Default is 1.
    p_drop : float, optional
        Dropout rate for regularization. Default is 0.
    """

    def __init__(self, n_in_feats, n_hidden=512, n_layers=2, p_drop=0):
        super().__init__()
        self.encoder = GCNEncoder(n_in_feats, n_hidden, n_layers, p_drop)  # Initialize the GCN-based encoder
        self.discriminator = Discriminator(n_hidden)  # Initialize the discriminator for mutual information maximization
        self.loss = nn.BCEWithLogitsLoss()  # Binary cross-entropy loss with logits for classification

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
        h = self.encoder(graph, feats, corrupt=False)
        return h.detach()

    def forward(self, graph, feats):
        """
        Forward pass to compute the DGI loss.

        Parameters
        ----------
        graph : dgl.DGLGraph
            The input graph.
        feats : torch.Tensor
            Node features.

        Returns
        -------
        torch.Tensor
            The DGI loss, computed as the sum of positive and negative sample losses.
        """
        positive = self.encoder(graph, feats, corrupt=False)  # Encode positive samples without corruption
        negative = self.encoder(graph, feats, corrupt=True)  # Encode negative samples with feature corruption
        summary = torch.sigmoid(
            positive.mean(dim=0)
        )  # Compute the graph summary vector by taking the mean of node embeddings
        positive = self.discriminator(positive, summary)  # Discriminate positive samples against the summary
        negative = self.discriminator(negative, summary)  # Discriminate negative samples against the summary
        l1 = self.loss(positive, torch.ones_like(positive))  # Compute the loss for positive samples
        l2 = self.loss(negative, torch.zeros_like(negative))  # Compute the loss for negative samples
        return l1 + l2  # Return the sum of both losses


class GCNEncoder(nn.Module):
    r"""
    A GCN-based encoder that applies graph convolutions to input features to produce node embeddings.

    Parameters
    ----------
    n_in_feats : int
        Number of input features per node.
    n_hidden : int
        Dimension of the hidden layers.
    n_layers : int
        Number of GNN layers in the encoder. Must be at least 2.
    p_drop : float
        Dropout rate for regularization.
    """

    def __init__(self, n_in_feats, n_hidden, n_layers, p_drop):
        super().__init__()
        assert n_layers >= 2, "The number of GNN layers must be at least 2."
        self.input_layer = GraphConv(
            n_in_feats, n_hidden, activation=nn.PReLU(n_hidden)
        )  # Input layer with PReLU activation
        self.hidden_layers = nn.ModuleList(
            [GraphConv(n_hidden, n_hidden, activation=nn.PReLU(n_hidden)) for _ in range(n_layers - 2)]
        )  # Define hidden layers with PReLU activation
        self.output_layer = GraphConv(n_hidden, n_hidden)  # Output layer without activation
        self.dropout = nn.Dropout(p=p_drop)  # Dropout layer for regularization

    def forward(self, graph, feat, corrupt=False):
        """
        Forward pass through the GCN encoder.

        Parameters
        ----------
        graph : dgl.DGLGraph
            The input graph.
        feat : torch.Tensor
            Node features.
        corrupt : bool, optional
            Whether to corrupt the node features by shuffling. Default is False.

        Returns
        -------
        torch.Tensor
            The node embeddings after passing through the GCN layers.
        """
        if corrupt:
            perm = torch.randperm(graph.num_nodes())  # Corrupt node features by shuffling them
            feat = feat[perm]
        feat = self.input_layer(graph, feat)  # Apply the input layer
        feat = self.dropout(feat)  # Apply dropout
        for hidden_layer in self.hidden_layers:
            feat = hidden_layer(graph, feat)  # Apply hidden layers
            feat = self.dropout(feat)  # Apply dropout after each hidden layer
        feat = self.output_layer(graph, feat)  # Apply the output layer
        return feat


class Discriminator(nn.Module):
    r"""
    Discriminator that distinguishes between real (positive) and corrupted (negative) embeddings.

    Parameters
    ----------
    n_hidden : int
        Dimension of the hidden layers, used for the bilinear transformation.
    """

    def __init__(self, n_hidden):
        super().__init__()
        self.weight = nn.Parameter(torch.Tensor(n_hidden, n_hidden))  # Define weights for bilinear transformation
        self.uniform_weight()  # Initialize the weights uniformly

    def uniform_weight(self):
        """
        Initialize weights uniformly within a specific bound.
        """
        bound = 1.0 / math.sqrt(self.weight.size(0))  # Compute the bound for uniform initialization
        self.weight.data.uniform_(-bound, bound)  # Apply uniform initialization

    def forward(self, feat, summary):
        """
        Forward pass through the discriminator.

        Parameters
        ----------
        feat : torch.Tensor
            Node embeddings.
        summary : torch.Tensor
            Summary vector of the graph.

        Returns
        -------
        torch.Tensor
            Discrimination score indicating how likely the embeddings are real.
        """
        feat = torch.matmul(feat, torch.matmul(self.weight, summary))  # Apply bilinear transformation
        return feat
