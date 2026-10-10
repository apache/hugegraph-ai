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

import torch
from torch import nn


class MLPClassifier(nn.Module):
    r"""
    A simple Multi-Layer Perceptron (MLP) classifier for predicting node classes based on embeddings.

    Parameters
    ----------
    n_in_feat : int
        The size of the input feature dimension, representing the embedding size for each node.
    n_out_feat : int
        The number of output features, representing the number of classes to predict.
    n_hidden : int, optional
        The number of hidden units in the hidden layer (default is 512).
    """

    def __init__(self, n_in_feat, n_out_feat, n_hidden=512):
        super().__init__()
        # Define the first fully connected layer for projecting input features to hidden features.
        self.fc1 = nn.Linear(n_in_feat, n_hidden)
        # Define the second fully connected layer to project hidden features to output classes.
        self.fc2 = nn.Linear(n_hidden, n_out_feat)
        self.criterion = nn.CrossEntropyLoss()

    def loss(self, logits, labels):
        return self.criterion(logits, labels)

    def inference(self, graph, feats):
        return self.forward(graph, feats)

    def forward(self, graph, feats):
        r"""
        Forward pass for node classification.

        Parameters
        ----------
        graph : dgl.DGLGraph
            The input DGL graph. Currently unused in the computation but required for API consistency.
        feats : torch.Tensor
            Input node features or embeddings of shape (batch_size, n_in_feat).

        Returns
        -------
        torch.Tensor
            Logits of shape (batch_size, n_out_feat), representing the class scores for each node.
        """
        # Pass input features through the first layer with ReLU activation.
        feats = torch.relu(self.fc1(feats))
        # Pass the activated features through the second layer to obtain class logits.
        feats = self.fc2(feats)
        return feats
