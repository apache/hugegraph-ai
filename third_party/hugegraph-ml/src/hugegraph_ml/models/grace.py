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
GRACE (Graph Contrastive Learning)

References
----------
Paper: https://arxiv.org/abs/2006.04131
Author's code: https://github.com/CRIPAC-DIG/GRACE
DGL code: https://github.com/dmlc/dgl/tree/master/examples/pytorch/grace
"""

import dgl
import numpy as np
import torch
import torch.nn.functional as F
from dgl.nn.pytorch import GraphConv
from torch import nn


class GRACE(nn.Module):
    """
    GRACE model for graph representation learning via contrastive learning.

    Parameters
    ----------
    n_in_feats : int
        Number of input features per node.
    n_hidden : int
        Dimension of the hidden layers.
    n_out_feats : int
        Dimension of the output features.
    n_layers : int
        Number of GNN layers.
    act_fn : nn.Module
        Activation function used in each layer.
    temp : float
        Temperature parameter for contrastive loss, controls the sharpness of
        the similarity distribution.
    edges_removing_rate_1 : float
        Proportion of edges to remove when generating the first view of the graph.
    edges_removing_rate_2 : float
        Proportion of edges to remove when generating the second view of the graph.
    feats_masking_rate_1 : float
        Proportion of node features to mask when generating the first view of the graph.
    feats_masking_rate_2 : float
        Proportion of node features to mask when generating the second view of the graph.
    """

    def __init__(
        self,
        n_in_feats,
        n_hidden=128,
        n_out_feats=128,
        n_layers=2,
        act_fn=None,
        temp=0.4,
        edges_removing_rate_1=0.2,
        edges_removing_rate_2=0.4,
        feats_masking_rate_1=0.3,
        feats_masking_rate_2=0.4,
    ):
        super().__init__()
        self.encoder = GCN(n_in_feats, n_hidden, act_fn, n_layers)  # Initialize the GCN encoder
        # Initialize the MLP projector to map the encoded features to the contrastive space
        self.proj = MLP(n_hidden, n_out_feats)
        self.temp = temp  # Set the temperature for the contrastive loss
        self.edges_removing_rate_1 = edges_removing_rate_1  # Edge removal rate for the first view
        self.edges_removing_rate_2 = edges_removing_rate_2  # Edge removal rate for the second view
        self.feats_masking_rate_1 = feats_masking_rate_1  # Feature masking rate for the first view
        self.feats_masking_rate_2 = feats_masking_rate_2  # Feature masking rate for the second view

    @staticmethod
    def sim(z1, z2):
        """
        Compute the cosine similarity between two sets of node embeddings.

        Parameters
        ----------
        z1 : torch.Tensor
            Node embeddings from the first view.
        z2 : torch.Tensor
            Node embeddings from the second view.

        Returns
        -------
        torch.Tensor
            Cosine similarity matrix.
        """
        z1 = F.normalize(z1)  # Normalize the embeddings for the first view
        z2 = F.normalize(z2)  # Normalize the embeddings for the second view
        return torch.mm(z1, z2.t())  # Compute pairwise cosine similarity

    def sim_loss(self, z1, z2):
        """
        Compute the contrastive loss based on cosine similarity.

        Parameters
        ----------
        z1 : torch.Tensor
            Node embeddings from the first view.
        z2 : torch.Tensor
            Node embeddings from the second view.

        Returns
        -------
        torch.Tensor
            Contrastive loss for the input embeddings.
        """
        refl_sim = torch.exp(self.sim(z1, z1) / self.temp)  # Self-similarity within the first view
        between_sim = torch.exp(self.sim(z1, z2) / self.temp)  # Cross-similarity between the two views
        x1 = refl_sim.sum(1) + between_sim.sum(1) - refl_sim.diag()  # Summation of similarities
        loss = -torch.log(between_sim.diag() / x1)  # Compute the contrastive loss
        return loss

    def loss(self, z1, z2):
        """
        Compute the symmetric contrastive loss for both views.

        Parameters
        ----------
        z1 : torch.Tensor
            Node embeddings from the first view.
        z2 : torch.Tensor
            Node embeddings from the second view.

        Returns
        -------
        torch.Tensor
            Average symmetric contrastive loss.
        """
        l1 = self.sim_loss(z1=z1, z2=z2)  # Loss for the first view
        l2 = self.sim_loss(z1=z2, z2=z1)  # Loss for the second view (symmetry)
        return (l1 + l2).mean() * 0.5  # Average the loss for symmetry

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
        h = self.encoder(graph, feats)  # Encode the node features with GCN
        return h.detach()  # Detach from computation graph for evaluation

    def forward(self, graph, feats):
        """
        Perform the forward pass and compute the contrastive loss.

        Parameters
        ----------
        graph : dgl.DGLGraph
            The input graph.
        feats : torch.Tensor
            Node features.

        Returns
        -------
        torch.Tensor
            Contrastive loss between two views of the graph.
        """
        # Generate the first view
        graph1, feats1 = _generating_views(graph, feats, self.edges_removing_rate_1, self.feats_masking_rate_1)
        # Generate the second view
        graph2, feats2 = _generating_views(graph, feats, self.edges_removing_rate_2, self.feats_masking_rate_2)
        z1 = self.proj(self.encoder(graph1, feats1))  # Project the encoded features for the first view
        z2 = self.proj(self.encoder(graph2, feats2))  # Project the encoded features for the second view
        loss = self.loss(z1, z2)  # Compute the contrastive loss
        return loss


class GCN(nn.Module):
    """
    Graph Convolutional Network (GCN) for node feature transformation.

    Parameters
    ----------
    n_in_feats : int
        Number of input features per node.
    n_out_feats : int
        Number of output features per node.
    act_fn : nn.Module
        Activation function.
    n_layers : int
        Number of GCN layers.
    """

    def __init__(self, n_in_feats, n_out_feats, act_fn, n_layers=2):
        super().__init__()
        assert n_layers >= 2, "Number of layers should be at least 2."
        self.n_layers = n_layers  # Set the number of layers
        self.n_hidden = n_out_feats * 2  # Set the hidden dimension as twice the output dimension
        self.input_layer = GraphConv(n_in_feats, self.n_hidden, activation=act_fn)  # Define the input layer
        self.hidden_layers = nn.ModuleList(
            [GraphConv(self.n_hidden, self.n_hidden, activation=act_fn) for _ in range(n_layers - 2)]
        )  # Define the hidden layers
        self.output_layer = GraphConv(self.n_hidden, n_out_feats, activation=act_fn)  # Define the output layer

    def forward(self, graph, feat):
        """
        Forward pass through the GCN.

        Parameters
        ----------
        graph : dgl.DGLGraph
            The input graph.
        feat : torch.Tensor
            Node features.

        Returns
        -------
        torch.Tensor
            Transformed node features after passing through the GCN layers.
        """
        feat = self.input_layer(graph, feat)  # Apply graph convolution at the input layer
        for hidden_layer in self.hidden_layers:
            feat = hidden_layer(graph, feat)  # Apply graph convolution at each hidden layer
        return self.output_layer(graph, feat)  # Apply graph convolution at the output layer


class MLP(nn.Module):
    """
    A simple Multi-Layer Perceptron (MLP) for projecting node embeddings to a new space.

    Parameters
    ----------
    n_in_feats : int
        Number of input features.
    n_out_feats : int
        Number of output features.
    """

    def __init__(self, n_in_feats, n_out_feats):
        super().__init__()
        self.fc1 = nn.Linear(n_in_feats, n_out_feats)  # Define the first fully connected layer
        self.fc2 = nn.Linear(n_out_feats, n_out_feats)  # Define the second fully connected layer

    def forward(self, x):
        """
        Forward pass through the MLP.

        Parameters
        ----------
        x : torch.Tensor
            Input node embeddings.

        Returns
        -------
        torch.Tensor
            Projected node embeddings.
        """
        z = F.elu(self.fc1(x))  # Apply ELU activation after the first layer
        return self.fc2(z)  # Return the output of the second layer


def _generating_views(graph, feats, edges_removing_rate, feats_masking_rate):
    """
    Generate two different views of the graph by removing edges and masking node features.

    Parameters
    ----------
    graph : dgl.DGLGraph
        The input graph.
    feats : torch.Tensor
        Node features.
    edges_removing_rate : float
        Proportion of edges to remove.
    feats_masking_rate : float
        Proportion of node features to mask.

    Returns
    -------
    new_graph : dgl.DGLGraph
        The modified graph with some edges removed.
    masked_feats : torch.Tensor
        Node features with some values masked.
    """
    # Removing edges (RE)
    removing_edges_idx = _get_removing_edges_idx(graph, edges_removing_rate)  # Get the indices of edges to remove
    src = graph.edges()[0]  # Source nodes of the edges
    dst = graph.edges()[1]  # Destination nodes of the edges
    new_src = src[removing_edges_idx]  # New source nodes after edge removal
    new_dst = dst[removing_edges_idx]  # New destination nodes after edge removal
    new_graph = dgl.graph(
        (new_src, new_dst), num_nodes=graph.num_nodes(), device=graph.device
    )  # Create a new graph with the remaining edges
    new_graph = dgl.add_self_loop(new_graph)  # Add self-loops to the new graph

    # Masking node features (MF)
    masked_feats = _masking_node_feats(feats, feats_masking_rate)  # Mask node features

    return new_graph, masked_feats  # Return the modified graph and masked features


def _masking_node_feats(feats, masking_rate):
    """
    Mask node features by setting a certain proportion to zero.

    Parameters
    ----------
    feats : torch.Tensor
        Node features.
    masking_rate : float
        Proportion of features to mask.

    Returns
    -------
    torch.Tensor
        Node features with some values masked.
    """
    mask = torch.rand(feats.size(1), dtype=torch.float32, device=feats.device) < masking_rate  # Generate a random mask
    feats = feats.clone()  # Clone the features to avoid in-place modification
    feats[:, mask] = 0  # Set masked features to zero
    return feats  # Return the masked features


def _get_removing_edges_idx(graph, edges_removing_rate):
    """
    Generate the indices of edges to be removed from the graph.

    Parameters
    ----------
    graph : dgl.DGLGraph
        The input graph.
    edges_removing_rate : float
        Proportion of edges to remove.

    Returns
    -------
    torch.Tensor
        Indices of the edges to be removed.
    """
    n_edges = graph.num_edges()  # Total number of edges
    mask_rates = torch.FloatTensor(np.ones(n_edges) * edges_removing_rate)  # Generate mask rates for each edge
    masks = torch.bernoulli(1 - mask_rates)  # Generate a mask indicating which edges to keep
    mask_idx = masks.nonzero().squeeze(1)  # Get the indices of edges to keep
    return mask_idx  # Return the indices of edges to be removed
