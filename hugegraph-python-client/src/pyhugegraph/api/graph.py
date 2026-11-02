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

"""Graph data conveniences; full entity payloads are accepted by batch operations."""

from collections.abc import Mapping

from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.structure.edge_data import EdgeData
from pyhugegraph.structure.vertex_data import VertexData


class GraphManager(HugeParamsBase):
    @staticmethod
    def _page_token(page, offset):
        if offset not in (None, 0):
            if page is not None:
                raise ValueError("page and nonzero offset cannot be combined")
            return None
        return "" if page is None else page

    def add_vertex(self, label, properties, id=None):
        body = {"label": label, "properties": properties}
        if id is not None:
            body["id"] = id
        return VertexData(self.request("vertex.create", body=body))

    def add_vertices(self, input_data):
        body = [
            dict(item) if isinstance(item, Mapping) else {"label": item[0], "properties": item[1]}
            for item in input_data
        ]
        return [
            VertexData(item if isinstance(item, dict) else {"id": item})
            for item in self.request("vertex.create_batch", body=body)
        ]

    def update_vertices(self, vertices, update_strategies, *, create_if_not_exist=True):
        return self.request(
            "vertex.update_batch",
            body={
                "vertices": vertices,
                "update_strategies": update_strategies or {},
                "create_if_not_exist": create_if_not_exist,
            },
        )

    def append_vertex(self, vertex_id, properties):
        return VertexData(
            self.request(
                "vertex.update_by_id",
                path_params={"id": vertex_id},
                params={"action": "append"},
                body={"properties": properties},
            )
        )

    def eliminate_vertex(self, vertex_id, properties):
        return VertexData(
            self.request(
                "vertex.update_by_id",
                path_params={"id": vertex_id},
                params={"action": "eliminate"},
                body={"properties": properties},
            )
        )

    def get_vertex_by_id(self, vertex_id):
        return VertexData(self.request("vertex.get", path_params={"id": vertex_id}))

    def list_vertices(self, *, label=None, properties=None, page=None, limit=None, offset=None, keep_start_p=None):
        """Return the REST envelope, including any pagination token."""
        return self.request(
            "vertex.list",
            params={
                "label": label,
                "properties": properties,
                "page": page,
                "limit": limit,
                "offset": offset,
                "keep_start_p": keep_start_p,
            },
        )

    def get_vertex_by_page(self, label, limit, page=None, properties=None, **options):
        response = self.list_vertices(
            label=label,
            properties=properties,
            page=self._page_token(page, options.get("offset")),
            limit=limit,
            **options,
        )
        return [VertexData(item) for item in response["vertices"]], response.get("page")

    def get_vertex_by_condition_with_page(self, label="", limit=0, page=None, properties=None, **options):
        response = self.list_vertices(
            label=label or None,
            properties=properties,
            page=self._page_token(page, options.get("offset")),
            limit=limit if limit > 0 else None,
            **options,
        )
        return [VertexData(item) for item in response["vertices"]], response.get("page")

    def get_vertex_by_condition(self, label="", limit=0, page=None, properties=None, **options):
        vertices, _ = self.get_vertex_by_condition_with_page(label, limit, page, properties, **options)
        return vertices

    def remove_vertex_by_id(self, vertex_id, *, label=None):
        return self.request("vertex.delete", path_params={"id": vertex_id}, params={"label": label})

    def add_edge(self, edge_label, out_id, in_id, properties):
        return EdgeData(
            self.request(
                "edge.create", body={"label": edge_label, "outV": out_id, "inV": in_id, "properties": properties}
            )
        )

    def add_edges(self, input_data, *, check_vertex=None):
        body = [
            dict(item)
            if isinstance(item, Mapping)
            else {
                "label": item[0],
                "outV": item[1],
                "inV": item[2],
                "outVLabel": item[3],
                "inVLabel": item[4],
                "properties": item[5],
            }
            for item in input_data
        ]
        return [
            EdgeData(item if isinstance(item, dict) else {"id": item})
            for item in self.request("edge.create_batch", body=body, params={"check_vertex": check_vertex})
        ]

    def update_edges(self, edges, update_strategies, *, create_if_not_exist=True):
        return self.request(
            "edge.update_batch",
            body={
                "edges": edges,
                "update_strategies": update_strategies or {},
                "create_if_not_exist": create_if_not_exist,
            },
        )

    def append_edge(self, edge_id, properties):
        return EdgeData(
            self.request(
                "edge.update_by_id",
                path_params={"id": edge_id},
                params={"action": "append"},
                body={"properties": properties},
            )
        )

    def eliminate_edge(self, edge_id, properties):
        return EdgeData(
            self.request(
                "edge.update_by_id",
                path_params={"id": edge_id},
                params={"action": "eliminate"},
                body={"properties": properties},
            )
        )

    def get_edge_by_id(self, edge_id):
        return EdgeData(self.request("edge.get", path_params={"id": edge_id}))

    def list_edges(
        self,
        *,
        label=None,
        vertex_id=None,
        direction=None,
        properties=None,
        page=None,
        limit=None,
        offset=None,
        keep_start_p=None,
    ):
        return self.request(
            "edge.list",
            params={
                "vertex_id": vertex_id,
                "direction": direction,
                "label": label,
                "properties": properties,
                "page": page,
                "limit": limit,
                "offset": offset,
                "keep_start_p": keep_start_p,
            },
        )

    def get_edge_by_page(
        self, label=None, vertex_id=None, direction=None, limit=0, page=None, properties=None, **options
    ):
        if vertex_id is not None and not direction:
            raise ValueError("direction is required when vertex_id is set")
        response = self.list_edges(
            vertex_id=vertex_id,
            direction=direction,
            label=label,
            properties=properties,
            page=self._page_token(page, options.get("offset")),
            limit=limit if limit > 0 else None,
            **options,
        )
        return [EdgeData(item) for item in response["edges"]], response.get("page")

    def remove_edge_by_id(self, edge_id, *, label=None):
        return self.request("edge.delete", path_params={"id": edge_id}, params={"label": label})

    def get_vertices_by_id(self, vertex_ids):
        if not vertex_ids:
            return []
        return [VertexData(item) for item in self.request("vertices.list", params={"ids": vertex_ids})["vertices"]]

    def get_edges_by_id(self, edge_ids):
        if not edge_ids:
            return []
        return [EdgeData(item) for item in self.request("edges.list", params={"ids": edge_ids})["edges"]]

    def vertex_shards(self, split_size):
        return self.request("vertices.shards", params={"split_size": split_size})

    def edge_shards(self, split_size):
        return self.request("edges.shards", params={"split_size": split_size})

    def scan_vertices(self, start, end, *, page=None, page_limit=None):
        return self.request(
            "vertices.scan", params={"start": start, "end": end, "page": page, "page_limit": page_limit}
        )

    def scan_edges(self, start, end, *, page=None, page_limit=None):
        return self.request("edges.scan", params={"start": start, "end": end, "page": page, "page_limit": page_limit})

    # Legacy public names share the canonical implementations.
    addEdge = add_edge  # noqa: N815
    addEdges = add_edges  # noqa: N815
    addVertex = add_vertex  # noqa: N815
    addVertices = add_vertices  # noqa: N815
    appendEdge = append_edge  # noqa: N815
    appendVertex = append_vertex  # noqa: N815
    eliminateEdge = eliminate_edge  # noqa: N815
    eliminateVertex = eliminate_vertex  # noqa: N815
    getEdgeById = get_edge_by_id  # noqa: N815
    getEdgeByPage = get_edge_by_page  # noqa: N815
    getEdgesById = get_edges_by_id  # noqa: N815
    getVertexByCondition = get_vertex_by_condition  # noqa: N815
    getVertexByConditionWithPage = get_vertex_by_condition_with_page  # noqa: N815
    getVertexById = get_vertex_by_id  # noqa: N815
    getVertexByPage = get_vertex_by_page  # noqa: N815
    getVerticesById = get_vertices_by_id  # noqa: N815
    removeEdgeById = remove_edge_by_id  # noqa: N815
    removeVertexById = remove_vertex_by_id  # noqa: N815
