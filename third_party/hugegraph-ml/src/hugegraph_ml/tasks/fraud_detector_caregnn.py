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

# pylint: disable=E0401,C0301

import torch
from dgl import DGLGraph
from sklearn.metrics import recall_score, roc_auc_score
from torch import nn
from torch.nn.functional import softmax


class DetectorCaregnn:
    def __init__(self, graph: DGLGraph, model: nn.Module):
        self.graph = graph
        self._model = model
        self._device = ""

    def train(
        self,
        lr: float = 1e-3,
        weight_decay: float = 0,
        n_epochs: int = 200,
        gpu: int = -1,
    ):
        self._device = f"cuda:{gpu}" if gpu != -1 and torch.cuda.is_available() else "cpu"
        self._model.to(self._device)
        self.graph = self.graph.to(self._device)
        labels = self.graph.ndata["label"].to(self._device)
        feat = self.graph.ndata["feature"].to(self._device)
        train_mask = self.graph.ndata["train_mask"]
        val_mask = self.graph.ndata["val_mask"]
        train_idx = torch.nonzero(train_mask, as_tuple=False).squeeze(1).to(self._device)
        val_idx = torch.nonzero(val_mask, as_tuple=False).squeeze(1).to(self._device)
        rl_idx = torch.nonzero(train_mask.to(self._device) & labels.bool(), as_tuple=False).squeeze(1)
        _, cnt = torch.unique(labels, return_counts=True)
        loss_fn = torch.nn.CrossEntropyLoss(weight=1 / cnt)
        optimizer = torch.optim.Adam(self._model.parameters(), lr=lr, weight_decay=weight_decay)
        for _epoch in range(n_epochs):
            self._model.train()
            logits_gnn, logits_sim = self._model(self.graph, feat)
            tr_loss = loss_fn(logits_gnn[train_idx], labels[train_idx]) + 2 * loss_fn(
                logits_sim[train_idx], labels[train_idx]
            )

            recall_score(
                labels[train_idx].cpu(),
                logits_gnn.data[train_idx].argmax(dim=1).cpu(),
            )
            roc_auc_score(
                labels[train_idx].cpu(),
                softmax(logits_gnn, dim=1).data[train_idx][:, 1].cpu(),
            )
            loss_fn(logits_gnn[val_idx], labels[val_idx]) + 2 * loss_fn(logits_sim[val_idx], labels[val_idx])
            recall_score(labels[val_idx].cpu(), logits_gnn.data[val_idx].argmax(dim=1).cpu())
            roc_auc_score(
                labels[val_idx].cpu(),
                softmax(logits_gnn, dim=1).data[val_idx][:, 1].cpu(),
            )
            optimizer.zero_grad()
            tr_loss.backward()
            optimizer.step()
        self._model.RLModule(self.graph, _epoch, rl_idx)

    def evaluate(self):
        labels = self.graph.ndata["label"].to(self._device)
        feat = self.graph.ndata["feature"].to(self._device)
        test_mask = self.graph.ndata["test_mask"]
        test_idx = torch.nonzero(test_mask, as_tuple=False).squeeze(1).to(self._device)
        _, cnt = torch.unique(labels, return_counts=True)
        loss_fn = torch.nn.CrossEntropyLoss(weight=1 / cnt)
        self._model.eval()
        logits_gnn, logits_sim = self._model.forward(self.graph, feat)
        test_loss = loss_fn(logits_gnn[test_idx], labels[test_idx]) + 2 * loss_fn(
            logits_sim[test_idx], labels[test_idx]
        )
        test_recall = recall_score(labels[test_idx].cpu(), logits_gnn[test_idx].argmax(dim=1).cpu())
        test_auc = roc_auc_score(
            labels[test_idx].cpu(),
            softmax(logits_gnn, dim=1).data[test_idx][:, 1].cpu(),
        )
        return {"recall": test_recall, "accuracy": test_auc, "loss": test_loss.item()}
