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


import random

import dgl
import torch
from torch import nn
from tqdm.auto import tqdm

from hugegraph_ml.models.gatne import (
    NeighborSampler,
    NSLoss,
    construct_typenodes_from_graph,
    generate_pairs,
)


class HeteroSampleEmbedGATNE:
    def __init__(self, graph, model: nn.Module):
        self.graph = graph
        self._model = model
        self._device = ""

    def train_and_embed(
        self,
        lr: float = 1e-3,
        n_epochs: int = 200,
        gpu: int = -1,
    ):
        self._device = f"cuda:{gpu}" if gpu != -1 and torch.cuda.is_available() else "cpu"
        self._model = self._model.to(self._device)
        self.graph = self.graph.to(self._device)
        type_nodes = construct_typenodes_from_graph(self.graph)
        edge_type_count = len(self.graph.etypes)
        neighbor_samples = 10
        num_walks = 20
        num_workers = 4
        window_size = 5
        batch_size = 64
        num_sampled = 5
        embedding_size = 200
        all_walks = []
        for i in range(edge_type_count):
            nodes = torch.LongTensor(type_nodes[i] * num_walks).to(self._device)
            traces, _ = dgl.sampling.random_walk(
                self.graph,
                nodes,
                metapath=[self.graph.etypes[i]] * (neighbor_samples - 1),
            )
            all_walks.append(traces)

        train_pairs = generate_pairs(all_walks, window_size, num_workers)
        neighbor_sampler = NeighborSampler(self.graph, [neighbor_samples])
        train_dataloader = torch.utils.data.DataLoader(
            train_pairs,
            batch_size=batch_size,
            collate_fn=neighbor_sampler.sample,
            shuffle=True,
            num_workers=num_workers,
            pin_memory=True,
        )
        nsloss = NSLoss(self.graph.number_of_nodes(), num_sampled, embedding_size)
        self._model.to(self._device)
        nsloss.to(self._device)

        optimizer = torch.optim.Adam(
            [{"params": self._model.parameters()}, {"params": nsloss.parameters()}],
            lr=lr,
        )

        for epoch in range(n_epochs):
            self._model.train()
            random.shuffle(train_pairs)

            data_iter = tqdm(
                train_dataloader,
                desc=f"epoch {epoch}",
                total=(len(train_pairs) + (batch_size - 1)) // batch_size,
            )
            avg_loss = 0.0
            for i, (block, head_invmap, tails, block_types) in enumerate(data_iter):
                optimizer.zero_grad()
                # embs: [batch_size, edge_type_count, embedding_size]
                block_types = block_types.to(self._device)
                embs = self._model(block[0].to(self._device))[head_invmap]
                embs = embs.gather(
                    1,
                    block_types.view(-1, 1, 1).expand(embs.shape[0], 1, embs.shape[2]),
                )[:, 0]
                loss = nsloss(
                    block[0].dstdata[dgl.NID][head_invmap].to(self._device),
                    embs,
                    tails.to(self._device),
                )
                loss.backward()
                optimizer.step()
                avg_loss += loss.item()

                post_fix = {
                    "epoch": epoch,
                    "iter": i,
                    "avg_loss": avg_loss / (i + 1),
                    "loss": loss.item(),
                }
                data_iter.set_postfix(post_fix)
