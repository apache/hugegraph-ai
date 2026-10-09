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


from typing import Literal

import torch
from dgl import DGLGraph
from torch import nn
from tqdm import trange

from hugegraph_ml.utils.early_stopping import EarlyStopping


class NodeClassifyWithEdge:
    def __init__(self, graph: DGLGraph, model: nn.Module):
        self.graph = graph
        self._model = model
        self._device = ""
        self._early_stopping = None
        self._is_trained = False
        self._check_graph()

    def _check_graph(self):
        required_node_attrs = ["feat", "label", "train_mask", "val_mask", "test_mask"]
        for attr in required_node_attrs:
            if attr not in self.graph.ndata:
                raise ValueError(f"Graph is missing required node attribute '{attr}' in ndata.")
        required_edge_attrs = ["feat"]
        for attr in required_edge_attrs:
            if attr not in self.graph.edata:
                raise ValueError(f"Graph is missing required edge attribute '{attr}' in edata.")

    def _evaluate(self, edge_feats, node_feats, labels, mask):
        self._model.eval()
        labels = labels[mask]
        with torch.no_grad():
            logits = self._model.inference(self.graph, edge_feats, node_feats)[mask]
            loss = self._model.loss(logits, labels)
            _, predicted = torch.max(logits, dim=1)
            accuracy = (predicted == labels).sum().item() / len(labels)
        return {"accuracy": accuracy, "loss": loss.item()}

    def train(
        self,
        lr: float = 1e-3,
        weight_decay: float = 0,
        n_epochs: int = 200,
        patience: int = float("inf"),
        early_stopping_monitor: Literal["loss", "accuracy"] = "loss",
        gpu: int = -1,
    ):
        # Set device for training
        self._device = f"cuda:{gpu}" if gpu != -1 and torch.cuda.is_available() else "cpu"
        self._early_stopping = EarlyStopping(patience=patience, monitor=early_stopping_monitor)
        self._model.to(self._device)
        self.graph = self.graph.to(self._device)
        # Get node features, labels, masks and move to device
        edge_feats = self.graph.edata["feat"].to(self._device)
        node_feats = self.graph.ndata["feat"].to(self._device)
        labels = self.graph.ndata["label"].to(self._device)
        train_mask = self.graph.ndata["train_mask"].to(self._device)
        val_mask = self.graph.ndata["val_mask"].to(self._device)
        optimizer = torch.optim.Adam(self._model.parameters(), lr=lr, weight_decay=weight_decay)
        # Training model
        epochs = trange(n_epochs)
        for epoch in epochs:
            # train
            self._model.train()
            optimizer.zero_grad()
            # forward pass, get logits, compute loss
            logits = self._model(self.graph, edge_feats, node_feats)
            logits_train_masked = logits[train_mask]
            loss = self._model.loss(logits_train_masked, labels[train_mask])
            loss.backward()
            optimizer.step()
            # validation
            valid_metrics = self._evaluate(edge_feats, node_feats, labels, val_mask)
            # logs
            epochs.set_description(
                f"epoch {epoch} | train loss {loss.item():.4f} | val loss {valid_metrics['loss']:.4f}"
            )
            # early stopping
            self._early_stopping(valid_metrics[self._early_stopping.monitor], self._model)
            torch.cuda.empty_cache()
            if self._early_stopping.early_stop:
                break
        self._early_stopping.load_best_model(self._model)
        self._is_trained = True

    def evaluate(self):
        test_mask = self.graph.ndata["test_mask"].to(self._device)
        edge_feats = self.graph.edata["feat"].to(self._device)
        node_feats = self.graph.ndata["feat"].to(self._device)
        labels = self.graph.ndata["label"].to(self._device)
        metrics = self._evaluate(edge_feats, node_feats, labels, test_mask)
        return metrics
