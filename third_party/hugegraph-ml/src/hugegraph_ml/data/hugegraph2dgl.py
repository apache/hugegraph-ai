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

# pylint: disable=too-many-branches
# pylint: disable=C0304

import warnings

import dgl
import networkx as nx
import torch
from pyhugegraph.api.gremlin import GremlinManager
from pyhugegraph.client import PyHugeClient

from hugegraph_ml.data.hugegraph_dataset import HugeGraphDataset


class HugeGraph2DGL:
    def __init__(
        self,
        url: str = "http://127.0.0.1:8080",
        graph: str = "hugegraph",
        user: str = "",
        pwd: str = "",
        graphspace: str | None = None,
    ):
        self._client: PyHugeClient = PyHugeClient(url=url, graph=graph, user=user, pwd=pwd, graphspace=graphspace)
        self._graph_germlin: GremlinManager = self._client.gremlin()

    def convert_graph(
        self,
        vertex_label: str,
        edge_label: str,
        feat_key: str = "feat",
        label_key: str = "label",
        mask_keys: list[str] | None = None,
    ):
        if mask_keys is None:
            mask_keys = ["train_mask", "val_mask", "test_mask"]
        vertices = self._graph_germlin.exec(f"g.V().hasLabel('{vertex_label}')")["data"]
        edges = self._graph_germlin.exec(f"g.E().hasLabel('{edge_label}')")["data"]
        graph_dgl = self._convert_graph_from_v_e(vertices, edges, feat_key, label_key, mask_keys)

        return graph_dgl

    def convert_hetero_graph(
        self,
        vertex_labels: list[str],
        edge_labels: list[str],
        feat_key: str = "feat",
        label_key: str = "label",
        mask_keys: list[str] | None = None,
    ):
        if mask_keys is None:
            mask_keys = ["train_mask", "val_mask", "test_mask"]
        vertex_label_id2idx = {}
        vertex_label_data = {}
        # for each vertex label
        for vertex_label in vertex_labels:
            vertices = self._graph_germlin.exec(f"g.V().hasLabel('{vertex_label}')")["data"]
            if len(vertices) == 0:
                warnings.warn(f"Graph has no vertices of vertex_label: {vertex_label}", Warning, stacklevel=2)
            else:
                vertex_ids = [v["id"] for v in vertices]
                id2idx = {vertex_id: idx for idx, vertex_id in enumerate(vertex_ids)}
                vertex_label_id2idx[vertex_label] = id2idx
                # extract vertex property(feat, label, mask)
                vertex_label_data[vertex_label] = {}
                if feat_key in vertices[0]["properties"]:
                    node_feats = torch.tensor([v["properties"][feat_key] for v in vertices], dtype=torch.float32)
                    vertex_label_data[vertex_label]["feat"] = node_feats
                if label_key in vertices[0]["properties"]:
                    node_labels = torch.tensor([v["properties"][label_key] for v in vertices], dtype=torch.long)
                    vertex_label_data[vertex_label]["label"] = node_labels
                if mask_keys:
                    for mk in mask_keys:
                        if mk in vertices[0]["properties"]:
                            mask = torch.tensor([v["properties"][mk] for v in vertices], dtype=torch.bool)
                            vertex_label_data[vertex_label][mk] = mask
        # build hetero graph from edges
        edge_data_dict = {}
        for edge_label in edge_labels:
            edges = self._graph_germlin.exec(f"g.E().hasLabel('{edge_label}')")["data"]
            if len(edges) == 0:
                warnings.warn(f"Graph has no edges of edge_label: {edge_label}", Warning, stacklevel=2)
            else:
                src_vertex_label = edges[0]["outVLabel"]
                src_idx = [vertex_label_id2idx[src_vertex_label][e["outV"]] for e in edges]
                dst_vertex_label = edges[0]["inVLabel"]
                dst_idx = [vertex_label_id2idx[dst_vertex_label][e["inV"]] for e in edges]
                edge_data_dict[(src_vertex_label, edge_label, dst_vertex_label)] = (src_idx, dst_idx)
        # add vertex properties data
        hetero_graph = dgl.heterograph(edge_data_dict)
        for vertex_label in vertex_labels:
            for prop in vertex_label_data[vertex_label]:
                hetero_graph.nodes[vertex_label].data[prop] = vertex_label_data[vertex_label][prop]

        return hetero_graph

    def convert_graph_dataset(
        self,
        graph_vertex_label: str,
        vertex_label: str,
        edge_label: str,
        feat_key: str = "feat",
        label_key: str = "label",
    ):
        # get graph vertices
        graph_vertices = self._graph_germlin.exec(f"g.V().hasLabel('{graph_vertex_label}')")["data"]
        graphs = []
        max_n_nodes = 0
        graph_labels = []
        for graph_vertex in graph_vertices:
            graph_id = graph_vertex["id"]
            label = graph_vertex["properties"][label_key]
            graph_labels.append(label)
            # get this graph's vertices and edges
            vertices = self._graph_germlin.exec(f"g.V().hasLabel('{vertex_label}').has('graph_id', {graph_id})")["data"]
            edges = self._graph_germlin.exec(f"g.E().hasLabel('{edge_label}').has('graph_id', {graph_id})")["data"]
            graph_dgl = self._convert_graph_from_v_e(vertices, edges, feat_key)
            graphs.append(graph_dgl)
            # record max num of node
            max_n_nodes = max(max_n_nodes, graph_dgl.number_of_nodes())
        # record dataset info
        graphs_info = {
            "n_graphs": len(graph_vertices),
            "max_n_nodes": max_n_nodes,
            "n_feat_dim": graphs[0].ndata["feat"].size()[1],
            "n_classes": len(set(graph_labels)),
        }
        dataset_dgl = HugeGraphDataset(graphs=graphs, labels=graph_labels, info=graphs_info)
        return dataset_dgl

    def convert_graph_nx(
        self,
        vertex_label: str,
        edge_label: str,
    ):
        vertices = self._graph_germlin.exec(f"g.V().hasLabel('{vertex_label}')")["data"]
        edges = self._graph_germlin.exec(f"g.E().hasLabel('{edge_label}')")["data"]
        graph_nx = self._convert_graph_from_v_e_nx(vertices=vertices, edges=edges)
        return graph_nx

    def convert_graph_with_edge_feat(
        self,
        vertex_label: str,
        edge_label: str,
        node_feat_key: str = "feat",
        edge_feat_key: str = "edge_feat",
        label_key: str = "label",
        mask_keys: list[str] | None = None,
    ):
        if mask_keys is None:
            mask_keys = ["train_mask", "val_mask", "test_mask"]
        vertices = self._graph_germlin.exec(f"g.V().hasLabel('{vertex_label}')")["data"]
        edges = self._graph_germlin.exec(f"g.E().hasLabel('{edge_label}')")["data"]
        graph_dgl = self._convert_graph_from_v_e_with_edge_feat(
            vertices, edges, edge_feat_key, node_feat_key, label_key, mask_keys
        )

        return graph_dgl

    def convert_graph_ogb(self, vertex_label: str, edge_label: str, split_label: str):
        vertices = self._graph_germlin.exec(f"g.V().hasLabel('{vertex_label}')")["data"]
        edges = self._graph_germlin.exec(f"g.E().hasLabel('{edge_label}')")["data"]
        graph_dgl, vertex_id_to_idx = self._convert_graph_from_ogb(vertices, edges, "feat", "year", "weight")
        edges_split = self._graph_germlin.exec(f"g.E().hasLabel('{split_label}')")["data"]
        split_edge = self._convert_split_edge_from_ogb(edges_split, vertex_id_to_idx)
        return graph_dgl, split_edge

    def convert_hetero_graph_bgnn(
        self,
        vertex_labels: list[str],
        edge_labels: list[str],
        feat_key: str = "feat",
        label_key: str = "class",
        cat_key: str = "cat_features",
        mask_keys: list[str] | None = None,
    ):
        if mask_keys is None:
            mask_keys = ["train_mask", "val_mask", "test_mask"]
        vertex_label_id2idx = {}
        vertex_label_data = {}
        # for each vertex label
        for vertex_label in vertex_labels:
            vertices = self._graph_germlin.exec(f"g.V().hasLabel('{vertex_label}')")["data"]
            if len(vertices) == 0:
                warnings.warn(f"Graph has no vertices of vertex_label: {vertex_label}", Warning, stacklevel=2)
            else:
                vertex_ids = [v["id"] for v in vertices]
                id2idx = {vertex_id: idx for idx, vertex_id in enumerate(vertex_ids)}
                vertex_label_id2idx[vertex_label] = id2idx
                # extract vertex property(feat, label, mask)
                vertex_label_data[vertex_label] = {}
                if feat_key in vertices[0]["properties"]:
                    node_feats = torch.tensor(
                        [v["properties"][feat_key] for v in vertices],
                        dtype=torch.int32,
                    )
                    vertex_label_data[vertex_label]["feat"] = node_feats
                if label_key in vertices[0]["properties"]:
                    node_labels = torch.tensor(
                        [v["properties"][label_key] for v in vertices],
                        dtype=torch.float64,
                    )
                    vertex_label_data[vertex_label]["class"] = node_labels
                if cat_key in vertices[0]["properties"]:
                    node_cat = torch.tensor(
                        [v["properties"][cat_key] for v in vertices],
                        dtype=torch.int32,
                    )
                    vertex_label_data[vertex_label]["cat_features"] = node_cat
                if mask_keys:
                    for mk in mask_keys:
                        if mk in vertices[0]["properties"]:
                            mask = torch.tensor(
                                [v["properties"][mk] for v in vertices],
                                dtype=torch.bool,
                            )
                            vertex_label_data[vertex_label][mk] = mask
        # build hetero graph from edges
        edge_data_dict = {}
        for edge_label in edge_labels:
            edges = self._graph_germlin.exec(f"g.E().hasLabel('{edge_label}')")["data"]
            if len(edges) == 0:
                warnings.warn(f"Graph has no edges of edge_label: {edge_label}", Warning, stacklevel=2)
            else:
                src_vertex_label = edges[0]["outVLabel"]
                src_idx = [vertex_label_id2idx[src_vertex_label][e["outV"]] for e in edges]
                dst_vertex_label = edges[0]["inVLabel"]
                dst_idx = [vertex_label_id2idx[dst_vertex_label][e["inV"]] for e in edges]
                edge_data_dict[(src_vertex_label, edge_label, dst_vertex_label)] = (
                    src_idx,
                    dst_idx,
                )
        # add vertex properties data
        hetero_graph = dgl.heterograph(edge_data_dict)
        for vertex_label in vertex_labels:
            for prop in vertex_label_data[vertex_label]:
                hetero_graph.nodes[vertex_label].data[prop] = vertex_label_data[vertex_label][prop]

        return hetero_graph

    @staticmethod
    def _convert_graph_from_v_e(vertices, edges, feat_key=None, label_key=None, mask_keys=None):
        if len(vertices) == 0:
            warnings.warn("This graph has no vertices", Warning, stacklevel=2)
            return dgl.graph(())
        vertex_ids = [v["id"] for v in vertices]
        vertex_id_to_idx = {vertex_id: idx for idx, vertex_id in enumerate(vertex_ids)}
        src_idx = [vertex_id_to_idx[e["outV"]] for e in edges]
        dst_idx = [vertex_id_to_idx[e["inV"]] for e in edges]
        graph_dgl = dgl.graph((src_idx, dst_idx))

        if feat_key and feat_key in vertices[0]["properties"]:
            node_feats = [v["properties"][feat_key] for v in vertices]
            graph_dgl.ndata["feat"] = torch.tensor(node_feats, dtype=torch.float32)
        if label_key and label_key in vertices[0]["properties"]:
            node_labels = [v["properties"][label_key] for v in vertices]
            graph_dgl.ndata["label"] = torch.tensor(node_labels, dtype=torch.long)
        if mask_keys:
            for mk in mask_keys:
                if mk in vertices[0]["properties"]:
                    node_masks = [v["properties"][mk] for v in vertices]
                    mask = torch.tensor(node_masks, dtype=torch.bool)
                    graph_dgl.ndata[mk] = mask
        return graph_dgl

    @staticmethod
    def _convert_graph_from_v_e_nx(vertices, edges):
        if len(vertices) == 0:
            warnings.warn("This graph has no vertices", Warning, stacklevel=2)
            return nx.Graph(())
        vertex_ids = [v["id"] for v in vertices]
        vertex_id_to_idx = {vertex_id: idx for idx, vertex_id in enumerate(vertex_ids)}
        new_vertex_ids = [vertex_id_to_idx[id] for id in vertex_ids]
        edge_list = [(edge["outV"], edge["inV"]) for edge in edges]
        new_edge_list = [(vertex_id_to_idx[src], vertex_id_to_idx[dst]) for src, dst in edge_list]
        graph_nx = nx.Graph()
        graph_nx.add_nodes_from(new_vertex_ids)
        graph_nx.add_edges_from(new_edge_list)
        return graph_nx

    @staticmethod
    def _convert_graph_from_v_e_with_edge_feat(
        vertices,
        edges,
        edge_feat_key,
        node_feat_key=None,
        label_key=None,
        mask_keys=None,
    ):
        if len(vertices) == 0:
            warnings.warn("This graph has no vertices", Warning, stacklevel=2)
            return dgl.graph(())
        vertex_ids = [v["id"] for v in vertices]
        vertex_id_to_idx = {vertex_id: idx for idx, vertex_id in enumerate(vertex_ids)}
        src_idx = [vertex_id_to_idx[e["outV"]] for e in edges]
        dst_idx = [vertex_id_to_idx[e["inV"]] for e in edges]
        graph_dgl = dgl.graph((src_idx, dst_idx))

        if node_feat_key and node_feat_key in vertices[0]["properties"]:
            node_feats = [v["properties"][node_feat_key] for v in vertices]
            graph_dgl.ndata["feat"] = torch.tensor(node_feats, dtype=torch.int64)
        if edge_feat_key and edge_feat_key in edges[0]["properties"]:
            edge_feats = [e["properties"][edge_feat_key] for e in edges]
            graph_dgl.edata["feat"] = torch.tensor(edge_feats, dtype=torch.int64)
        if label_key and label_key in vertices[0]["properties"]:
            node_labels = [v["properties"][label_key] for v in vertices]
            graph_dgl.ndata["label"] = torch.tensor(node_labels, dtype=torch.long)
        if mask_keys:
            for mk in mask_keys:
                if mk in vertices[0]["properties"]:
                    node_masks = [v["properties"][mk] for v in vertices]
                    mask = torch.tensor(node_masks, dtype=torch.bool)
                    graph_dgl.ndata[mk] = mask
        return graph_dgl

    @staticmethod
    def _convert_graph_from_ogb(vertices, edges, feat_key, year_key, weight_key):
        if len(vertices) == 0:
            warnings.warn("This graph has no vertices", Warning, stacklevel=2)
            return dgl.graph(())
        vertex_ids = [v["id"] for v in vertices]
        vertex_id_to_idx = {vertex_id: idx for idx, vertex_id in enumerate(vertex_ids)}
        src_idx = [vertex_id_to_idx[e["outV"]] for e in edges]
        dst_idx = [vertex_id_to_idx[e["inV"]] for e in edges]
        graph_dgl = dgl.graph((src_idx, dst_idx))
        if feat_key and feat_key in vertices[0]["properties"]:
            node_feats = [v["properties"][feat_key] for v in vertices[0 : graph_dgl.number_of_nodes()]]
            graph_dgl.ndata["feat"] = torch.tensor(node_feats, dtype=torch.float32)
        if year_key and year_key in edges[0]["properties"]:
            year = [e["properties"][year_key] for e in edges]
            graph_dgl.edata["year"] = torch.tensor(year, dtype=torch.int64)
        if weight_key and weight_key in edges[0]["properties"]:
            weight = [e["properties"][weight_key] for e in edges]
            graph_dgl.edata["weight"] = torch.tensor(weight, dtype=torch.int64)

        return graph_dgl, vertex_id_to_idx

    @staticmethod
    def _convert_split_edge_from_ogb(edges, vertex_id_to_idx):
        train_edge_list = []
        train_year_list = []
        train_weight_list = []
        valid_edge_list = []
        valid_year_list = []
        valid_weight_list = []
        valid_edge_neg_list = []
        test_edge_list = []
        test_year_list = []
        test_weight_list = []
        test_edge_neg_list = []

        for edge in edges:
            if edge["properties"]["train_edge_mask"] == 1:
                train_edge_list.append([vertex_id_to_idx[edge["outV"]], vertex_id_to_idx[edge["inV"]]])
            if edge["properties"]["train_year_mask"] != -1:
                train_year_list.append(edge["properties"]["train_year_mask"])
            if edge["properties"]["train_weight_mask"] != -1:
                train_weight_list.append(edge["properties"]["train_weight_mask"])

            if edge["properties"]["valid_edge_mask"] == 1:
                valid_edge_list.append([vertex_id_to_idx[edge["outV"]], vertex_id_to_idx[edge["inV"]]])
            if edge["properties"]["valid_year_mask"] != -1:
                valid_year_list.append(edge["properties"]["valid_year_mask"])
            if edge["properties"]["valid_weight_mask"] != -1:
                valid_weight_list.append(edge["properties"]["valid_weight_mask"])
            if edge["properties"]["valid_edge_neg_mask"] == 1:
                valid_edge_neg_list.append([vertex_id_to_idx[edge["outV"]], vertex_id_to_idx[edge["inV"]]])

            if edge["properties"]["test_edge_mask"] == 1:
                test_edge_list.append([vertex_id_to_idx[edge["outV"]], vertex_id_to_idx[edge["inV"]]])
            if edge["properties"]["test_year_mask"] != -1:
                test_year_list.append(edge["properties"]["test_year_mask"])
            if edge["properties"]["test_weight_mask"] != -1:
                test_weight_list.append(edge["properties"]["test_weight_mask"])
            if edge["properties"]["test_edge_neg_mask"] == 1:
                test_edge_neg_list.append([vertex_id_to_idx[edge["outV"]], vertex_id_to_idx[edge["inV"]]])

        split_edge = {
            "train": {
                "edge": torch.tensor(train_edge_list),
                "weight": torch.tensor(train_weight_list),
                "year": torch.tensor(train_year_list),
            },
            "valid": {
                "edge": torch.tensor(valid_edge_list),
                "weight": torch.tensor(valid_weight_list),
                "year": torch.tensor(valid_year_list),
                "edge_neg": torch.tensor(valid_edge_neg_list),
            },
            "test": {
                "edge": torch.tensor(test_edge_list),
                "weight": torch.tensor(test_weight_list),
                "year": torch.tensor(test_year_list),
                "edge_neg": torch.tensor(test_edge_neg_list),
            },
        }

        return split_edge


if __name__ == "__main__":
    hg2d = HugeGraph2DGL()
    hg2d.convert_graph(vertex_label="CORA_vertex", edge_label="CORA_edge")
    hg2d.convert_graph_dataset(
        graph_vertex_label="MUTAG_graph_vertex",
        vertex_label="MUTAG_vertex",
        edge_label="MUTAG_edge",
    )
    hg2d.convert_hetero_graph(
        vertex_labels=["ACM_paper_v", "ACM_author_v", "ACM_field_v"],
        edge_labels=["ACM_ap_e", "ACM_fp_e", "ACM_pa_e", "ACM_pf_e"],
    )
    hg2d.convert_graph_nx(vertex_label="CAVEMAN_vertex", edge_label="CAVEMAN_edge")
    hg2d.convert_graph_with_edge_feat(vertex_label="CORA_edge_feat_vertex", edge_label="CORA_edge_feat_edge")
    hg2d.convert_graph_ogb(
        vertex_label="ogbl-collab_vertex",
        edge_label="ogbl-collab_edge",
        split_label="ogbl-collab_split_edge",
    )
    hg2d.convert_hetero_graph_bgnn(vertex_labels=["AVAZU__N_v"], edge_labels=["AVAZU__E_e"])
    hg2d.convert_hetero_graph(
        vertex_labels=["AMAZONGATNE__N_v"],
        edge_labels=[
            "AMAZONGATNE_1_e",
            "AMAZONGATNE_2_e",
        ],
    )
