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
"""OLTP: immediate neighbourhood, path and recommendation queries.

Use client.olap() for asynchronous full-graph computations.
"""

import json

from pyhugegraph.api.common import HugeParamsBase


class TraverserManager(HugeParamsBase):
    def k_out(
        self,
        source_id,
        max_depth,
        *,
        direction=None,
        label=None,
        nearest=None,
        count_only=None,
        max_degree=None,
        capacity=None,
        limit=None,
    ) -> dict:
        return self.request(
            "kout.get",
            params={
                "source": source_id,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "nearest": nearest,
                "count_only": count_only,
                "max_degree": max_degree,
                "capacity": capacity,
                "limit": limit,
            },
        )

    def k_neighbor(
        self, source_id, max_depth, *, direction=None, label=None, count_only=None, max_degree=None, limit=None
    ) -> dict:
        return self.request(
            "kneighbor.get",
            params={
                "source": source_id,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "count_only": count_only,
                "max_degree": max_degree,
                "limit": limit,
            },
        )

    def same_neighbors(self, vertex_id, other_id, *, direction=None, label=None, max_degree=None, limit=None) -> dict:
        return self.request(
            "same_neighbors.get",
            params={
                "vertex": vertex_id,
                "other": other_id,
                "direction": direction,
                "label": label,
                "max_degree": max_degree,
                "limit": limit,
            },
        )

    def jaccard_similarity(self, vertex_id, other_id, *, direction=None, label=None, max_degree=None) -> dict:
        return self.request(
            "jaccard_similarity.get",
            params={
                "vertex": vertex_id,
                "other": other_id,
                "direction": direction,
                "label": label,
                "max_degree": max_degree,
            },
        )

    def shortest_path(
        self,
        source_id,
        target_id,
        max_depth,
        *,
        direction=None,
        label=None,
        max_degree=None,
        skip_degree=None,
        with_vertex=None,
        with_edge=None,
        capacity=None,
    ) -> dict:
        return self.request(
            "shortest_path.get",
            params={
                "source": source_id,
                "target": target_id,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "max_degree": max_degree,
                "skip_degree": skip_degree,
                "with_vertex": with_vertex,
                "with_edge": with_edge,
                "capacity": capacity,
            },
        )

    def all_shortest_paths(
        self,
        source_id,
        target_id,
        max_depth,
        *,
        direction=None,
        label=None,
        max_degree=None,
        skip_degree=None,
        with_vertex=None,
        with_edge=None,
        capacity=None,
    ) -> dict:
        return self.request(
            "all_shortest_paths.get",
            params={
                "source": source_id,
                "target": target_id,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "max_degree": max_degree,
                "skip_degree": skip_degree,
                "with_vertex": with_vertex,
                "with_edge": with_edge,
                "capacity": capacity,
            },
        )

    def weighted_shortest_path(
        self,
        source_id,
        target_id,
        weight,
        *,
        direction=None,
        label=None,
        max_degree=None,
        skip_degree=None,
        with_vertex=None,
        with_edge=None,
        capacity=None,
    ) -> dict:
        return self.request(
            "weighted_shortest_path.get",
            params={
                "source": source_id,
                "target": target_id,
                "direction": direction,
                "label": label,
                "weight": weight,
                "max_degree": max_degree,
                "skip_degree": skip_degree,
                "with_vertex": with_vertex,
                "with_edge": with_edge,
                "capacity": capacity,
            },
        )

    def single_source_shortest_path(
        self,
        source_id,
        *,
        direction=None,
        label=None,
        weight=None,
        max_degree=None,
        skip_degree=None,
        with_vertex=None,
        with_edge=None,
        capacity=None,
        limit=None,
    ) -> dict:
        return self.request(
            "single_source_shortest_path.get",
            params={
                "source": source_id,
                "direction": direction,
                "label": label,
                "weight": weight,
                "max_degree": max_degree,
                "skip_degree": skip_degree,
                "with_vertex": with_vertex,
                "with_edge": with_edge,
                "capacity": capacity,
                "limit": limit,
            },
        )

    def paths(
        self, source_id, target_id, max_depth, *, direction=None, label=None, max_degree=None, capacity=None, limit=None
    ) -> dict:
        return self.request(
            "paths.get",
            params={
                "source": source_id,
                "target": target_id,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "max_degree": max_degree,
                "capacity": capacity,
                "limit": limit,
            },
        )

    def crosspoints(
        self, source_id, target_id, max_depth, *, direction=None, label=None, max_degree=None, capacity=None, limit=None
    ) -> dict:
        return self.request(
            "crosspoints.get",
            params={
                "source": source_id,
                "target": target_id,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "max_degree": max_degree,
                "capacity": capacity,
                "limit": limit,
            },
        )

    def rings(
        self,
        source_id,
        max_depth,
        *,
        direction=None,
        label=None,
        source_in_ring=None,
        max_degree=None,
        capacity=None,
        limit=None,
        with_vertex=None,
        with_edge=None,
    ) -> dict:
        return self.request(
            "rings.get",
            params={
                "source": source_id,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "source_in_ring": source_in_ring,
                "max_degree": max_degree,
                "capacity": capacity,
                "limit": limit,
                "with_vertex": with_vertex,
                "with_edge": with_edge,
            },
        )

    def rays(
        self,
        source_id,
        max_depth,
        *,
        direction=None,
        label=None,
        max_degree=None,
        capacity=None,
        limit=None,
        with_vertex=None,
        with_edge=None,
    ) -> dict:
        return self.request(
            "rays.get",
            params={
                "source": source_id,
                "direction": direction,
                "label": label,
                "max_depth": max_depth,
                "max_degree": max_degree,
                "capacity": capacity,
                "limit": limit,
                "with_vertex": with_vertex,
                "with_edge": with_edge,
            },
        )

    def adamic_adar(self, vertex_id, other_id, *, direction=None, label=None, max_degree=None, limit=None) -> dict:
        return self.request(
            "adamic_adar.get",
            params={
                "vertex": vertex_id,
                "other": other_id,
                "direction": direction,
                "label": label,
                "max_degree": max_degree,
                "limit": limit,
            },
        )

    def resource_allocation(
        self, vertex_id, other_id, *, direction=None, label=None, max_degree=None, limit=None
    ) -> dict:
        return self.request(
            "resource_allocation.create",
            params={
                "vertex": vertex_id,
                "other": other_id,
                "direction": direction,
                "label": label,
                "max_degree": max_degree,
                "limit": limit,
            },
        )

    def edge_exist(self, source_id, target_id, label, *, sort_values=None, limit=None) -> dict:
        return self.request(
            "edge_existence.get",
            params={
                "source": source_id,
                "target": target_id,
                "label": label,
                "sort_values": sort_values,
                "limit": limit,
            },
        )

    def vertices(self, ids) -> dict:
        return self.request("vertices.list", params={"ids": ids})

    def edges(self, ids) -> dict:
        return self.request("edges.list", params={"ids": ids})

    def multi_node_shortest_path(
        self, vertices, direction="BOTH", properties=None, max_depth=10, capacity=100000000, with_vertex=True
    ):
        if properties is None:
            properties = {}
        return self.request(
            "multi_node_shortest_path.post",
            data=json.dumps(
                {
                    "vertices": {"ids": vertices},
                    "step": {"direction": direction, "properties": properties},
                    "max_depth": max_depth,
                    "capacity": capacity,
                    "with_vertex": with_vertex,
                }
            ),
        )

    def advanced_paths(
        self, sources, targets, step, max_depth, nearest=True, capacity=10000000, limit=10, with_vertex=False
    ):
        return self.request(
            "paths.post",
            data=json.dumps(
                {
                    "sources": sources,
                    "targets": targets,
                    "step": step,
                    "max_depth": max_depth,
                    "nearest": nearest,
                    "capacity": capacity,
                    "limit": limit,
                    "with_vertex": with_vertex,
                }
            ),
        )

    def customized_paths(self, sources, steps, sort_by="INCR", with_vertex=True, capacity=-1, limit=-1):
        return self.request(
            "customized_paths.post",
            data=json.dumps(
                {
                    "sources": sources,
                    "steps": steps,
                    "sort_by": sort_by,
                    "with_vertex": with_vertex,
                    "capacity": capacity,
                    "limit": limit,
                }
            ),
        )

    def template_paths(self, sources, targets, steps, capacity=10000, limit=10, with_vertex=True):
        return self.request(
            "template_paths.post",
            data=json.dumps(
                {
                    "sources": sources,
                    "targets": targets,
                    "steps": steps,
                    "capacity": capacity,
                    "limit": limit,
                    "with_vertex": with_vertex,
                }
            ),
        )

    def customized_crosspoints(self, sources, path_patterns, with_path=True, with_vertex=True, capacity=-1, limit=-1):
        return self.request(
            "customized_crosspoints.post",
            data=json.dumps(
                {
                    "sources": sources,
                    "path_patterns": path_patterns,
                    "with_path": with_path,
                    "with_vertex": with_vertex,
                    "capacity": capacity,
                    "limit": limit,
                }
            ),
        )

    def fusiform_similarity(
        self,
        sources,
        label,
        direction,
        min_neighbors,
        alpha,
        min_similars,
        top,
        group_property,
        min_groups=2,
        max_degree=10000,
        capacity=-1,
        limit=-1,
        with_intermediary=False,
        with_vertex=True,
    ):
        return self.request(
            "fusiform_similarity.post",
            data=json.dumps(
                {
                    "sources": sources,
                    "label": label,
                    "direction": direction,
                    "min_neighbors": min_neighbors,
                    "alpha": alpha,
                    "min_similars": min_similars,
                    "top": top,
                    "group_property": group_property,
                    "min_groups": min_groups,
                    "max_degree": max_degree,
                    "capacity": capacity,
                    "limit": limit,
                    "with_intermediary": with_intermediary,
                    "with_vertex": with_vertex,
                }
            ),
        )

    def advanced_k_neighbor(self, body: dict) -> dict:
        return self.request("kneighbor.post", body=body)

    def advanced_k_out(self, body: dict) -> dict:
        return self.request("kout.post", body=body)

    def advanced_jaccard_similarity(self, body: dict) -> dict:
        return self.request("jaccard_similarity.post", body=body)

    def advanced_same_neighbors(self, body: dict) -> dict:
        return self.request("same_neighbors.same_neighbors", body=body)

    def same_neighbors_batch(self, body: dict) -> dict:
        return self.request("same_neighbors_batch.post", body=body)

    def count(self, body: dict) -> dict:
        return self.request("count.post", body=body)
