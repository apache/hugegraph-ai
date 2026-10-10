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
import json
from urllib.parse import urlencode

from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.utils import huge_router as router
from pyhugegraph.utils.id_format import format_vertex_id


class TraverserManager(HugeParamsBase):
    def _get_with_vertex_ids(self, endpoint, vertex_params, query_params):
        params = [(name, format_vertex_id(value)) for name, value in vertex_params]
        params.extend(query_params)
        return self._sess.request(f"{endpoint}?{urlencode(params)}")

    def k_out(self, source_id, max_depth):
        return self._get_with_vertex_ids("traversers/kout", [("source", source_id)], [("max_depth", max_depth)])

    def k_neighbor(self, source_id, max_depth):
        return self._get_with_vertex_ids("traversers/kneighbor", [("source", source_id)], [("max_depth", max_depth)])

    def same_neighbors(self, vertex_id, other_id):
        return self._get_with_vertex_ids(
            "traversers/sameneighbors",
            [("vertex", vertex_id), ("other", other_id)],
            [],
        )

    def jaccard_similarity(self, vertex_id, other_id):
        return self._get_with_vertex_ids(
            "traversers/jaccardsimilarity",
            [("vertex", vertex_id), ("other", other_id)],
            [],
        )

    def shortest_path(self, source_id, target_id, max_depth):
        return self._get_with_vertex_ids(
            "traversers/shortestpath",
            [("source", source_id), ("target", target_id)],
            [("max_depth", max_depth)],
        )

    def all_shortest_paths(self, source_id, target_id, max_depth):
        return self._get_with_vertex_ids(
            "traversers/allshortestpaths",
            [("source", source_id), ("target", target_id)],
            [("max_depth", max_depth)],
        )

    def weighted_shortest_path(self, source_id, target_id, weight, max_depth):
        return self._get_with_vertex_ids(
            "traversers/weightedshortestpath",
            [("source", source_id), ("target", target_id)],
            [("weight", weight), ("max_depth", max_depth)],
        )

    def single_source_shortest_path(self, source_id, max_depth):
        return self._get_with_vertex_ids(
            "traversers/singlesourceshortestpath",
            [("source", source_id)],
            [("max_depth", max_depth)],
        )

    @router.http("POST", "traversers/multinodeshortestpath")
    def multi_node_shortest_path(
        self,
        vertices,
        direction="BOTH",
        properties=None,
        max_depth=10,
        capacity=100000000,
        with_vertex=True,
    ):
        if properties is None:
            properties = {}
        return self._invoke_request(
            data=json.dumps(
                {
                    "vertices": {"ids": vertices},
                    "step": {"direction": direction, "properties": properties},
                    "max_depth": max_depth,
                    "capacity": capacity,
                    "with_vertex": with_vertex,
                }
            )
        )

    def paths(self, source_id, target_id, max_depth):
        return self._get_with_vertex_ids(
            "traversers/paths",
            [("source", source_id), ("target", target_id)],
            [("max_depth", max_depth)],
        )

    @router.http("POST", "traversers/paths")
    def advanced_paths(
        self,
        sources,
        targets,
        step,
        max_depth,
        nearest=True,
        capacity=10000000,
        limit=10,
        with_vertex=False,
    ):
        return self._invoke_request(
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
            )
        )

    @router.http("POST", "traversers/customizedpaths")
    def customized_paths(self, sources, steps, sort_by="INCR", with_vertex=True, capacity=-1, limit=-1):
        return self._invoke_request(
            data=json.dumps(
                {
                    "sources": sources,
                    "steps": steps,
                    "sort_by": sort_by,
                    "with_vertex": with_vertex,
                    "capacity": capacity,
                    "limit": limit,
                }
            )
        )

    @router.http("POST", "traversers/templatepaths")
    def template_paths(self, sources, targets, steps, capacity=10000, limit=10, with_vertex=True):
        return self._invoke_request(
            data=json.dumps(
                {
                    "sources": sources,
                    "targets": targets,
                    "steps": steps,
                    "capacity": capacity,
                    "limit": limit,
                    "with_vertex": with_vertex,
                }
            )
        )

    def crosspoints(self, source_id, target_id, max_depth):
        return self._get_with_vertex_ids(
            "traversers/crosspoints",
            [("source", source_id), ("target", target_id)],
            [("max_depth", max_depth)],
        )

    @router.http("POST", "traversers/customizedcrosspoints")
    def customized_crosspoints(
        self,
        sources,
        path_patterns,
        with_path=True,
        with_vertex=True,
        capacity=-1,
        limit=-1,
    ):
        return self._invoke_request(
            data=json.dumps(
                {
                    "sources": sources,
                    "path_patterns": path_patterns,
                    "with_path": with_path,
                    "with_vertex": with_vertex,
                    "capacity": capacity,
                    "limit": limit,
                }
            )
        )

    def rings(self, source_id, max_depth):
        return self._get_with_vertex_ids("traversers/rings", [("source", source_id)], [("max_depth", max_depth)])

    def rays(self, source_id, max_depth):
        return self._get_with_vertex_ids("traversers/rays", [("source", source_id)], [("max_depth", max_depth)])

    @router.http("POST", "traversers/fusiformsimilarity")
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
        return self._invoke_request(
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
            )
        )

    @router.http("GET", "traversers/vertices")
    def vertices(self, ids):
        params = {"ids": format_vertex_id(ids)}
        return self._invoke_request(params=params)

    @router.http("GET", "traversers/edges")
    def edges(self, ids):
        params = {"ids": ids}
        return self._invoke_request(params=params)
