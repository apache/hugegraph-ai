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

# pylint: disable=C0301

from typing import Literal

import dgl
import numpy as np
import torch
from dgl import DGLGraph
from torch import nn
from tqdm import trange

from hugegraph_ml.utils.early_stopping import EarlyStopping


class NodeClassifyWithSample:
    def __init__(self, graph: DGLGraph, model: nn.Module):
        self.graph = graph
        self._model = model
        self.gpu = -1
        self._device = "cpu"
        self._early_stopping = None
        self._is_trained = False
        self.num_partitions = 100
        self.batch_size = 100
        self.sampler = dgl.dataloading.ClusterGCNSampler(
            graph,
            self.num_partitions,
        )
        self.dataloader = dgl.dataloading.DataLoader(
            self.graph,
            torch.arange(self.num_partitions).to(self._device),
            self.sampler,
            device=self._device,
            batch_size=self.batch_size,
            shuffle=True,
            drop_last=False,
            num_workers=0,
            use_uva=False,
        )
        self._check_graph()

    def _check_graph(self):
        required_node_attrs = ["feat", "label", "train_mask", "val_mask", "test_mask"]
        for attr in required_node_attrs:
            if attr not in self.graph.ndata:
                raise ValueError(f"Graph is missing required node attribute '{attr}' in ndata.")

    def train(
        self,
        lr: float = 1e-3,
        weight_decay: float = 0,
        n_epochs: int = 200,
        patience: int = float("inf"),
        early_stopping_monitor: Literal["loss", "accuracy"] = "loss",
    ):
        # Set device for training
        early_stopping = EarlyStopping(patience=patience, monitor=early_stopping_monitor)
        self._model.to(self._device)
        # Get node features, labels, masks and move to device
        feats = self.graph.ndata["feat"].to(self._device)
        labels = self.graph.ndata["label"].to(self._device)
        train_mask = self.graph.ndata["train_mask"].to(self._device)
        val_mask = self.graph.ndata["val_mask"].to(self._device)
        optimizer = torch.optim.Adam(self._model.parameters(), lr=lr, weight_decay=weight_decay)
        # Training model
        loss_fn = nn.CrossEntropyLoss()
        epochs = trange(n_epochs)
        for epoch in epochs:
            # train
            self._model.train()
            for it, sg in enumerate(self.dataloader):
                sg_feats = feats[sg.ndata["_ID"]]
                sg_labels = labels[sg.ndata["_ID"]]
                sg_train_msak = train_mask[sg.ndata["_ID"]].bool()
                logits = self._model(sg, sg_feats)
                train_loss = loss_fn(logits[sg_train_msak], sg_labels[sg_train_msak])
                optimizer.zero_grad()
                train_loss.backward()
                optimizer.step()
                # validation
                valid_metrics = self.evaluate_sg(
                    sg=sg,
                    sg_feats=sg_feats,
                    labels=labels,
                    val_mask=val_mask,
                )
                # logs
                epochs.set_description(
                    f"epoch {epoch} | it {it} | train loss {train_loss.item():.4f} "
                    f"| val loss {valid_metrics['loss']:.4f}"
                )
                # early stopping
                early_stopping(valid_metrics[early_stopping.monitor], self._model)
                torch.cuda.empty_cache()
                if early_stopping.early_stop:
                    break
            early_stopping.load_best_model(self._model)

    def evaluate_sg(self, sg, sg_feats, labels, val_mask):
        self._model.eval()
        sg_val_msak = val_mask[sg.ndata["_ID"]].bool()
        sg_val_labels = labels[sg_val_msak]
        with torch.no_grad():
            sg_val_logits = self._model.inference(sg, sg_feats)[sg_val_msak]
            val_loss = self._model.loss(sg_val_logits, sg_val_labels)
            _, predicted = torch.max(sg_val_logits, dim=1)
            accuracy = (predicted == sg_val_labels).sum().item() / len(sg_val_labels)
        return {"accuracy": accuracy, "loss": val_loss.item()}

    def evaluate(self):
        test_mask = self.graph.ndata["test_mask"]
        feats = self.graph.ndata["feat"]
        labels = self.graph.ndata["label"]
        test_logits = []
        test_labels = []
        total_loss = 0
        with torch.no_grad():
            for _, sg in enumerate(self.dataloader):
                sg_feats = feats[sg.ndata["_ID"]]
                sg_labels = labels[sg.ndata["_ID"]]
                sg_test_msak = test_mask[sg.ndata["_ID"]].bool()
                sg_test_labels = sg_labels[sg_test_msak]
                sg_test_logits = self._model.inference(sg, sg_feats)[sg_test_msak]
                loss = self._model.loss(sg_test_logits, sg_test_labels)
                total_loss += loss
                test_logits.append(sg_test_logits)
                test_labels.append(sg_test_labels)
            test_logits = torch.tensor(np.vstack(test_logits))
            _, predicted = torch.max(test_logits, dim=1)
            accuracy = (predicted == test_labels[0]).sum().item() / len(test_labels[0])
        return {"accuracy": accuracy, "total_loss": total_loss.item()}
