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
from urllib.parse import quote_plus, urlencode

from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.structure.edge_data import EdgeData
from pyhugegraph.structure.vertex_data import VertexData
from pyhugegraph.utils import huge_router as router
from pyhugegraph.utils.exceptions import NotFoundError
from pyhugegraph.utils.id_format import (
    format_edge_id_path,
    format_vertex_id,
    format_vertex_id_path,
)


def _urlencode_query(params):
    parts = []
    for key, value in params:
        if value is None:
            parts.append(quote_plus(str(key), safe=""))
        else:
            parts.append(urlencode([(key, value)]))
    return "&".join(parts)


class GraphManager(HugeParamsBase):
    @router.http("POST", "graph/vertices")
    def addVertex(self, label, properties, id=None):
        data = {}
        if id is not None:
            data["id"] = id
        data["label"] = label
        data["properties"] = properties
        if response := self._invoke_request(data=json.dumps(data)):
            return VertexData(response)
        return None

    @router.http("POST", "graph/vertices/batch")
    def addVertices(self, input_data):
        data = []
        for item in input_data:
            data.append({"label": item[0], "properties": item[1]})
        if response := self._invoke_request(data=json.dumps(data)):
            return [VertexData({"id": item}) for item in response]
        return None

    def appendVertex(self, vertex_id, properties):
        data = {"properties": properties}
        path = f"graph/vertices/{format_vertex_id_path(vertex_id)}?action=append"
        if response := self._sess.request(path, "PUT", data=json.dumps(data)):
            return VertexData(response)
        return None

    def eliminateVertex(self, vertex_id, properties):
        data = {"properties": properties}
        path = f"graph/vertices/{format_vertex_id_path(vertex_id)}?action=eliminate"
        if response := self._sess.request(path, "PUT", data=json.dumps(data)):
            return VertexData(response)
        return None

    def getVertexById(self, vertex_id):
        path = f"graph/vertices/{format_vertex_id_path(vertex_id)}"
        if response := self._sess.request(path):
            return VertexData(response)
        return None

    def getVertexByPage(self, label, limit, page=None, properties=None):
        path = "graph/vertices?"
        params = [("label", label)]
        if properties:
            params.append(("properties", json.dumps(properties)))
        if page:
            params.append(("page", page))
        else:
            params.append(("page", None))
        params.append(("limit", str(limit)))
        path = path + _urlencode_query(params)
        if response := self._sess.request(path):
            res = [VertexData(item) for item in response["vertices"]]
            next_page = response["page"]
            return res, next_page
        return None, None

    def getVertexByConditionWithPage(self, label="", limit=0, page=None, properties=None):
        path = "graph/vertices?"
        params = []
        if label:
            params.append(("label", label))
        if properties:
            params.append(("properties", json.dumps(properties)))
        if limit > 0:
            params.append(("limit", str(limit)))
        if page:
            params.append(("page", page))
        else:
            params.append(("page", None))
        path = path + _urlencode_query(params)
        if response := self._sess.request(path):
            return [VertexData(item) for item in response["vertices"]], response.get("page")
        return None, None

    def getVertexByCondition(self, label="", limit=0, page=None, properties=None):
        vertices, _ = self.getVertexByConditionWithPage(
            label=label,
            limit=limit,
            page=page,
            properties=properties,
        )
        return vertices

    def removeVertexById(self, vertex_id):
        path = f"graph/vertices/{format_vertex_id_path(vertex_id)}"
        return self._sess.request(path, "DELETE")

    @router.http("POST", "graph/edges")
    def addEdge(self, edge_label, out_id, in_id, properties) -> EdgeData | None:
        data = {
            "label": edge_label,
            "outV": out_id,
            "inV": in_id,
            "properties": properties,
        }
        if response := self._invoke_request(data=json.dumps(data)):
            return EdgeData(response)
        return None

    @router.http("POST", "graph/edges/batch")
    def addEdges(self, input_data) -> list[EdgeData] | None:
        data = []
        for item in input_data:
            data.append(
                {
                    "label": item[0],
                    "outV": item[1],
                    "inV": item[2],
                    "outVLabel": item[3],
                    "inVLabel": item[4],
                    "properties": item[5],
                }
            )
        if response := self._invoke_request(data=json.dumps(data)):
            return [EdgeData({"id": item}) for item in response]
        return None

    def appendEdge(
        self,
        edge_id,
        properties,
    ) -> EdgeData | None:
        path = f"graph/edges/{format_edge_id_path(edge_id)}?action=append"
        if response := self._sess.request(
            path,
            "PUT",
            data=json.dumps({"properties": properties}),
        ):
            return EdgeData(response)
        return None

    def eliminateEdge(
        self,
        edge_id,
        properties,
    ) -> EdgeData | None:
        path = f"graph/edges/{format_edge_id_path(edge_id)}?action=eliminate"
        if response := self._sess.request(
            path,
            "PUT",
            data=json.dumps({"properties": properties}),
        ):
            return EdgeData(response)
        return None

    def getEdgeById(self, edge_id) -> EdgeData | None:
        path = f"graph/edges/{format_edge_id_path(edge_id)}"
        if response := self._sess.request(path):
            return EdgeData(response)
        return None

    def getEdgeByPage(
        self,
        label=None,
        vertex_id=None,
        direction=None,
        limit=0,
        page=None,
        properties=None,
    ):
        path = "graph/edges?"
        params = []
        if vertex_id is not None:
            if direction:
                params.append(("vertex_id", format_vertex_id(vertex_id)))
                params.append(("direction", direction))
            else:
                raise NotFoundError("Direction can not be empty.")
        if label:
            params.append(("label", label))
        if properties:
            params.append(("properties", json.dumps(properties)))
        if page:
            params.append(("page", page))
        else:
            params.append(("page", None))
        if limit > 0:
            params.append(("limit", str(limit)))
        path = path + _urlencode_query(params)
        if response := self._sess.request(path):
            return [EdgeData(item) for item in response["edges"]], response["page"]
        return None, None

    def removeEdgeById(self, edge_id) -> dict:
        path = f"graph/edges/{format_edge_id_path(edge_id)}"
        return self._sess.request(path, "DELETE")

    def getVerticesById(self, vertex_ids) -> list[VertexData] | None:
        if not vertex_ids:
            return []
        path = "traversers/vertices?"
        query = urlencode([("ids", format_vertex_id(vertex_id)) for vertex_id in vertex_ids])
        path += query
        if response := self._sess.request(path):
            return [VertexData(item) for item in response["vertices"]]
        return None

    def getEdgesById(self, edge_ids) -> list[EdgeData] | None:
        if not edge_ids:
            return []
        path = "traversers/edges?"
        path += urlencode([("ids", str(edge_id)) for edge_id in edge_ids])
        if response := self._sess.request(path):
            return [EdgeData(item) for item in response["edges"]]
        return None
