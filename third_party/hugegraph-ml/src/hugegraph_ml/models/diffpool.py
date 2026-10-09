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
DiffPool (Differentiable Pooling)

References
----------
Paper: https://arxiv.org/abs/1806.08804
Author's code: https://github.com/RexYing/diffpool
Ref DGL code: https://github.com/dmlc/dgl/tree/master/examples/pytorch/diffpool
"""

import dgl
import numpy as np
import torch
import torch.nn.functional as F
from dgl.nn.pytorch import SAGEConv
from torch import nn


class DiffPool(nn.Module):
    def __init__(
        self,
        n_in_feats,
        n_out_feats,
        max_n_nodes,
        n_hidden=64,
        n_embedding=64,
        n_layers=3,
        dropout=0.0,
        n_pooling=1,
        aggregator_type="mean",
        pool_ratio=0.1,
        concat=False,
    ):
        super().__init__()
        self.link_pred = True
        self.concat = concat
        self.n_pooling = n_pooling
        self.link_pred_loss = []
        self.entropy_loss = []

        # list of GNN modules before the first diffpool operation
        self.gc_before_pool = nn.ModuleList()
        self.diffpool_layers = nn.ModuleList()

        # list of GNN modules, each list after one diffpool operation
        self.gc_after_pool = nn.ModuleList()
        self.assign_dim = int(max_n_nodes * pool_ratio)
        self.num_aggs = 1

        # constructing layers before diffpool
        assert n_layers >= 3, "n_layers too few"
        self.gc_before_pool.append(
            SAGEConv(n_in_feats, n_hidden, aggregator_type, feat_drop=dropout, activation=F.relu)
        )
        for _ in range(n_layers - 2):
            self.gc_before_pool.append(
                SAGEConv(n_hidden, n_hidden, aggregator_type, feat_drop=dropout, activation=F.relu)
            )
        self.gc_before_pool.append(SAGEConv(n_hidden, n_embedding, aggregator_type, feat_drop=dropout, activation=None))

        assign_dims = [self.assign_dim]
        pool_embedding_dim = n_hidden * (n_layers - 1) + n_embedding if self.concat else n_embedding

        self.first_diffpool_layer = _DiffPoolBatchedGraphLayer(
            pool_embedding_dim,
            self.assign_dim,
            n_hidden,
            dropout,
            aggregator_type,
            self.link_pred,
        )

        gc_after_per_pool = nn.ModuleList()
        for _ in range(n_layers - 1):
            gc_after_per_pool.append(_BatchedGraphSAGE(n_hidden, n_hidden))
        gc_after_per_pool.append(_BatchedGraphSAGE(n_hidden, n_embedding))
        self.gc_after_pool.append(gc_after_per_pool)

        self.assign_dim = int(self.assign_dim * pool_ratio)
        # each pooling module
        for _ in range(n_pooling - 1):
            self.diffpool_layers.append(_BatchedDiffPool(pool_embedding_dim, self.assign_dim, n_hidden, self.link_pred))
            gc_after_per_pool = nn.ModuleList()
            for _ in range(n_layers - 1):
                gc_after_per_pool.append(_BatchedGraphSAGE(n_hidden, n_hidden))
            gc_after_per_pool.append(_BatchedGraphSAGE(n_hidden, n_embedding))
            self.gc_after_pool.append(gc_after_per_pool)
            assign_dims.append(self.assign_dim)
            self.assign_dim = int(self.assign_dim * pool_ratio)

        # predicting layer
        if self.concat:
            self.pred_input_dim = pool_embedding_dim * self.num_aggs * (n_pooling + 1)
        else:
            self.pred_input_dim = n_embedding * self.num_aggs
        self.pred_layer = nn.Linear(self.pred_input_dim, n_out_feats)

        # weight initialization
        for m in self.modules():
            if isinstance(m, nn.Linear):
                m.weight.data = nn.init.xavier_uniform_(m.weight.data, gain=nn.init.calculate_gain("relu"))
                if m.bias is not None:
                    m.bias.data = nn.init.constant_(m.bias.data, 0.0)

    def forward(self, g, feat):
        self.link_pred_loss = []
        self.entropy_loss = []
        h = feat
        # node feature for assignment matrix computation is the same as the
        # original node feature

        out_all = []

        # we use GCN blocks to get an embedding first
        g_embedding = _gcn_forward(g, h, self.gc_before_pool, self.concat)

        g.ndata["h"] = g_embedding

        readout = dgl.sum_nodes(g, "h")
        out_all.append(readout)
        if self.num_aggs == 2:
            readout = dgl.max_nodes(g, "h")
            out_all.append(readout)

        adj, h = self.first_diffpool_layer(g, g_embedding)
        node_per_pool_graph = int(adj.size()[0] / len(g.batch_num_nodes()))

        h, adj = _batch2tensor(adj, h, node_per_pool_graph)
        h = _gcn_forward_tensorized(h, adj, self.gc_after_pool[0], self.concat)
        readout = torch.sum(h, dim=1)
        out_all.append(readout)
        if self.num_aggs == 2:
            readout, _ = torch.max(h, dim=1)
            out_all.append(readout)

        for i, diffpool_layer in enumerate(self.diffpool_layers):
            h, adj = diffpool_layer(h, adj)
            h = _gcn_forward_tensorized(h, adj, self.gc_after_pool[i + 1], self.concat)
            readout = torch.sum(h, dim=1)
            out_all.append(readout)
            if self.num_aggs == 2:
                readout, _ = torch.max(h, dim=1)
                out_all.append(readout)
        final_readout = torch.cat(out_all, dim=1) if self.concat or self.num_aggs > 1 else readout
        ypred = self.pred_layer(final_readout)
        return ypred

    def loss(self, pred, label):
        # softmax + CE
        criterion = nn.CrossEntropyLoss()
        loss = criterion(pred, label)
        for _, value in self.first_diffpool_layer.loss_log.items():
            loss += value
        for diffpool_layer in self.diffpool_layers:
            for _, value in diffpool_layer.loss_log.items():
                loss += value
        return loss


class _BatchedGraphSAGE(nn.Module):
    def __init__(self, n_feat_in, n_feat_out, mean=False, add_self=False):
        super().__init__()
        self.bn = None
        self.add_self = add_self
        self.mean = mean
        self.w = nn.Linear(n_feat_in, n_feat_out, bias=True)

        nn.init.xavier_uniform_(self.w.weight, gain=nn.init.calculate_gain("relu"))

    def forward(self, x, adj):
        num_node_per_graph = adj.size(1)
        self.bn = nn.BatchNorm1d(num_node_per_graph).to(adj.device)

        if self.add_self:
            adj = adj + torch.eye(num_node_per_graph).to(adj.device)

        if self.mean:
            adj = adj / adj.sum(-1, keepdim=True)

        h_k_n = torch.matmul(adj, x)
        h_k = self.w(h_k_n)
        h_k = F.normalize(h_k, dim=2, p=2)
        h_k = F.relu(h_k)
        if self.bn is not None:
            h_k = self.bn(h_k)
        return h_k


class _DiffPoolAssignment(nn.Module):
    def __init__(self, n_feat, n_next):
        super().__init__()
        self.assign_mat = _BatchedGraphSAGE(n_feat, n_next)

    def forward(self, x, adj):
        s_l_init = self.assign_mat(x, adj)
        s_l = F.softmax(s_l_init, dim=-1)
        return s_l


class _BatchedDiffPool(nn.Module):
    def __init__(self, n_feat, n_next, n_hid, link_pred=False, entropy=True):
        super().__init__()
        self.link_pred = link_pred
        self.link_pred_layer = _LinkPredLoss()
        self.embed = _BatchedGraphSAGE(n_feat, n_hid)
        self.assign = _DiffPoolAssignment(n_feat, n_next)
        self.reg_loss = nn.ModuleList([])
        self.loss_log = {}
        if link_pred:
            self.reg_loss.append(_LinkPredLoss())
        if entropy:
            self.reg_loss.append(_EntropyLoss())

    def forward(self, x, adj):
        z_l = self.embed(x, adj)
        s_l = self.assign(x, adj)
        x_next = torch.matmul(s_l.transpose(-1, -2), z_l)
        a_next = (s_l.transpose(-1, -2)).matmul(adj).matmul(s_l)

        for loss_layer in self.reg_loss:
            loss_name = str(type(loss_layer).__name__)
            self.loss_log[loss_name] = loss_layer(adj, a_next, s_l)
        return x_next, a_next


class _DiffPoolBatchedGraphLayer(nn.Module):
    def __init__(
        self,
        input_dim,
        assign_dim,
        output_feat_dim,
        dropout,
        aggregator_type,
        link_pred,
    ):
        super().__init__()
        self.embedding_dim = input_dim
        self.assign_dim = assign_dim
        self.hidden_dim = output_feat_dim
        self.link_pred = link_pred
        self.feat_gc = SAGEConv(
            input_dim,
            output_feat_dim,
            aggregator_type,
            feat_drop=dropout,
            activation=F.relu,
        )
        self.pool_gc = SAGEConv(
            input_dim,
            assign_dim,
            aggregator_type,
            feat_drop=dropout,
            activation=F.relu,
        )
        self.reg_loss = nn.ModuleList([])
        self.loss_log = {}
        self.reg_loss.append(_EntropyLoss())

    def forward(self, g, h):
        feat = self.feat_gc(g, h)  # size = (sum_N, F_out), sum_N is num of nodes in this batch
        device = feat.device
        assign_tensor = self.pool_gc(g, h)  # size = (sum_N, N_a), N_a is num of nodes in pooled graph.
        assign_tensor = F.softmax(assign_tensor, dim=1)
        assign_tensor = torch.split(assign_tensor, g.batch_num_nodes().tolist())
        assign_tensor = torch.block_diag(*assign_tensor)  # size = (sum_N, batch_size * N_a)

        h = torch.matmul(torch.t(assign_tensor), feat)
        adj = g.adj_external(transpose=True, ctx=device)
        adj_dense = adj.to_dense()
        adj_new = torch.mm(torch.t(assign_tensor), torch.mm(adj_dense, assign_tensor))

        if self.link_pred:
            current_lp_loss = torch.norm(adj_dense - torch.mm(assign_tensor, torch.t(assign_tensor))) / np.power(
                g.num_nodes(), 2
            )
            self.loss_log["LinkPredLoss"] = current_lp_loss

        for loss_layer in self.reg_loss:
            loss_name = str(type(loss_layer).__name__)
            self.loss_log[loss_name] = loss_layer(adj, adj_new, assign_tensor)

        return adj_new, h


class _EntropyLoss(nn.Module):
    # Return Scalar
    def forward(self, adj, a_next, s_l):
        entropy = (torch.distributions.Categorical(probs=s_l).entropy()).sum(-1).mean(-1)
        assert not torch.isnan(entropy)
        return entropy


class _LinkPredLoss(nn.Module):
    def forward(self, adj, a_next, s_l):
        link_pred_loss = (adj - s_l.matmul(s_l.transpose(-1, -2))).norm(dim=(1, 2))
        link_pred_loss = link_pred_loss / (adj.size(1) * adj.size(2))
        return link_pred_loss.mean()


def _batch2tensor(batch_adj, batch_feat, node_per_pool_graph):
    """
    transform a batched graph to batched adjacency tensor and node feature tensor
    """
    batch_size = int(batch_adj.size()[0] / node_per_pool_graph)
    adj_list = []
    feat_list = []
    for i in range(batch_size):
        start = i * node_per_pool_graph
        end = (i + 1) * node_per_pool_graph
        adj_list.append(batch_adj[start:end, start:end])
        feat_list.append(batch_feat[start:end, :])
    adj_list = [torch.unsqueeze(x, 0) for x in adj_list]
    feat_list = [torch.unsqueeze(x, 0) for x in feat_list]
    adj = torch.cat(adj_list, dim=0)
    feat = torch.cat(feat_list, dim=0)

    return feat, adj


def _masked_softmax(matrix, mask, dim=-1, memory_efficient=True, mask_fill_value=-1e32):
    """
    Code snippet contributed by AllenNLP (https://github.com/allenai/allennlp)
    """
    if mask is None:
        result = torch.nn.functional.softmax(matrix, dim=dim)
    else:
        mask = mask.float()
        while mask.dim() < matrix.dim():
            mask = mask.unsqueeze(1)
        if not memory_efficient:
            result = torch.nn.functional.softmax(matrix * mask, dim=dim)
            result = result * mask
            result = result / (result.sum(dim=dim, keepdim=True) + 1e-13)
        else:
            masked_matrix = matrix.masked_fill((1 - mask).byte(), mask_fill_value)
            result = torch.nn.functional.softmax(masked_matrix, dim=dim)
    return result


def _gcn_forward(g, h, gc_layers, cat=False):
    block_readout = []
    for gc_layer in gc_layers[:-1]:
        h = gc_layer(g, h)
        block_readout.append(h)
    h = gc_layers[-1](g, h)
    block_readout.append(h)
    block = torch.cat(block_readout, dim=1) if cat else h
    return block


def _gcn_forward_tensorized(h, adj, gc_layers, cat=False):
    block_readout = []
    for gc_layer in gc_layers:
        h = gc_layer(h, adj)
        block_readout.append(h)
    block = torch.cat(block_readout, dim=2) if cat else h
    return block
