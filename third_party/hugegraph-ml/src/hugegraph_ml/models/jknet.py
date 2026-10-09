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
Jumping Knowledge Network (JKNet)

References
----------
Paper: https://arxiv.org/abs/1806.03536
DGL code: https://github.com/dmlc/dgl/tree/master/examples/pytorch/jknet
"""

import dgl.function as fn
import torch.nn.functional as F
from dgl.nn.pytorch import GraphConv, JumpingKnowledge
from torch import nn


class JKNet(nn.Module):
    """
    Jumping Knowledge Network (JKNet) model for learning node representations on graphs.

    Parameters
    ----------
    n_in_feats : int
        Number of input features per node.
    n_hidden : int
        Number of hidden units in each GraphConv layer.
    n_out_feats : int
        Number of output features or classes.
    n_layers : int, optional
        Number of GraphConv layers. Default is 1.
    mode : str, optional
        Jumping Knowledge mode ('cat', 'max', 'lstm'). Default is "cat".
    dropout : float, optional
        Dropout rate applied after each GraphConv layer. Default is 0.0.
    """

    def __init__(self, n_in_feats, n_out_feats, n_hidden=32, n_layers=6, mode="cat", dropout=0.5):
        super().__init__()
        self.mode = mode
        self.dropout = nn.Dropout(dropout)  # Dropout layer to prevent overfitting

        self.layers = nn.ModuleList()  # List to hold GraphConv layers
        # Add the first GraphConv layer (input layer)
        self.layers.append(GraphConv(n_in_feats, n_hidden, activation=F.relu))
        # Add additional GraphConv layers (hidden layers)
        for _ in range(n_layers):
            self.layers.append(GraphConv(n_hidden, n_hidden, activation=F.relu))

        # Initialize Jumping Knowledge module
        if self.mode == "lstm":
            self.jump = JumpingKnowledge(mode, n_hidden, n_layers)  # JKNet with LSTM for aggregating representations
        else:
            # JKNet with concatenation or max pooling for aggregating representations
            self.jump = JumpingKnowledge(mode)

        # Adjust hidden size for concatenation mode
        if self.mode == "cat":
            # Multiply by (n_layers + 1) because all layer outputs are concatenated
            n_hidden = n_hidden * (n_layers + 1)

        # Output layer for final prediction
        self.output_layer = nn.Linear(n_hidden, n_out_feats)
        self.criterion = nn.CrossEntropyLoss()
        self.reset_params()  # Initialize the model parameters

    def reset_params(self):
        """
        Reset parameters of the model.
        """
        for layer in self.layers:
            layer.reset_parameters()  # Reset GraphConv layer parameters
        self.jump.reset_parameters()  # Reset JumpingKnowledge parameters
        self.output_layer.reset_parameters()  # Reset output layer parameters

    def loss(self, logits, labels):
        return self.criterion(logits, labels)

    def inference(self, graph, feats):
        return self.forward(graph, feats)

    def forward(self, graph, feats):
        """
        Forward pass through the JKNet model.

        Parameters
        ----------
        graph : dgl.DGLGraph
            The input graph.
        feats : torch.Tensor
            Node features.

        Returns
        -------
        torch.Tensor
            The final node representations or predictions.
        """
        hidden_representations = []
        for layer in self.layers:
            feats = self.dropout(layer(graph, feats))  # Apply GraphConv layer and dropout
            hidden_representations.append(feats)  # Collect hidden representations from each layer

        if self.mode == "lstm":
            self.jump.lstm.flatten_parameters()  # Flatten LSTM parameters for efficiency

        # Apply Jumping Knowledge to aggregate hidden representations
        graph.ndata["h"] = self.jump(hidden_representations)

        # Message passing: aggregate node information using sum operation
        graph.update_all(fn.copy_u("h", "m"), fn.sum("m", "h"))  # pylint: disable=no-member

        # Apply the output layer to the aggregated node features
        h = self.output_layer(graph.ndata["h"])

        return h  # Return the final node representations or predictions
