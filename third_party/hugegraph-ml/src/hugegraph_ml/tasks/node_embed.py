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


import dgl
import torch
from dgl import DGLGraph
from torch import nn
from tqdm import trange

from hugegraph_ml.utils.early_stopping import EarlyStopping


class NodeEmbed:
    def __init__(self, graph: DGLGraph, model: nn.Module):
        self.graph = graph
        self._model = model
        self._device = ""
        self._early_stopping = None
        self._check_graph()

    def _check_graph(self):
        required_node_attrs = ["feat"]
        for attr in required_node_attrs:
            if attr not in self.graph.ndata:
                raise ValueError(f"Graph is missing required node attribute '{attr}' in ndata.")

    def train_and_embed(
        self,
        add_self_loop: bool = True,
        lr: float = 1e-3,
        weight_decay: float = 0,
        n_epochs: int = 200,
        patience: int = float("inf"),
        gpu: int = -1,
    ) -> DGLGraph:
        # Set device for training
        self._device = f"cuda:{gpu}" if gpu != -1 and torch.cuda.is_available() else "cpu"
        self._early_stopping = EarlyStopping(patience=patience)
        self._model = self._model.to(self._device)
        self.graph = self.graph.to(self._device)
        # Add self-loop if required
        if add_self_loop:
            self.graph = dgl.add_self_loop(self.graph)
        # Get node features and move to device
        feat = self.graph.ndata["feat"].to(self._device)
        optimizer = torch.optim.Adam(self._model.parameters(), lr=lr, weight_decay=weight_decay)
        # Training model
        epochs = trange(n_epochs)
        for epoch in epochs:
            self._model.train()
            optimizer.zero_grad()
            # Forward pass and compute loss
            loss = self._model(self.graph, feat)
            loss.backward()
            optimizer.step()
            # Log
            epochs.set_description(f"epoch {epoch} | train loss {loss.item():.4f}")
            # early stop
            self._early_stopping(loss.item(), self._model)
            torch.cuda.empty_cache()
            if self._early_stopping.early_stop:
                break
        self._early_stopping.load_best_model(self._model)
        embed_feat = self._model.get_embedding(self.graph, feat)
        self.graph.ndata["feat"] = embed_feat
        return self.graph
