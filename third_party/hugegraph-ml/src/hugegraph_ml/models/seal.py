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

# pylint: disable=R1719,C0103,R0205,R1721.R1705,R0205,W0612

"""
SEAL

References
----------
Paper: https://arxiv.org/abs/1802.09691
Author's code: https://github.com/muhanzhang/SEAL
DGL code: https://github.com/dmlc/dgl/tree/master/examples/pytorch/seal
"""

import argparse
import logging
import os
import os.path as osp
import time
from copy import deepcopy

import dgl
import numpy as np
import torch
import torch.nn.functional as F
from dgl import NID, add_self_loop
from dgl.dataloading.negative_sampler import Uniform
from dgl.nn.pytorch import GraphConv, SAGEConv, SortPooling, SumPooling
from ogb.linkproppred import DglLinkPropPredDataset, Evaluator
from scipy.sparse.csgraph import shortest_path
from torch import nn
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm


class GCN(nn.Module):
    """
    GCN Model

    Attributes:
        num_layers(int): num of gcn layers
        hidden_units(int): num of hidden units
        gcn_type(str): type of gcn layer, 'gcn' for GraphConv and 'sage' for SAGEConv
        pooling_type(str): type of graph pooling to get subgraph representation
                           'sum' for sum pooling and 'center' for center pooling.
        node_attributes(Tensor, optional): node attribute
        edge_weights(Tensor, optional): edge weight
        node_embedding(Tensor, optional): pre-trained node embedding
        use_embedding(bool, optional): whether to use node embedding. Note that if 'use_embedding' is set True
                             and 'node_embedding' is None, will automatically randomly initialize node embedding.
        num_nodes(int, optional): num of nodes
        dropout(float, optional): dropout rate
        max_z(int, optional): default max vocab size of node labeling, default 1000.

    """

    def __init__(
        self,
        num_layers,
        hidden_units,
        gcn_type="gcn",
        pooling_type="sum",
        node_attributes=None,
        edge_weights=None,
        node_embedding=None,
        use_embedding=False,
        num_nodes=None,
        dropout=0.5,
        max_z=1000,
    ):
        super().__init__()
        self.num_layers = num_layers
        self.dropout = dropout
        self.pooling_type = pooling_type
        self.use_attribute = node_attributes is not None
        self.use_embedding = use_embedding
        self.use_edge_weight = edge_weights is not None

        self.z_embedding = nn.Embedding(max_z, hidden_units)
        if node_attributes is not None:
            self.node_attributes_lookup = nn.Embedding.from_pretrained(node_attributes)
            self.node_attributes_lookup.weight.requires_grad = False
        if edge_weights is not None:
            self.edge_weights_lookup = nn.Embedding.from_pretrained(edge_weights)
            self.edge_weights_lookup.weight.requires_grad = False
        if node_embedding is not None:
            self.node_embedding = nn.Embedding.from_pretrained(node_embedding)
            self.node_embedding.weight.requires_grad = False
        elif use_embedding:
            self.node_embedding = nn.Embedding(num_nodes, hidden_units)

        initial_dim = hidden_units
        if self.use_attribute:
            initial_dim += self.node_attributes_lookup.embedding_dim
        if self.use_embedding:
            initial_dim += self.node_embedding.embedding_dim

        self.layers = nn.ModuleList()
        if gcn_type == "gcn":
            self.layers.append(GraphConv(initial_dim, hidden_units, allow_zero_in_degree=True))
            for _ in range(num_layers - 1):
                self.layers.append(GraphConv(hidden_units, hidden_units, allow_zero_in_degree=True))
        elif gcn_type == "sage":
            self.layers.append(SAGEConv(initial_dim, hidden_units, aggregator_type="gcn"))
            for _ in range(num_layers - 1):
                self.layers.append(SAGEConv(hidden_units, hidden_units, aggregator_type="gcn"))
        else:
            raise ValueError("Gcn type error.")

        self.linear_1 = nn.Linear(hidden_units, hidden_units)
        self.linear_2 = nn.Linear(hidden_units, 1)
        if pooling_type != "sum":
            raise ValueError("Pooling type error.")
        self.pooling = SumPooling()

    def reset_parameters(self):
        for layer in self.layers:
            layer.reset_parameters()

    def forward(self, g, z, node_id=None, edge_id=None):
        """
        Args:
            g(DGLGraph): the graph
            z(Tensor): node labeling tensor, shape [N, 1]
            node_id(Tensor, optional): node id tensor, shape [N, 1]
            edge_id(Tensor, optional): edge id tensor, shape [E, 1]
        Returns:
            x(Tensor): output tensor

        """

        z_emb = self.z_embedding(z)

        if self.use_attribute:
            x = self.node_attributes_lookup(node_id)
            x = torch.cat([z_emb, x], 1)
        else:
            x = z_emb

        edge_weight = self.edge_weights_lookup(edge_id) if self.use_edge_weight else None

        if self.use_embedding:
            n_emb = self.node_embedding(node_id)
            x = torch.cat([x, n_emb], 1)

        for layer in self.layers[:-1]:
            x = layer(g, x, edge_weight=edge_weight)
            x = F.relu(x)
            x = F.dropout(x, p=self.dropout, training=self.training)
        x = self.layers[-1](g, x, edge_weight=edge_weight)

        x = self.pooling(g, x)
        x = F.relu(self.linear_1(x))
        F.dropout(x, p=self.dropout, training=self.training)
        x = self.linear_2(x)

        return x


class DGCNN(nn.Module):
    """
    An end-to-end deep learning architecture for graph classification.
    paper link: https://muhanzhang.github.io/papers/AAAI_2018_DGCNN.pdf

    Attributes:
        num_layers(int): num of gcn layers
        hidden_units(int): num of hidden units
        k(int, optional): The number of nodes to hold for each graph in SortPooling.
        gcn_type(str): type of gcn layer, 'gcn' for GraphConv and 'sage' for SAGEConv
        node_attributes(Tensor, optional): node attribute
        edge_weights(Tensor, optional): edge weight
        node_embedding(Tensor, optional): pre-trained node embedding
        use_embedding(bool, optional): whether to use node embedding. Note that if 'use_embedding' is set True
                             and 'node_embedding' is None, will automatically randomly initialize node embedding.
        num_nodes(int, optional): num of nodes
        dropout(float, optional): dropout rate
        max_z(int, optional): default max vocab size of node labeling, default 1000.
    """

    def __init__(
        self,
        num_layers,
        hidden_units,
        k=10,
        gcn_type="gcn",
        node_attributes=None,
        edge_weights=None,
        node_embedding=None,
        use_embedding=False,
        num_nodes=None,
        dropout=0.5,
        max_z=1000,
    ):
        super().__init__()
        self.num_layers = num_layers
        self.dropout = dropout
        self.use_attribute = node_attributes is not None
        self.use_embedding = use_embedding
        self.use_edge_weight = edge_weights is not None

        self.z_embedding = nn.Embedding(max_z, hidden_units)

        if node_attributes is not None:
            self.node_attributes_lookup = nn.Embedding.from_pretrained(node_attributes)
            self.node_attributes_lookup.weight.requires_grad = False
        if edge_weights is not None:
            self.edge_weights_lookup = nn.Embedding.from_pretrained(edge_weights)
            self.edge_weights_lookup.weight.requires_grad = False
        if node_embedding is not None:
            self.node_embedding = nn.Embedding.from_pretrained(node_embedding)
            self.node_embedding.weight.requires_grad = False
        elif use_embedding:
            self.node_embedding = nn.Embedding(num_nodes, hidden_units)

        initial_dim = hidden_units
        if self.use_attribute:
            initial_dim += self.node_attributes_lookup.embedding_dim
        if self.use_embedding:
            initial_dim += self.node_embedding.embedding_dim

        self.layers = nn.ModuleList()
        if gcn_type == "gcn":
            self.layers.append(GraphConv(initial_dim, hidden_units, allow_zero_in_degree=True))
            for _ in range(num_layers - 1):
                self.layers.append(GraphConv(hidden_units, hidden_units, allow_zero_in_degree=True))
            self.layers.append(GraphConv(hidden_units, 1, allow_zero_in_degree=True))
        elif gcn_type == "sage":
            self.layers.append(SAGEConv(initial_dim, hidden_units, aggregator_type="gcn"))
            for _ in range(num_layers - 1):
                self.layers.append(SAGEConv(hidden_units, hidden_units, aggregator_type="gcn"))
            self.layers.append(SAGEConv(hidden_units, 1, aggregator_type="gcn"))
        else:
            raise ValueError("Gcn type error.")

        self.pooling = SortPooling(k=k)
        conv1d_channels = [16, 32]
        total_latent_dim = hidden_units * num_layers + 1
        conv1d_kws = [total_latent_dim, 5]
        self.conv_1 = nn.Conv1d(1, conv1d_channels[0], conv1d_kws[0], conv1d_kws[0])
        self.maxpool1d = nn.MaxPool1d(2, 2)
        self.conv_2 = nn.Conv1d(conv1d_channels[0], conv1d_channels[1], conv1d_kws[1], 1)
        dense_dim = int((k - 2) / 2 + 1)
        dense_dim = (dense_dim - conv1d_kws[1] + 1) * conv1d_channels[1]
        self.linear_1 = nn.Linear(dense_dim, 128)
        self.linear_2 = nn.Linear(128, 1)

    def forward(self, g, z, node_id=None, edge_id=None):
        """
        Args:
            g(DGLGraph): the graph
            z(Tensor): node labeling tensor, shape [N, 1]
            node_id(Tensor, optional): node id tensor, shape [N, 1]
            edge_id(Tensor, optional): edge id tensor, shape [E, 1]
        Returns:
            x(Tensor): output tensor
        """
        z_emb = self.z_embedding(z)
        if self.use_attribute:
            x = self.node_attributes_lookup(node_id)
            x = torch.cat([z_emb, x], 1)
        else:
            x = z_emb
        edge_weight = self.edge_weights_lookup(edge_id) if self.use_edge_weight else None

        if self.use_embedding:
            n_emb = self.node_embedding(node_id)
            x = torch.cat([x, n_emb], 1)

        xs = [x]
        for layer in self.layers:
            out = torch.tanh(layer(g, xs[-1], edge_weight=edge_weight))
            xs += [out]

        x = torch.cat(xs[1:], dim=-1)

        # SortPooling
        x = self.pooling(g, x)
        x = x.unsqueeze(1)
        x = F.relu(self.conv_1(x))
        x = self.maxpool1d(x)
        x = F.relu(self.conv_2(x))
        x = x.view(x.size(0), -1)

        x = F.relu(self.linear_1(x))
        F.dropout(x, p=self.dropout, training=self.training)
        x = self.linear_2(x)

        return x


def parse_arguments():
    """
    Parse arguments
    """
    parser = argparse.ArgumentParser(description="SEAL")
    parser.add_argument("--dataset", type=str, default="ogbl-ddi")
    parser.add_argument("--gpu_id", type=int, default=0)
    parser.add_argument("--hop", type=int, default=1)
    parser.add_argument("--model", type=str, default="dgcnn")
    parser.add_argument("--gcn_type", type=str, default="gcn")
    parser.add_argument("--num_layers", type=int, default=3)
    parser.add_argument("--hidden_units", type=int, default=32)
    parser.add_argument("--sort_k", type=int, default=30)
    parser.add_argument("--pooling", type=str, default="sum")
    parser.add_argument("--dropout", type=str, default=0.5)
    parser.add_argument("--hits_k", type=int, default=50)
    parser.add_argument("--lr", type=float, default=0.0001)
    parser.add_argument("--neg_samples", type=int, default=1)
    parser.add_argument("--subsample_ratio", type=float, default=0.1)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--eval_steps", type=int, default=5)
    parser.add_argument("--num_workers", type=int, default=32)
    parser.add_argument("--random_seed", type=int, default=2021)
    parser.add_argument("--save_dir", type=str, default="./processed")
    args = parser.parse_args()

    return args


def load_ogb_dataset(dataset):
    """
    Load OGB dataset
    Args:
        dataset(str): name of dataset (ogbl-collab, ogbl-ddi, ogbl-citation)

    Returns:
        graph(DGLGraph): graph
        split_edge(dict): split edge

    """
    dataset = DglLinkPropPredDataset(name=dataset)
    split_edge = dataset.get_edge_split()
    graph = dataset[0]

    return graph, split_edge


def drnl_node_labeling(subgraph, src, dst):
    """
    Double Radius Node labeling
    d = r(i,u)+r(i,v)
    label = 1+ min(r(i,u),r(i,v))+ (d//2)*(d//2+d%2-1)
    Isolated nodes in subgraph will be set as zero.
    Extreme large graph may cause memory error.

    Args:
        subgraph(DGLGraph): The graph
        src(int): node id of one of src node in new subgraph
        dst(int): node id of one of dst node in new subgraph
    Returns:
        z(Tensor): node labeling tensor
    """
    adj = subgraph.adj_external().to_dense().numpy()
    src, dst = (dst, src) if src > dst else (src, dst)

    idx = list(range(src)) + list(range(src + 1, adj.shape[0]))
    adj_wo_src = adj[idx, :][:, idx]

    idx = list(range(dst)) + list(range(dst + 1, adj.shape[0]))
    adj_wo_dst = adj[idx, :][:, idx]

    dist2src = shortest_path(adj_wo_dst, directed=False, unweighted=True, indices=src)
    dist2src = np.insert(dist2src, dst, 0, axis=0)
    dist2src = torch.from_numpy(dist2src)

    dist2dst = shortest_path(adj_wo_src, directed=False, unweighted=True, indices=dst - 1)
    dist2dst = np.insert(dist2dst, src, 0, axis=0)
    dist2dst = torch.from_numpy(dist2dst)

    dist = dist2src + dist2dst
    dist_over_2, dist_mod_2 = dist // 2, dist % 2

    z = 1 + torch.min(dist2src, dist2dst)
    z += dist_over_2 * (dist_over_2 + dist_mod_2 - 1)
    z[src] = 1.0
    z[dst] = 1.0
    z[torch.isnan(z)] = 0.0

    return z.to(torch.long)


def evaluate_hits(name, pos_pred, neg_pred, K):
    """
    Compute hits
    Args:
        name(str): name of dataset
        pos_pred(Tensor): predict value of positive edges
        neg_pred(Tensor): predict value of negative edges
        K(int): num of hits

    Returns:
        hits(float): score of hits


    """
    evaluator = Evaluator(name)
    evaluator.K = K
    hits = evaluator.eval(
        {
            "y_pred_pos": pos_pred,
            "y_pred_neg": neg_pred,
        }
    )[f"hits@{K}"]

    return hits


class GraphDataSet(Dataset):
    """
    GraphDataset for torch DataLoader
    """

    def __init__(self, graph_list, tensor):
        self.graph_list = graph_list
        self.tensor = tensor

    def __len__(self):
        return len(self.graph_list)

    def __getitem__(self, index):
        return (self.graph_list[index], self.tensor[index])


class PosNegEdgesGenerator:
    """
    Generate positive and negative samples
    Attributes:
        g(dgl.DGLGraph): graph
        split_edge(dict): split edge
        neg_samples(int): num of negative samples per positive sample
        subsample_ratio(float): ratio of subsample
        shuffle(bool): if shuffle generated graph list
    """

    def __init__(self, g, split_edge, neg_samples=1, subsample_ratio=0.1, shuffle=True):
        self.neg_sampler = Uniform(neg_samples)
        self.subsample_ratio = subsample_ratio
        self.split_edge = split_edge
        self.g = g
        self.shuffle = shuffle

    def __call__(self, split_type):
        subsample_ratio = self.subsample_ratio if split_type == "train" else 1

        pos_edges = self.split_edge[split_type]["edge"]
        if split_type == "train":
            # Adding self loop in train avoids sampling the source node itself.
            g = add_self_loop(self.g)
            eids = g.edge_ids(pos_edges[:, 0], pos_edges[:, 1])
            neg_edges = torch.stack(self.neg_sampler(g, eids), dim=1)
        else:
            neg_edges = self.split_edge[split_type]["edge_neg"]
        pos_edges = self.subsample(pos_edges, subsample_ratio).long()
        neg_edges = self.subsample(neg_edges, subsample_ratio).long()

        edges = torch.cat([pos_edges, neg_edges])
        labels = torch.cat(
            [
                torch.ones(pos_edges.size(0), 1),
                torch.zeros(neg_edges.size(0), 1),
            ]
        )
        if self.shuffle:
            perm = torch.randperm(edges.size(0))
            edges = edges[perm]
            labels = labels[perm]
        return edges, labels

    def subsample(self, edges, subsample_ratio):
        """
        Subsample generated edges.
        Args:
            edges(Tensor): edges to subsample
            subsample_ratio(float): ratio of subsample

        Returns:
            edges(Tensor):  edges

        """

        num_edges = edges.size(0)
        perm = torch.randperm(num_edges)
        perm = perm[: int(subsample_ratio * num_edges)]
        edges = edges[perm]
        return edges


class EdgeDataSet(Dataset):
    """
    Assistant Dataset for speeding up the SEALSampler
    """

    def __init__(self, edges, labels, transform):
        self.edges = edges
        self.transform = transform
        self.labels = labels

    def __len__(self):
        return len(self.edges)

    def __getitem__(self, index):
        subgraph = self.transform(self.edges[index])
        return (subgraph, self.labels[index])


class SEALSampler:
    """
    Sampler for SEAL in paper(no-block version)
    The  strategy is to sample all the k-hop neighbors around the two target nodes.
    Attributes:
        graph(DGLGraph): The graph
        hop(int): num of hop
        num_workers(int): num of workers

    """

    def __init__(self, graph, hop=1, num_workers=32, print_fn=print):
        self.graph = graph
        self.hop = hop
        self.print_fn = print_fn
        self.num_workers = num_workers

    def sample_subgraph(self, target_nodes):
        """
        Args:
            target_nodes(Tensor): Tensor of two target nodes
        Returns:
            subgraph(DGLGraph): subgraph
        """
        sample_nodes = [target_nodes]
        frontiers = target_nodes

        for _ in range(self.hop):
            frontiers = self.graph.out_edges(frontiers)[1]
            frontiers = torch.unique(frontiers)
            sample_nodes.append(frontiers)

        sample_nodes = torch.cat(sample_nodes)
        sample_nodes = torch.unique(sample_nodes)
        subgraph = dgl.node_subgraph(self.graph, sample_nodes)

        # Each node should have unique node id in the new subgraph
        u_id = int(torch.nonzero(subgraph.ndata[NID] == int(target_nodes[0]), as_tuple=False))
        v_id = int(torch.nonzero(subgraph.ndata[NID] == int(target_nodes[1]), as_tuple=False))

        # remove link between target nodes in positive subgraphs.
        if subgraph.has_edges_between(u_id, v_id):
            link_id = subgraph.edge_ids(u_id, v_id, return_uv=True)[2]
            subgraph.remove_edges(link_id)
        if subgraph.has_edges_between(v_id, u_id):
            link_id = subgraph.edge_ids(v_id, u_id, return_uv=True)[2]
            subgraph.remove_edges(link_id)

        z = drnl_node_labeling(subgraph, u_id, v_id)
        subgraph.ndata["z"] = z

        return subgraph

    def _collate(self, batch):
        batch_graphs, batch_labels = map(list, zip(*batch, strict=False))

        batch_graphs = dgl.batch(batch_graphs)
        batch_labels = torch.stack(batch_labels)
        return batch_graphs, batch_labels

    def __call__(self, edges, labels):
        subgraph_list = []
        labels_list = []
        edge_dataset = EdgeDataSet(edges, labels, transform=self.sample_subgraph)
        self.print_fn(f"Using {self.num_workers} workers in sampling job.")
        sampler = DataLoader(
            edge_dataset,
            batch_size=32,
            num_workers=self.num_workers,
            shuffle=False,
            collate_fn=self._collate,
        )
        for subgraph, label in tqdm(sampler, ncols=100):
            label_copy = deepcopy(label)
            subgraph = dgl.unbatch(subgraph)

            del label
            subgraph_list += subgraph
            labels_list.append(label_copy)

        return subgraph_list, torch.cat(labels_list)


class SEALData:
    """
    1. Generate positive and negative samples
    2. Subgraph sampling

    Attributes:
        g(dgl.DGLGraph): graph
        split_edge(dict): split edge
        hop(int): num of hop
        neg_samples(int): num of negative samples per positive sample
        subsample_ratio(float): ratio of subsample
        use_coalesce(bool): True for coalesce graph. Graph with multi-edge need to coalesce
    """

    def __init__(
        self,
        g,
        split_edge,
        hop=1,
        neg_samples=1,
        subsample_ratio=1,
        prefix=None,
        save_dir=None,
        num_workers=32,
        shuffle=True,
        use_coalesce=True,
        print_fn=print,
    ):
        self.g = g
        self.hop = hop
        self.subsample_ratio = subsample_ratio
        self.prefix = prefix
        self.save_dir = save_dir
        self.print_fn = print_fn

        self.generator = PosNegEdgesGenerator(
            g=self.g,
            split_edge=split_edge,
            neg_samples=neg_samples,
            subsample_ratio=subsample_ratio,
            shuffle=shuffle,
        )
        if use_coalesce:
            for k, v in g.edata.items():
                g.edata[k] = v.float()  # dgl.to_simple() requires data is float
            self.g = dgl.to_simple(g, copy_ndata=True, copy_edata=True, aggregator="sum")

        self.ndata = dict(self.g.ndata.items())
        self.edata = dict(self.g.edata.items())
        self.g.ndata.clear()
        self.g.edata.clear()
        self.print_fn("Save ndata and edata in class.")
        self.print_fn("Clear ndata and edata in graph.")

        self.sampler = SEALSampler(graph=self.g, hop=hop, num_workers=num_workers, print_fn=print_fn)

    def __call__(self, split_type):
        subsample_ratio = self.subsample_ratio if split_type == "train" else 1

        path = osp.join(
            self.save_dir or "",
            f"{self.prefix}_{split_type}_{self.hop}-hop_{subsample_ratio}-subsample.bin",
        )

        if osp.exists(path):
            self.print_fn(f"Load existing processed {split_type} files")
            graph_list, data = dgl.load_graphs(path)
            dataset = GraphDataSet(graph_list, data["labels"])

        else:
            self.print_fn(f"Processed {split_type} files not exist.")

            edges, labels = self.generator(split_type)
            self.print_fn(f"Generate {edges.size(0)} edges totally.")

            graph_list, labels = self.sampler(edges, labels)
            dataset = GraphDataSet(graph_list, labels)
            dgl.save_graphs(path, graph_list, {"labels": labels})
            self.print_fn(f"Save preprocessed subgraph to {path}")
        return dataset


def _transform_log_level(str_level):
    if str_level == "info":
        return logging.INFO
    elif str_level == "warning":
        return logging.WARNING
    elif str_level == "critical":
        return logging.CRITICAL
    elif str_level == "debug":
        return logging.DEBUG
    elif str_level == "error":
        return logging.ERROR
    else:
        raise KeyError("Log level error")


class LightLogging:
    def __init__(self, log_path=None, log_name="lightlog", log_level="debug"):
        log_level = _transform_log_level(log_level)

        if log_path:
            if not log_path.endswith("/"):
                log_path += "/"
            if not os.path.exists(log_path):
                os.mkdir(log_path)

            if log_name.endswith("-") or log_name.endswith("_"):
                log_name = log_path + log_name + time.strftime("%Y-%m-%d-%H:%M", time.localtime(time.time())) + ".log"
            else:
                log_name = (
                    log_path + log_name + "_" + time.strftime("%Y-%m-%d-%H-%M", time.localtime(time.time())) + ".log"
                )

            logging.basicConfig(
                level=log_level,
                format="%(asctime)s %(levelname)s: %(message)s",
                datefmt="%Y-%m-%d-%H:%M",
                handlers=[
                    logging.FileHandler(log_name, mode="w"),
                    logging.StreamHandler(),
                ],
            )
            logging.info("Start Logging")
            logging.info("Log file path: %s", log_name)

        else:
            logging.basicConfig(
                level=log_level,
                format="%(asctime)s %(levelname)s: %(message)s",
                datefmt="%Y-%m-%d-%H:%M",
                handlers=[logging.StreamHandler()],
            )
            logging.info("Start Logging")

    def debug(self, msg):
        logging.debug(msg)

    def info(self, msg):
        logging.info(msg)

    def critical(self, msg):
        logging.critical(msg)

    def warning(self, msg):
        logging.warning(msg)

    def error(self, msg):
        logging.error(msg)


def data_prepare(graph, split_edge):
    seal_data = SEALData(
        g=graph,
        split_edge=split_edge,
        hop=1,
        neg_samples=1,
        subsample_ratio=0.1,
        use_coalesce=True,
        prefix="ogbl-collab",
        save_dir="./processed",
        num_workers=32,
        print_fn=print,
    )
    node_attribute = seal_data.ndata["feat"]
    edge_weight = seal_data.edata["weight"].float()
    return node_attribute, edge_weight
