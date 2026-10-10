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

# pylint: disable=R1728

import time

import numpy as np
import torch
from dgl import EID, NID, DGLGraph
from dgl.dataloading import GraphDataLoader
from torch.nn import BCEWithLogitsLoss
from tqdm import tqdm

from hugegraph_ml.models.seal import SEALData, evaluate_hits


class LinkPredictionSeal:
    def __init__(self, graph: DGLGraph, split_edge, model):
        self.graph = graph
        self._model = model
        self.split_edge = split_edge
        self._device = ""
        self.train_loader = None
        self.val_loader = None
        self.test_loader = None
        self.train_graphs = None
        self.data_prepare()

    def data_prepare(self):
        seal_data = SEALData(
            g=self.graph,
            split_edge=self.split_edge,
            hop=1,
            neg_samples=1,
            subsample_ratio=0.1,
            use_coalesce=True,
            prefix="ogbl-collab",
            save_dir="./processed",
            num_workers=32,
            print_fn=print,
        )
        train_data = seal_data("train")
        val_data = seal_data("valid")
        test_data = seal_data("test")
        self.train_graphs = len(train_data.graph_list)
        self.train_loader = GraphDataLoader(train_data, batch_size=32, num_workers=32)
        self.val_loader = GraphDataLoader(val_data, batch_size=32, num_workers=32)
        self.test_loader = GraphDataLoader(test_data, batch_size=32, num_workers=32)

    def _train(
        self,
        dataloader,
        loss_fn,
        optimizer,
        num_graphs=32,
        total_graphs=None,
    ):
        self._model.train()

        total_loss = 0
        for g, labels in tqdm(dataloader, ncols=100):
            g = g.to(self._device)
            labels = labels.to(self._device)
            optimizer.zero_grad()
            logits = self._model(g, g.ndata["z"], g.ndata[NID], g.edata[EID])
            loss = loss_fn(logits, labels)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * num_graphs
        return total_loss / total_graphs

    def train(
        self,
        lr: float = 1e-3,
        n_epochs: int = 200,
        gpu: int = -1,
    ):
        torch.manual_seed(2021)
        self._device = f"cuda:{gpu}" if gpu != -1 and torch.cuda.is_available() else "cpu"
        self._model.to(self._device)
        self.graph = self.graph.to(self._device)
        parameters = self._model.parameters()
        optimizer = torch.optim.Adam(parameters, lr=lr)
        loss_fn = BCEWithLogitsLoss()

        # train and evaluate loop
        summary_val = []
        summary_test = []
        for epoch in range(n_epochs):
            time.time()
            self._train(
                dataloader=self.train_loader,
                loss_fn=loss_fn,
                optimizer=optimizer,
                num_graphs=32,
                total_graphs=self.train_graphs,
            )
            time.time()
            if epoch % 5 == 0:
                val_pos_pred, val_neg_pred = self.evaluate(dataloader=self.val_loader)
                test_pos_pred, test_neg_pred = self.evaluate(dataloader=self.test_loader)

                val_metric = evaluate_hits("ogbl-collab", val_pos_pred, val_neg_pred, 50)
                test_metric = evaluate_hits("ogbl-collab", test_pos_pred, test_neg_pred, 50)
                time.time()
                summary_val.append(val_metric)
                summary_test.append(test_metric)
        summary_test = np.array(summary_test)

    @torch.no_grad()
    def evaluate(self, dataloader):
        self._model.eval()
        y_pred, y_true = [], []
        for g, labels in tqdm(dataloader, ncols=100):
            g = g.to(self._device)
            logits = self._model(g, g.ndata["z"], g.ndata[NID], g.edata[EID])
            y_pred.append(logits.view(-1).cpu())
            y_true.append(labels.view(-1).cpu().to(torch.float))
        y_pred, y_true = torch.cat(y_pred), torch.cat(y_true)
        pos_pred = y_pred[y_true == 1]
        neg_pred = y_pred[y_true == 0]
        return pos_pred, neg_pred
