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

import dgl
import torch
from torch import nn
from tqdm import trange

from hugegraph_ml.data.hugegraph_dataset import HugeGraphDataset
from hugegraph_ml.utils.early_stopping import EarlyStopping


class GraphClassify:
    def __init__(self, dataset: HugeGraphDataset, model: nn.Module):
        self.dataset = dataset
        self._train_dataloader = None
        self._valid_dataloader = None
        self._test_dataloader = None
        self._model = model
        self._device = ""
        self._early_stopping = None

    def _evaluate(self, dataloader):
        self._model.eval()
        correct = 0
        total = 0
        total_loss = 0
        with torch.no_grad():
            for batched_graph, labels in dataloader:
                batched_graph = batched_graph.to(self._device)
                feats = torch.FloatTensor(batched_graph.ndata["feat"]).to(self._device)
                labels = torch.LongTensor(labels.long()).to(self._device)
                logits = self._model(batched_graph, feats)
                preds = torch.argmax(logits, dim=1)
                correct += (preds == labels).sum().item()
                total += labels.size(0)
                loss = self._model.loss(logits, labels)
                total_loss += loss.item()
            accuracy = correct / total
            loss = total_loss / total
        return {"accuracy": accuracy, "loss": loss}

    def train(
        self,
        batch_size: int = 20,
        lr: float = 1e-3,
        weight_decay: float = 0,
        n_epochs: int = 200,
        patience: int = float("inf"),
        early_stopping_monitor: Literal["loss", "accuracy"] = "loss",
        clip: float = 2.0,
        gpu: int = -1,
    ):
        self._device = f"cuda:{gpu}" if gpu != -1 and torch.cuda.is_available() else "cpu"
        self._early_stopping = EarlyStopping(patience=patience, monitor=early_stopping_monitor)
        self._model.to(self._device)
        # default 7-2-1 train-valid-test
        train_size = int(len(self.dataset) * 0.7)
        test_size = int(len(self.dataset) * 0.1)
        valid_size = len(self.dataset) - train_size - test_size
        train_dataset, val_dataset, test_dataset = torch.utils.data.random_split(
            self.dataset, (train_size, valid_size, test_size)
        )
        self._train_dataloader = dgl.dataloading.GraphDataLoader(train_dataset, batch_size=batch_size, shuffle=True)
        self._valid_dataloader = dgl.dataloading.GraphDataLoader(val_dataset, batch_size=batch_size, shuffle=False)
        self._test_dataloader = dgl.dataloading.GraphDataLoader(test_dataset, batch_size=batch_size, shuffle=False)

        optimizer = torch.optim.Adam(
            filter(lambda p: p.requires_grad, self._model.parameters()), lr=lr, weight_decay=weight_decay
        )
        epochs = trange(n_epochs)
        for epoch in epochs:
            self._model.train()
            correct = 0
            total = 0
            total_loss = 0
            for batched_graph, labels in self._train_dataloader:
                batched_graph = batched_graph.to(self._device)
                feats = torch.FloatTensor(batched_graph.ndata["feat"]).to(self._device)
                labels = torch.LongTensor(labels.long()).to(self._device)
                self._model.zero_grad()
                total += labels.size(0)
                logits = self._model(batched_graph, feats)
                preds = torch.argmax(logits, dim=1)
                correct += (preds == labels).sum().item()
                loss = self._model.loss(logits, labels)
                total_loss += loss.item()
                loss.backward()
                nn.utils.clip_grad_norm_(self._model.parameters(), clip)
                optimizer.step()
            train_acc = correct / total
            loss = total_loss / total
            # validation
            valid_metrics = self._evaluate(self._valid_dataloader)
            epochs.set_description(
                f"epoch {epoch} | train loss {loss:.4f} | val loss {valid_metrics['loss']:.4f} | "
                f"train acc {train_acc:.4f} | val acc {valid_metrics['accuracy']:.4f}"
            )
            # early stopping
            self._early_stopping(valid_metrics[self._early_stopping.monitor], self._model)
            if self._early_stopping.early_stop:
                break
        self._early_stopping.load_best_model(self._model)

    def evaluate(self):
        return self._evaluate(self._test_dataloader)
