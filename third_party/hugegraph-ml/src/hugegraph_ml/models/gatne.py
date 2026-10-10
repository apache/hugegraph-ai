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

# pylint: disable=R0205,C0200,R1732

"""
General Attributed Multiplex HeTerogeneous Network Embedding (GATNE)

References
----------
Paper: https://arxiv.org/abs/1905.01669
Author's code: https://github.com/THUDM/GATNE
DGL code: https://github.com/dmlc/dgl/tree/master/examples/pytorch/GATNE-T
"""

import math
import multiprocessing
import time
from functools import partial, reduce

import dgl
import dgl.function as fn
import numpy as np
import torch
import torch.nn.functional as F
from torch import nn
from torch.nn.parameter import Parameter


class NeighborSampler:
    def __init__(self, g, num_fanouts):
        self.g = g
        self.num_fanouts = num_fanouts

    def sample(self, pairs):
        heads, tails, types = zip(*pairs, strict=False)
        seeds, head_invmap = torch.unique(torch.LongTensor(heads), return_inverse=True)
        blocks = []
        for fanout in reversed(self.num_fanouts):
            sampled_graph = dgl.sampling.sample_neighbors(self.g, seeds, fanout)
            sampled_block = dgl.to_block(sampled_graph, seeds)
            seeds = sampled_block.srcdata[dgl.NID]
            blocks.insert(0, sampled_block)
        return (
            blocks,
            torch.LongTensor(head_invmap),
            torch.LongTensor(tails),
            torch.LongTensor(types),
        )


class DGLGATNE(nn.Module):
    def __init__(
        self,
        num_nodes,
        embedding_size,
        embedding_u_size,
        edge_types,
        edge_type_count,
        dim_a,
    ):
        super().__init__()
        self.num_nodes = num_nodes
        self.embedding_size = embedding_size
        self.embedding_u_size = embedding_u_size
        self.edge_types = edge_types
        self.edge_type_count = edge_type_count
        self.dim_a = dim_a

        self.node_embeddings = Parameter(torch.FloatTensor(num_nodes, embedding_size))
        self.node_type_embeddings = Parameter(torch.FloatTensor(num_nodes, edge_type_count, embedding_u_size))
        self.trans_weights = Parameter(torch.FloatTensor(edge_type_count, embedding_u_size, embedding_size))
        self.trans_weights_s1 = Parameter(torch.FloatTensor(edge_type_count, embedding_u_size, dim_a))
        self.trans_weights_s2 = Parameter(torch.FloatTensor(edge_type_count, dim_a, 1))

        self.reset_parameters()

    def reset_parameters(self):
        self.node_embeddings.data.uniform_(-1.0, 1.0)
        self.node_type_embeddings.data.uniform_(-1.0, 1.0)
        self.trans_weights.data.normal_(std=1.0 / math.sqrt(self.embedding_size))
        self.trans_weights_s1.data.normal_(std=1.0 / math.sqrt(self.embedding_size))
        self.trans_weights_s2.data.normal_(std=1.0 / math.sqrt(self.embedding_size))

    # embs: [batch_size, embedding_size]
    def forward(self, block):
        input_nodes = block.srcdata[dgl.NID]
        output_nodes = block.dstdata[dgl.NID]
        batch_size = block.number_of_dst_nodes()
        node_embed = self.node_embeddings
        node_type_embed = []

        with block.local_scope():
            for i in range(self.edge_type_count):
                edge_type = self.edge_types[i]
                block.srcdata[edge_type] = self.node_type_embeddings[input_nodes, i]
                block.dstdata[edge_type] = self.node_type_embeddings[output_nodes, i]
                block.update_all(
                    fn.copy_u(edge_type, "m"),
                    fn.sum("m", edge_type),  # pylint: disable=E1101
                    etype=edge_type,
                )
                node_type_embed.append(block.dstdata[edge_type])

            node_type_embed = torch.stack(node_type_embed, 1)
            tmp_node_type_embed = node_type_embed.unsqueeze(2).view(-1, 1, self.embedding_u_size)
            trans_w = (
                self.trans_weights.unsqueeze(0)
                .repeat(batch_size, 1, 1, 1)
                .view(-1, self.embedding_u_size, self.embedding_size)
            )
            trans_w_s1 = (
                self.trans_weights_s1.unsqueeze(0)
                .repeat(batch_size, 1, 1, 1)
                .view(-1, self.embedding_u_size, self.dim_a)
            )
            trans_w_s2 = self.trans_weights_s2.unsqueeze(0).repeat(batch_size, 1, 1, 1).view(-1, self.dim_a, 1)

            attention = (
                F.softmax(
                    torch.matmul(
                        torch.tanh(torch.matmul(tmp_node_type_embed, trans_w_s1)),
                        trans_w_s2,
                    )
                    .squeeze(2)
                    .view(-1, self.edge_type_count),
                    dim=1,
                )
                .unsqueeze(1)
                .repeat(1, self.edge_type_count, 1)
            )

            node_type_embed = torch.matmul(attention, node_type_embed).view(-1, 1, self.embedding_u_size)
            node_embed = node_embed[output_nodes].unsqueeze(1).repeat(1, self.edge_type_count, 1) + torch.matmul(
                node_type_embed, trans_w
            ).view(-1, self.edge_type_count, self.embedding_size)
            last_node_embed = F.normalize(node_embed, dim=2)

            return last_node_embed  # [batch_size, edge_type_count, embedding_size]


class NSLoss(nn.Module):
    def __init__(self, num_nodes, num_sampled, embedding_size):
        super().__init__()
        self.num_nodes = num_nodes
        self.num_sampled = num_sampled
        self.embedding_size = embedding_size
        self.weights = Parameter(torch.FloatTensor(num_nodes, embedding_size))
        # [ (log(i+2) - log(i+1)) / log(num_nodes + 1)]
        self.sample_weights = F.normalize(
            torch.Tensor([(math.log(k + 2) - math.log(k + 1)) / math.log(num_nodes + 1) for k in range(num_nodes)]),
            dim=0,
        )

        self.reset_parameters()

    def reset_parameters(self):
        self.weights.data.normal_(std=1.0 / math.sqrt(self.embedding_size))

    def forward(self, input, embs, label):
        n = input.shape[0]
        log_target = torch.log(torch.sigmoid(torch.sum(torch.mul(embs, self.weights[label]), 1)))
        negs = torch.multinomial(self.sample_weights, self.num_sampled * n, replacement=True).view(n, self.num_sampled)
        noise = torch.neg(self.weights[negs])
        sum_log_sampled = torch.sum(torch.log(torch.sigmoid(torch.bmm(noise, embs.unsqueeze(2)))), 1).squeeze()

        loss = log_target + sum_log_sampled
        return -loss.sum() / n


def generate_pairs_parallel(walks, skip_window=None, layer_id=None):
    pairs = []
    for walk in walks:
        walk = walk.tolist()
        for i in range(len(walk)):
            for j in range(1, skip_window + 1):
                if i - j >= 0:
                    pairs.append((walk[i], walk[i - j], layer_id))
                if i + j < len(walk):
                    pairs.append((walk[i], walk[i + j], layer_id))
    return pairs


def generate_pairs(all_walks, window_size, num_workers):
    # for each node, choose the first neighbor and second neighbor of it to form pairs
    # Get all worker processes
    time.time()

    # Start all worker processes
    pool = multiprocessing.Pool(processes=num_workers)
    pairs = []
    skip_window = window_size // 2
    for layer_id, walks in enumerate(all_walks):
        block_num = len(walks) // num_workers
        if block_num > 0:
            walks_list = [walks[i * block_num : min((i + 1) * block_num, len(walks))] for i in range(num_workers)]
        else:
            walks_list = [walks]
        tmp_result = pool.map(
            partial(
                generate_pairs_parallel,
                skip_window=skip_window,
                layer_id=layer_id,
            ),
            walks_list,
        )
        pairs += reduce(lambda x, y: x + y, tmp_result)

    pool.close()
    time.time()
    return np.array([list(pair) for pair in set(pairs)])


def construct_typenodes_from_graph(graph):
    nodes = []
    for etype in graph.etypes:
        edges = graph.edges(etype=etype)
        node1, node2 = edges
        node1_list = node1.cpu().numpy().tolist()
        node2_list = node2.cpu().numpy().tolist()
        tmp_nodes = list(set(node1_list + node2_list))
        nodes.append(tmp_nodes)
    return nodes
