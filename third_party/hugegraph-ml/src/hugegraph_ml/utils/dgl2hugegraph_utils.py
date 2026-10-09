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
# pylint: disable=too-many-statements
# pylint: disable=C0302,C0103,W1514,R1735,R1734,C0206

import json
import os

import dgl
import networkx as nx
import numpy as np
import pandas as pd
import scipy
import torch
from dgl.data import (
    CiteseerGraphDataset,
    CoraGraphDataset,
    GINDataset,
    LegacyTUDataset,
    PubmedGraphDataset,
    get_download_dir,
)
from dgl.data.utils import _get_dgl_url, download, load_graphs
from ogb.linkproppred import DglLinkPropPredDataset
from pyhugegraph.api.graph import GraphManager
from pyhugegraph.api.schema import SchemaManager
from pyhugegraph.client import PyHugeClient

MAX_BATCH_NUM = 500


def clear_all_data(
    url: str = "http://127.0.0.1:8080",
    graph: str = "hugegraph",
    user: str = "",
    pwd: str = "",
    graphspace: str | None = None,
):
    client: PyHugeClient = PyHugeClient(url=url, graph=graph, user=user, pwd=pwd, graphspace=graphspace)
    client.graphs().clear_graph_all_data()


def import_graph_from_dgl(
    dataset_name,
    url: str = "http://127.0.0.1:8080",
    graph: str = "hugegraph",
    user: str = "",
    pwd: str = "",
    graphspace: str | None = None,
):
    dataset_name = dataset_name.upper()
    if dataset_name == "CORA":
        dataset_dgl = CoraGraphDataset(verbose=False)
    elif dataset_name == "CITESEER":
        dataset_dgl = CiteseerGraphDataset(verbose=False)
    elif dataset_name == "PUBMED":
        dataset_dgl = PubmedGraphDataset(verbose=False)
    else:
        raise ValueError("dataset not supported")
    graph_dgl = dataset_dgl[0]

    client: PyHugeClient = PyHugeClient(url=url, graph=graph, user=user, pwd=pwd, graphspace=graphspace)
    client_schema: SchemaManager = client.schema()
    client_graph: GraphManager = client.graph()
    # create property schema
    client_schema.propertyKey("feat").asDouble().valueList().ifNotExist().create()
    client_schema.propertyKey("label").asLong().ifNotExist().create()
    client_schema.propertyKey("train_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("val_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("test_mask").asInt().ifNotExist().create()
    # check props and create vertex label
    vertex_label = f"{dataset_name}_vertex"
    all_props = ["feat", "label", "train_mask", "val_mask", "test_mask"]
    props = [p for p in all_props if p in graph_dgl.ndata]
    props_value = {}
    for p in props:
        props_value[p] = graph_dgl.ndata[p].tolist()
    client_schema.vertexLabel(vertex_label).useAutomaticId().properties(*props).ifNotExist().create()
    # add vertices for batch (note MAX_BATCH_NUM)
    idx_to_vertex_id = {}
    vdatas = []
    vidxs = []
    for idx in range(graph_dgl.number_of_nodes()):
        # extract props
        properties = {
            p: int(props_value[p][idx]) if isinstance(props_value[p][idx], bool) else props_value[p][idx] for p in props
        }
        vdata = [vertex_label, properties]
        vdatas.append(vdata)
        vidxs.append(idx)
        if len(vdatas) == MAX_BATCH_NUM:
            idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, vidxs))
            vdatas.clear()
            vidxs.clear()
    # add rest vertices
    if len(vdatas) > 0:
        idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, vidxs))

    # add edges for batch
    edge_label = f"{dataset_name}_edge"
    client_schema.edgeLabel(edge_label).sourceLabel(vertex_label).targetLabel(vertex_label).ifNotExist().create()
    edges_src, edges_dst = graph_dgl.edges()
    edatas = []
    for src, dst in zip(edges_src.numpy(), edges_dst.numpy(), strict=False):
        edata = [edge_label, idx_to_vertex_id[src], idx_to_vertex_id[dst], vertex_label, vertex_label, {}]
        edatas.append(edata)
        if len(edatas) == MAX_BATCH_NUM:
            _add_batch_edges(client_graph, edatas)
            edatas.clear()
    if len(edatas) > 0:
        _add_batch_edges(client_graph, edatas)


def import_graphs_from_dgl(
    dataset_name,
    url: str = "http://127.0.0.1:8080",
    graph: str = "hugegraph",
    user: str = "",
    pwd: str = "",
    graphspace: str | None = None,
):
    dataset_name = dataset_name.upper()
    # load dgl bultin dataset
    if dataset_name in ["ENZYMES", "DD"]:
        dataset_dgl = LegacyTUDataset(name=dataset_name)
    elif dataset_name in ["MUTAG", "COLLAB", "NCI1", "PROTEINS", "PTC"]:
        dataset_dgl = GINDataset(name=dataset_name, self_loop=True)
    else:
        raise ValueError("dataset not supported")
    # hugegraph client
    client: PyHugeClient = PyHugeClient(url=url, graph=graph, user=user, pwd=pwd, graphspace=graphspace)
    client_schema: SchemaManager = client.schema()
    client_graph: GraphManager = client.graph()
    # define vertexLabel/edgeLabel
    graph_vertex_label = f"{dataset_name}_graph_vertex"
    vertex_label = f"{dataset_name}_vertex"
    edge_label = f"{dataset_name}_edge"
    # create schema
    client_schema.propertyKey("label").asLong().ifNotExist().create()
    client_schema.propertyKey("feat").asDouble().valueList().ifNotExist().create()
    client_schema.propertyKey("graph_id").asLong().ifNotExist().create()
    client_schema.vertexLabel(graph_vertex_label).useAutomaticId().properties("label").ifNotExist().create()
    client_schema.vertexLabel(vertex_label).useAutomaticId().properties("feat", "graph_id").ifNotExist().create()
    client_schema.edgeLabel(edge_label).sourceLabel(vertex_label).targetLabel(vertex_label).properties(
        "graph_id"
    ).ifNotExist().create()
    client_schema.indexLabel("vertex_by_graph_id").onV(vertex_label).by("graph_id").secondary().ifNotExist().create()
    client_schema.indexLabel("edge_by_graph_id").onE(edge_label).by("graph_id").secondary().ifNotExist().create()
    # import to hugegraph
    for graph_dgl, label in dataset_dgl:
        graph_vertex = client_graph.addVertex(label=graph_vertex_label, properties={"label": int(label)})
        # refine feat prop
        if "feat" in graph_dgl.ndata:
            node_feats = graph_dgl.ndata["feat"]
        elif "attr" in graph_dgl.ndata:
            node_feats = graph_dgl.ndata["attr"]
        else:
            raise ValueError("Node feature is empty")
        # add vertices of graph i for barch
        idx_to_vertex_id = {}
        vdatas = []
        vidxs = []
        for idx in range(graph_dgl.number_of_nodes()):
            feat = node_feats[idx].tolist()
            properties = {"feat": feat, "graph_id": graph_vertex.id}
            vdata = [vertex_label, properties]
            vdatas.append(vdata)
            vidxs.append(idx)
            if len(vdatas) == MAX_BATCH_NUM:
                idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, vidxs))
                vdatas.clear()
                vidxs.clear()
        if len(vdatas) > 0:
            idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, vidxs))
        # add edges of graph i for barch
        srcs, dsts = graph_dgl.edges()
        edatas = []
        for src, dst in zip(srcs.numpy(), dsts.numpy(), strict=False):
            edata = [
                edge_label,
                idx_to_vertex_id[src],
                idx_to_vertex_id[dst],
                vertex_label,
                vertex_label,
                {"graph_id": graph_vertex.id},
            ]
            edatas.append(edata)
            if len(edatas) == MAX_BATCH_NUM:
                _add_batch_edges(client_graph, edatas)
                edatas.clear()
        if len(edatas) > 0:
            _add_batch_edges(client_graph, edatas)


def import_hetero_graph_from_dgl(
    dataset_name,
    url: str = "http://127.0.0.1:8080",
    graph: str = "hugegraph",
    user: str = "",
    pwd: str = "",
    graphspace: str | None = None,
):
    dataset_name = dataset_name.upper()
    if dataset_name == "ACM":
        hetero_graph = load_acm_raw()
    else:
        raise ValueError("dataset not supported")
    client: PyHugeClient = PyHugeClient(url=url, graph=graph, user=user, pwd=pwd, graphspace=graphspace)
    client_schema: SchemaManager = client.schema()
    client_graph: GraphManager = client.graph()

    client_schema.propertyKey("feat").asDouble().valueList().ifNotExist().create()
    client_schema.propertyKey("label").asLong().ifNotExist().create()
    client_schema.propertyKey("train_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("val_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("test_mask").asInt().ifNotExist().create()

    ntype_to_vertex_label = {}
    ntype_idx_to_vertex_id = {}
    for ntype in hetero_graph.ntypes:
        # create vertex schema
        vertex_label = f"{dataset_name}_{ntype}_v"
        ntype_to_vertex_label[ntype] = vertex_label
        all_props = ["feat", "label", "train_mask", "val_mask", "test_mask"]
        # check properties
        props = [p for p in all_props if p in hetero_graph.nodes[ntype].data]
        client_schema.vertexLabel(vertex_label).useAutomaticId().properties(*props).ifNotExist().create()
        props_value = {}
        for p in props:
            props_value[p] = hetero_graph.nodes[ntype].data[p].tolist()
        # add vertices for batch of ntype
        idx_to_vertex_id = {}
        vdatas = []
        idxs = []
        for idx in range(hetero_graph.number_of_nodes(ntype=ntype)):
            properties = {
                p: int(props_value[p][idx]) if isinstance(props_value[p][idx], bool) else props_value[p][idx]
                for p in props
            }
            vdata = [vertex_label, properties]
            vdatas.append(vdata)
            idxs.append(idx)
            if len(vdatas) == MAX_BATCH_NUM:
                idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, idxs))
                vdatas.clear()
                idxs.clear()
        if len(vdatas) > 0:
            idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, idxs))
        ntype_idx_to_vertex_id[ntype] = idx_to_vertex_id

    # add edges
    edatas = []
    for canonical_etype in hetero_graph.canonical_etypes:
        # create edge schema
        src_type, etype, dst_type = canonical_etype
        edge_label = f"{dataset_name}_{etype}_e"
        client_schema.edgeLabel(edge_label).sourceLabel(ntype_to_vertex_label[src_type]).targetLabel(
            ntype_to_vertex_label[dst_type]
        ).ifNotExist().create()
        # add edges for batch of canonical_etype
        srcs, dsts = hetero_graph.edges(etype=canonical_etype)
        for src, dst in zip(srcs.numpy(), dsts.numpy(), strict=False):
            edata = [
                edge_label,
                ntype_idx_to_vertex_id[src_type][src],
                ntype_idx_to_vertex_id[dst_type][dst],
                ntype_to_vertex_label[src_type],
                ntype_to_vertex_label[dst_type],
                {},
            ]
            edatas.append(edata)
            if len(edatas) == MAX_BATCH_NUM:
                _add_batch_edges(client_graph, edatas)
                edatas.clear()
    if len(edatas) > 0:
        _add_batch_edges(client_graph, edatas)


def import_hetero_graph_from_dgl_no_feat(
    dataset_name,
    url: str = "http://127.0.0.1:8080",
    graph: str = "hugegraph",
    user: str = "",
    pwd: str = "",
    graphspace: str | None = None,
):
    # dataset download from:
    # https://s3.us-west-2.amazonaws.com/dgl-data/dataset/recsys/GATNE/amazon.zip
    dataset_name = dataset_name.upper()
    if dataset_name == "AMAZONGATNE":
        hetero_graph = load_training_data_gatne()
    else:
        raise ValueError("dataset not supported")
    client: PyHugeClient = PyHugeClient(url=url, graph=graph, user=user, pwd=pwd, graphspace=graphspace)
    client_schema: SchemaManager = client.schema()
    client_graph: GraphManager = client.graph()

    ntype_to_vertex_label = {}
    ntype_idx_to_vertex_id = {}
    for ntype in hetero_graph.ntypes:
        # create vertex schema
        vertex_label = f"{dataset_name}_{ntype}_v"
        ntype_to_vertex_label[ntype] = vertex_label
        client_schema.vertexLabel(vertex_label).useAutomaticId().ifNotExist().create()
        # add vertices for batch of ntype
        idx_to_vertex_id = {}
        vdatas = []
        idxs = []
        for idx in range(hetero_graph.number_of_nodes(ntype=ntype)):
            properties = {}
            vdata = [vertex_label, properties]
            vdatas.append(vdata)
            idxs.append(idx)
            if len(vdatas) == MAX_BATCH_NUM:
                idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, idxs))
                vdatas.clear()
                idxs.clear()
        if len(vdatas) > 0:
            idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, idxs))
        ntype_idx_to_vertex_id[ntype] = idx_to_vertex_id

    # add edges
    edatas = []
    for canonical_etype in hetero_graph.canonical_etypes:
        # create edge schema
        src_type, etype, dst_type = canonical_etype
        edge_label = f"{dataset_name}_{etype}_e"
        client_schema.edgeLabel(edge_label).sourceLabel(ntype_to_vertex_label[src_type]).targetLabel(
            ntype_to_vertex_label[dst_type]
        ).ifNotExist().create()
        # add edges for batch of canonical_etype
        srcs, dsts = hetero_graph.edges(etype=canonical_etype)
        for src, dst in zip(srcs.numpy(), dsts.numpy(), strict=False):
            edata = [
                edge_label,
                ntype_idx_to_vertex_id[src_type][src],
                ntype_idx_to_vertex_id[dst_type][dst],
                ntype_to_vertex_label[src_type],
                ntype_to_vertex_label[dst_type],
                {},
            ]
            edatas.append(edata)
            if len(edatas) == MAX_BATCH_NUM:
                _add_batch_edges(client_graph, edatas)
                edatas.clear()
    if len(edatas) > 0:
        _add_batch_edges(client_graph, edatas)


def import_graph_from_nx(
    dataset_name,
    url: str = "http://127.0.0.1:8080",
    graph: str = "hugegraph",
    user: str = "",
    pwd: str = "",
    graphspace: str | None = None,
):
    dataset_name = dataset_name.upper()
    if dataset_name == "CAVEMAN":
        dataset = nx.connected_caveman_graph(20, 20)
    else:
        raise ValueError("dataset not supported")

    client: PyHugeClient = PyHugeClient(url=url, graph=graph, user=user, pwd=pwd, graphspace=graphspace)
    client_schema: SchemaManager = client.schema()
    client_graph: GraphManager = client.graph()
    # create property schema
    # check props and create vertex label
    vertex_label = f"{dataset_name}_vertex"
    client_schema.vertexLabel(vertex_label).useAutomaticId().ifNotExist().create()
    # add vertices for batch (note MAX_BATCH_NUM)
    idx_to_vertex_id = {}
    vdatas = []
    vidxs = []
    for idx in dataset.nodes:
        vdata = [vertex_label, {}]
        vdatas.append(vdata)
        vidxs.append(idx)
        if len(vdatas) == MAX_BATCH_NUM:
            idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, vidxs))
            vdatas.clear()
            vidxs.clear()
    # add rest vertices
    if len(vdatas) > 0:
        idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, vidxs))

    # add edges for batch
    edge_label = f"{dataset_name}_edge"
    client_schema.edgeLabel(edge_label).sourceLabel(vertex_label).targetLabel(vertex_label).ifNotExist().create()
    edatas = []
    for edge in dataset.edges:
        edata = [
            edge_label,
            idx_to_vertex_id[edge[0]],
            idx_to_vertex_id[edge[1]],
            vertex_label,
            vertex_label,
            {},
        ]
        edatas.append(edata)
        if len(edatas) == MAX_BATCH_NUM:
            _add_batch_edges(client_graph, edatas)
            edatas.clear()
    if len(edatas) > 0:
        _add_batch_edges(client_graph, edatas)


def import_graph_from_dgl_with_edge_feat(
    dataset_name,
    url: str = "http://127.0.0.1:8080",
    graph: str = "hugegraph",
    user: str = "",
    pwd: str = "",
    graphspace: str | None = None,
):
    dataset_name = dataset_name.upper()
    if dataset_name == "CORA":
        dataset_dgl = CoraGraphDataset(verbose=False)
    elif dataset_name == "CITESEER":
        dataset_dgl = CiteseerGraphDataset(verbose=False)
    elif dataset_name == "PUBMED":
        dataset_dgl = PubmedGraphDataset(verbose=False)
    else:
        raise ValueError("dataset not supported")
    graph_dgl = dataset_dgl[0]

    client: PyHugeClient = PyHugeClient(url=url, graph=graph, user=user, pwd=pwd, graphspace=graphspace)
    client_schema: SchemaManager = client.schema()
    client_graph: GraphManager = client.graph()
    # create property schema
    client_schema.propertyKey("feat").asDouble().valueList().ifNotExist().create()  # node features
    client_schema.propertyKey("edge_feat").asDouble().valueList().ifNotExist().create()
    client_schema.propertyKey("label").asLong().ifNotExist().create()
    client_schema.propertyKey("train_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("val_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("test_mask").asInt().ifNotExist().create()
    # check props and create vertex label
    vertex_label = f"{dataset_name}_edge_feat_vertex"
    node_all_props = ["feat", "label", "train_mask", "val_mask", "test_mask"]
    node_props = [p for p in node_all_props if p in graph_dgl.ndata]
    node_props_value = {}
    for p in node_props:
        node_props_value[p] = graph_dgl.ndata[p].tolist()
    client_schema.vertexLabel(vertex_label).useAutomaticId().properties(*node_props).ifNotExist().create()
    # add vertices for batch (note MAX_BATCH_NUM)
    idx_to_vertex_id = {}
    vdatas = []
    vidxs = []
    for idx in range(graph_dgl.number_of_nodes()):
        # extract props
        properties = {
            p: (
                int(node_props_value[p][idx])
                if isinstance(node_props_value[p][idx], bool)
                else node_props_value[p][idx]
            )
            for p in node_props
        }
        vdata = [vertex_label, properties]
        vdatas.append(vdata)
        vidxs.append(idx)
        if len(vdatas) == MAX_BATCH_NUM:
            idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, vidxs))
            vdatas.clear()
            vidxs.clear()
    # add rest vertices
    if len(vdatas) > 0:
        idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, vidxs))

    # add edges for batch
    edge_label = f"{dataset_name}_edge_feat_edge"
    edge_all_props = ["edge_feat"]

    client_schema.edgeLabel(edge_label).sourceLabel(vertex_label).targetLabel(vertex_label).properties(
        *edge_all_props
    ).ifNotExist().create()
    edges_src, edges_dst = graph_dgl.edges()
    edatas = []
    for src, dst in zip(edges_src.numpy(), edges_dst.numpy(), strict=False):
        properties = {p: (torch.rand(8).tolist()) for p in edge_all_props}
        edata = [
            edge_label,
            idx_to_vertex_id[src],
            idx_to_vertex_id[dst],
            vertex_label,
            vertex_label,
            properties,
        ]
        edatas.append(edata)
        if len(edatas) == MAX_BATCH_NUM:
            _add_batch_edges(client_graph, edatas)
            edatas.clear()
    if len(edatas) > 0:
        _add_batch_edges(client_graph, edatas)


def import_graph_from_ogb(
    dataset_name,
    url: str = "http://127.0.0.1:8080",
    graph: str = "hugegraph",
    user: str = "",
    pwd: str = "",
    graphspace: str | None = None,
):
    if dataset_name == "ogbl-collab":
        dataset_dgl = DglLinkPropPredDataset(name=dataset_name)
    else:
        raise ValueError("dataset not supported")
    graph_dgl = dataset_dgl[0]

    client: PyHugeClient = PyHugeClient(url=url, graph=graph, user=user, pwd=pwd, graphspace=graphspace)
    client_schema: SchemaManager = client.schema()
    client_graph: GraphManager = client.graph()
    # create property schema
    client_schema.propertyKey("feat").asDouble().valueList().ifNotExist().create()  # node features
    client_schema.propertyKey("year").asDouble().valueList().ifNotExist().create()
    client_schema.propertyKey("weight").asDouble().valueList().ifNotExist().create()

    # check props and create vertex label
    vertex_label = f"{dataset_name}_vertex"
    node_all_props = ["feat"]
    node_props = [p for p in node_all_props if p in graph_dgl.ndata]
    node_props_value = {}
    for p in node_props:
        node_props_value[p] = graph_dgl.ndata[p].tolist()
    client_schema.vertexLabel(vertex_label).useAutomaticId().properties(*node_props).ifNotExist().create()

    # add vertices for batch (note MAX_BATCH_NUM)
    idx_to_vertex_id = {}
    vdatas = []
    vidxs = []
    max_nodes = 10000
    for idx in range(graph_dgl.number_of_nodes()):
        if idx <= max_nodes:
            # extract props
            properties = {
                p: (
                    int(node_props_value[p][idx])
                    if isinstance(node_props_value[p][idx], bool)
                    else node_props_value[p][idx]
                )
                for p in node_props
            }
            vdata = [vertex_label, properties]
            vdatas.append(vdata)
            vidxs.append(idx)
            if len(vdatas) == MAX_BATCH_NUM:
                idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, vidxs))
                vdatas.clear()
                vidxs.clear()
    # add rest vertices
    if len(vdatas) > 0:
        idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, vidxs))

    # add edges for batch
    edge_label = f"{dataset_name}_edge"
    edge_all_props = ["year", "weight"]
    edge_props_value = {}
    for p in edge_all_props:
        edge_props_value[p] = graph_dgl.edata[p].tolist()
    client_schema.edgeLabel(edge_label).sourceLabel(vertex_label).targetLabel(vertex_label).properties(
        *edge_all_props
    ).ifNotExist().create()
    edges_src, edges_dst = graph_dgl.edges()
    edatas = []
    for src, dst in zip(edges_src.numpy(), edges_dst.numpy(), strict=False):
        if src <= max_nodes and dst <= max_nodes:
            properties = {
                p: (
                    int(edge_props_value[p][idx])
                    if isinstance(edge_props_value[p][idx], bool)
                    else edge_props_value[p][idx]
                )
                for p in edge_all_props
            }
            edata = [
                edge_label,
                idx_to_vertex_id[src],
                idx_to_vertex_id[dst],
                vertex_label,
                vertex_label,
                properties,
            ]
            edatas.append(edata)
            if len(edatas) == MAX_BATCH_NUM:
                _add_batch_edges(client_graph, edatas)
                edatas.clear()
    if len(edatas) > 0:
        _add_batch_edges(client_graph, edatas)
    import_split_edge_from_ogb(
        dataset_name=dataset_name,
        idx_to_vertex_id=idx_to_vertex_id,
        max_nodes=max_nodes,
    )


def import_split_edge_from_ogb(
    dataset_name,
    idx_to_vertex_id,
    max_nodes: int,
    url: str = "http://127.0.0.1:8080",
    graph: str = "hugegraph",
    user: str = "",
    pwd: str = "",
    graphspace: str | None = None,
):
    if dataset_name == "ogbl-collab":
        dataset_dgl = DglLinkPropPredDataset(name=dataset_name)
    else:
        raise ValueError("dataset not supported")
    split_edges = dataset_dgl.get_edge_split()

    client: PyHugeClient = PyHugeClient(url=url, graph=graph, user=user, pwd=pwd, graphspace=graphspace)
    client_schema: SchemaManager = client.schema()
    client_graph: GraphManager = client.graph()
    # create property schema
    client_schema.propertyKey("train_edge_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("train_year_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("train_weight_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("valid_edge_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("valid_weight_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("valid_year_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("valid_edge_neg_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("test_edge_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("test_weight_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("test_year_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("test_edge_neg_mask").asInt().ifNotExist().create()
    edge_all_props = [
        "train_edge_mask",
        "train_year_mask",
        "train_weight_mask",
        "valid_edge_mask",
        "valid_weight_mask",
        "valid_year_mask",
        "valid_edge_neg_mask",
        "test_edge_mask",
        "test_weight_mask",
        "test_year_mask",
        "test_edge_neg_mask",
    ]
    edge_props = [
        "train_edge_mask",
        "valid_edge_mask",
        "valid_edge_neg_mask",
        "test_edge_mask",
        "test_edge_neg_mask",
    ]
    # add edges for batch
    vertex_label = f"{dataset_name}_vertex"
    edge_label = f"{dataset_name}_split_edge"
    client_schema.edgeLabel(edge_label).sourceLabel(vertex_label).targetLabel(vertex_label).properties(
        *edge_all_props
    ).ifNotExist().create()
    edges = {}
    edges["train_edge_mask"] = split_edges["train"]["edge"]
    edges["train_year_mask"] = split_edges["train"]["year"]
    edges["train_weight_mask"] = split_edges["train"]["weight"]
    edges["valid_edge_mask"] = split_edges["valid"]["edge"]
    edges["valid_weight_mask"] = split_edges["valid"]["weight"]
    edges["valid_year_mask"] = split_edges["valid"]["year"]
    edges["valid_edge_neg_mask"] = split_edges["valid"]["edge_neg"]
    edges["test_edge_mask"] = split_edges["test"]["edge"]
    edges["test_weight_mask"] = split_edges["test"]["weight"]
    edges["test_year_mask"] = split_edges["test"]["year"]
    edges["test_edge_neg_mask"] = split_edges["test"]["edge_neg"]
    init_ogb_split_edge(
        "train",
        "valid",
        "test",
        "",
        edges,
        max_nodes,
        edge_props,
        vertex_label,
        edge_label,
        idx_to_vertex_id,
        client_graph,
    )
    init_ogb_split_edge(
        "valid",
        "train",
        "test",
        "",
        edges,
        max_nodes,
        edge_props,
        vertex_label,
        edge_label,
        idx_to_vertex_id,
        client_graph,
    )
    init_ogb_split_edge(
        "valid",
        "train",
        "test",
        "neg_",
        edges,
        max_nodes,
        edge_props,
        vertex_label,
        edge_label,
        idx_to_vertex_id,
        client_graph,
    )
    init_ogb_split_edge(
        "test",
        "train",
        "valid",
        "",
        edges,
        max_nodes,
        edge_props,
        vertex_label,
        edge_label,
        idx_to_vertex_id,
        client_graph,
    )
    init_ogb_split_edge(
        "test",
        "train",
        "valid",
        "neg_",
        edges,
        max_nodes,
        edge_props,
        vertex_label,
        edge_label,
        idx_to_vertex_id,
        client_graph,
    )


def import_hetero_graph_from_dgl_bgnn(
    dataset_name,
    url: str = "http://127.0.0.1:8080",
    graph: str = "hugegraph",
    user: str = "",
    pwd: str = "",
    graphspace: str | None = None,
):
    # dataset download from : https://www.dropbox.com/s/verx1evkykzli88/datasets.zip
    # Extract zip folder in this directory
    dataset_name = dataset_name.upper()
    if dataset_name == "AVAZU":
        hetero_graph = read_input()
    else:
        raise ValueError("dataset not supported")
    client: PyHugeClient = PyHugeClient(url=url, graph=graph, user=user, pwd=pwd, graphspace=graphspace)
    client_schema: SchemaManager = client.schema()
    client_graph: GraphManager = client.graph()

    client_schema.propertyKey("feat").asInt().valueList().ifNotExist().create()
    client_schema.propertyKey("class").asDouble().valueList().ifNotExist().create()
    client_schema.propertyKey("cat_features").asInt().valueList().ifNotExist().create()
    client_schema.propertyKey("train_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("val_mask").asInt().ifNotExist().create()
    client_schema.propertyKey("test_mask").asInt().ifNotExist().create()

    ntype_to_vertex_label = {}
    ntype_idx_to_vertex_id = {}
    for ntype in hetero_graph.ntypes:
        # create vertex schema
        vertex_label = f"{dataset_name}_{ntype}_v"
        ntype_to_vertex_label[ntype] = vertex_label
        all_props = [
            "feat",
            "class",
            "cat_features",
            "train_mask",
            "val_mask",
            "test_mask",
        ]
        # check properties
        props = [p for p in all_props if p in hetero_graph.nodes[ntype].data]
        client_schema.vertexLabel(vertex_label).useAutomaticId().properties(*props).ifNotExist().create()
        props_value = {}
        for p in props:
            props_value[p] = hetero_graph.nodes[ntype].data[p].tolist()
        # add vertices for batch of ntype
        idx_to_vertex_id = {}
        vdatas = []
        idxs = []
        for idx in range(hetero_graph.number_of_nodes(ntype=ntype)):
            properties = {
                p: (int(props_value[p][idx]) if isinstance(props_value[p][idx], bool) else props_value[p][idx])
                for p in props
            }
            vdata = [vertex_label, properties]
            vdatas.append(vdata)
            idxs.append(idx)
            if len(vdatas) == MAX_BATCH_NUM:
                idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, idxs))
                vdatas.clear()
                idxs.clear()
        if len(vdatas) > 0:
            idx_to_vertex_id.update(_add_batch_vertices(client_graph, vdatas, idxs))
        ntype_idx_to_vertex_id[ntype] = idx_to_vertex_id

    # add edges
    edatas = []
    for canonical_etype in hetero_graph.canonical_etypes:
        # create edge schema
        src_type, etype, dst_type = canonical_etype
        edge_label = f"{dataset_name}_{etype}_e"
        client_schema.edgeLabel(edge_label).sourceLabel(ntype_to_vertex_label[src_type]).targetLabel(
            ntype_to_vertex_label[dst_type]
        ).ifNotExist().create()
        # add edges for batch of canonical_etype
        srcs, dsts = hetero_graph.edges(etype=canonical_etype)
        for src, dst in zip(srcs.numpy(), dsts.numpy(), strict=False):
            edata = [
                edge_label,
                ntype_idx_to_vertex_id[src_type][src],
                ntype_idx_to_vertex_id[dst_type][dst],
                ntype_to_vertex_label[src_type],
                ntype_to_vertex_label[dst_type],
                {},
            ]
            edatas.append(edata)
            if len(edatas) == MAX_BATCH_NUM:
                _add_batch_edges(client_graph, edatas)
                edatas.clear()
    if len(edatas) > 0:
        _add_batch_edges(client_graph, edatas)


def init_ogb_split_edge(
    a,
    b,
    c,
    d,
    edges,
    max_nodes,
    edge_props,
    vertex_label,
    edge_label,
    idx_to_vertex_id,
    client_graph,
):
    edatas = []
    for idx, edge in enumerate(edges[f"{a}_edge_{d}mask"]):
        if int(edge[0]) <= max_nodes and int(edge[1]) <= max_nodes:
            properties = {q: (int(q == f"{a}_edge_{d}mask")) for q in edge_props}
            if d != "neg_":
                properties2 = {
                    f"{a}_year_mask": int(edges[f"{a}_year_mask"][idx]),
                    f"{a}_weight_mask": int(edges[f"{a}_weight_mask"][idx]),
                }
                properties3 = {
                    f"{b}_year_mask": -1,
                    f"{b}_weight_mask": -1,
                    f"{c}_year_mask": -1,
                    f"{c}_weight_mask": -1,
                }
                properties.update(properties2)
                properties.update(properties3)
            else:
                properties2 = {
                    f"{a}_year_mask": -1,
                    f"{a}_weight_mask": -1,
                    f"{b}_year_mask": -1,
                    f"{b}_weight_mask": -1,
                    f"{c}_year_mask": -1,
                    f"{c}_weight_mask": -1,
                }
                properties.update(properties2)
            edata = [
                edge_label,
                idx_to_vertex_id[int(edge[0])],
                idx_to_vertex_id[int(edge[1])],
                vertex_label,
                vertex_label,
                properties,
            ]
            edatas.append(edata)
            if len(edatas) == MAX_BATCH_NUM:
                _add_batch_edges(client_graph, edatas)
                edatas.clear()
    if len(edatas) > 0:
        _add_batch_edges(client_graph, edatas)


def _add_batch_vertices(client_graph, vdatas, vidxs):
    vertices = client_graph.addVertices(vdatas)
    assert len(vertices) == len(vidxs)
    idx_to_vertex_id = {}
    for i, idx in enumerate(vidxs):
        idx_to_vertex_id[idx] = vertices[i].id
    return idx_to_vertex_id


def _add_batch_edges(client_graph, edatas):
    client_graph.addEdges(edatas)


def load_acm_raw():
    # reference: https://github.com/dmlc/dgl/blob/master/examples/pytorch/han/utils.py
    url = "dataset/ACM.mat"
    data_path = get_download_dir() + "/ACM.mat"
    if not os.path.exists(data_path):
        download(_get_dgl_url(url), path=data_path)

    data = scipy.io.loadmat(data_path)
    p_vs_l = data["PvsL"]  # paper-field?
    p_vs_a = data["PvsA"]  # paper-author
    p_vs_t = data["PvsT"]  # paper-term, bag of words
    p_vs_c = data["PvsC"]  # paper-conference, labels come from that

    # We assign
    # (1) KDD papers as class 0 (data mining),
    # (2) SIGMOD and VLDB papers as class 1 (database),
    # (3) SIGCOMM and MOBICOMM papers as class 2 (communication)
    conf_ids = [0, 1, 9, 10, 13]
    label_ids = [0, 1, 2, 2, 1]

    p_selected = p_vs_c[:, conf_ids].tocoo().row
    p_vs_l = p_vs_l[p_selected]
    p_vs_a = p_vs_a[p_selected]
    p_vs_t = p_vs_t[p_selected]
    p_vs_c = p_vs_c[p_selected]

    hgraph = dgl.heterograph(
        {
            ("paper", "pa", "author"): p_vs_a.nonzero(),
            ("author", "ap", "paper"): p_vs_a.transpose().nonzero(),
            ("paper", "pf", "field"): p_vs_l.nonzero(),
            ("field", "fp", "paper"): p_vs_l.transpose().nonzero(),
        }
    )

    features = torch.FloatTensor(p_vs_t.toarray())

    pc_p, pc_c = p_vs_c.nonzero()
    labels = np.zeros(len(p_selected), dtype=np.int64)
    for conf_id, label_id in zip(conf_ids, label_ids, strict=False):
        labels[pc_p[pc_c == conf_id]] = label_id
    labels = torch.LongTensor(labels)

    float_mask = np.zeros(len(pc_p))
    for conf_id in conf_ids:
        pc_c_mask = pc_c == conf_id
        float_mask[pc_c_mask] = np.random.permutation(np.linspace(0, 1, pc_c_mask.sum()))
    train_idx = np.where(float_mask <= 0.2)[0]
    val_idx = np.where((float_mask > 0.2) & (float_mask <= 0.3))[0]
    test_idx = np.where(float_mask > 0.3)[0]

    num_nodes = hgraph.num_nodes("paper")
    train_mask = _get_mask(num_nodes, train_idx)
    val_mask = _get_mask(num_nodes, val_idx)
    test_mask = _get_mask(num_nodes, test_idx)

    hgraph.nodes["paper"].data["feat"] = features
    hgraph.nodes["paper"].data["label"] = labels
    hgraph.nodes["paper"].data["train_mask"] = train_mask
    hgraph.nodes["paper"].data["val_mask"] = val_mask
    hgraph.nodes["paper"].data["test_mask"] = test_mask

    return hgraph


def read_input():
    # reference: https://github.com/dmlc/dgl/blob/master/examples/pytorch/bgnn/run.py
    # I added X, y, cat_features and masks into graph
    input_folder = "dataset/avazu"
    X = pd.read_csv(f"{input_folder}/X.csv")
    y = pd.read_csv(f"{input_folder}/y.csv")

    categorical_columns = []
    if os.path.exists(f"{input_folder}/cat_features.txt"):
        with open(f"{input_folder}/cat_features.txt") as f:
            for line in f:
                if line.strip():
                    categorical_columns.append(line.strip())

    cat_features = None
    if categorical_columns:
        columns = X.columns
        cat_features = np.where(columns.isin(categorical_columns))[0]

        for col in list(columns[cat_features]):
            X[col] = X[col].astype(str)

    gs, _ = load_graphs(f"{input_folder}/graph.dgl")
    graph = gs[0]

    with open(f"{input_folder}/masks.json") as f:
        masks = json.load(f)

    # add X
    features = [[int(x) for x in row] for row in X.values]
    features_tensor = torch.tensor(features, dtype=torch.int32)
    graph.ndata["feat"] = features_tensor

    # add y
    y_tensor = torch.tensor(y.values, dtype=torch.float64)
    graph.ndata["class"] = y_tensor

    # add masks
    for mask_name, node_ids in masks["0"].items():
        mask_tensor = torch.zeros(graph.number_of_nodes(), dtype=torch.int32)
        mask_tensor[node_ids] = 1
        graph.ndata[f"{mask_name}_mask"] = mask_tensor

    # add cat_features
    cat_features_tensor = torch.tensor(cat_features, dtype=torch.int32)
    graph.ndata["cat_features"] = torch.repeat_interleave(
        cat_features_tensor[None, :], repeats=graph.number_of_nodes(), dim=0
    )

    return graph


def load_training_data_gatne():
    # reference: https://github.com/dmlc/dgl/blob/master/examples/pytorch/GATNE-T/src/utils.py
    # reference: https://github.com/dmlc/dgl/blob/master/examples/pytorch/GATNE-T/src/main.py
    f_name = "dataset/amazon/train.txt"
    edge_data_by_type = {}
    with open(f_name) as f:
        for line in f:
            words = line[:-1].split(" ")  # line[-1] == '\n'
            if words[0] not in edge_data_by_type:
                edge_data_by_type[words[0]] = []
            x, y = words[1], words[2]
            edge_data_by_type[words[0]].append((x, y))
    nodes, index2word = [], []
    for edge_type in edge_data_by_type:
        node1, node2 = zip(*edge_data_by_type[edge_type], strict=False)
        index2word = index2word + list(node1) + list(node2)
    index2word = list(set(index2word))
    vocab = {}
    i = 0
    for word in index2word:
        vocab[word] = i
        i = i + 1
    for edge_type in edge_data_by_type:
        node1, node2 = zip(*edge_data_by_type[edge_type], strict=False)
        tmp_nodes = list(set(list(node1) + list(node2)))
        tmp_nodes = [vocab[word] for word in tmp_nodes]
        nodes.append(tmp_nodes)
    node_type = "_N"  # '_N' can be replaced by an arbitrary name
    data_dict = {}
    num_nodes_dict = {node_type: len(vocab)}
    for edge_type in edge_data_by_type:
        tmp_data = edge_data_by_type[edge_type]
        src = []
        dst = []
        for edge in tmp_data:
            src.extend([vocab[edge[0]], vocab[edge[1]]])
            dst.extend([vocab[edge[1]], vocab[edge[0]]])
        data_dict[(node_type, edge_type, node_type)] = (src, dst)
    graph = dgl.heterograph(data_dict, num_nodes_dict)
    return graph


def _get_mask(size, indices):
    mask = torch.zeros(size)
    mask[indices] = 1
    return mask.bool()


if __name__ == "__main__":
    clear_all_data()
    import_graph_from_dgl("CORA")
    import_graphs_from_dgl("MUTAG")
    import_hetero_graph_from_dgl("ACM")
    import_graph_from_nx("CAVEMAN")
    import_graph_from_dgl_with_edge_feat("CORA")
    import_graph_from_ogb("ogbl-collab")
    import_hetero_graph_from_dgl_bgnn("AVAZU")
    import_hetero_graph_from_dgl_no_feat("amazongatne")
