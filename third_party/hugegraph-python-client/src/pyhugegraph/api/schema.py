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


from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.api.schema_manage.edge_label import EdgeLabel
from pyhugegraph.api.schema_manage.index_label import IndexLabel
from pyhugegraph.api.schema_manage.property_key import PropertyKey
from pyhugegraph.api.schema_manage.vertex_label import VertexLabel
from pyhugegraph.structure.edge_label_data import EdgeLabelData
from pyhugegraph.structure.index_label_data import IndexLabelData
from pyhugegraph.structure.property_key_data import PropertyKeyData
from pyhugegraph.structure.vertex_label_data import VertexLabelData
from pyhugegraph.utils import huge_router as router
from pyhugegraph.utils.log import log


class SchemaManager(HugeParamsBase):
    """
    create schemas, including propertyKey/vertexLabel/edgeLabel/indexLabel
    """

    def propertyKey(self, property_name) -> PropertyKey:
        property_key = PropertyKey(self._sess)
        property_key.create_parameter_holder()
        property_key.add_parameter("name", property_name)
        property_key.add_parameter("not_exist", True)
        return property_key

    def vertexLabel(self, vertex_name):
        vertex_label = VertexLabel(self._sess)
        vertex_label.create_parameter_holder()
        vertex_label.add_parameter("name", vertex_name)
        # vertex_label.add_parameter("id_strategy", "AUTOMATIC")
        vertex_label.add_parameter("not_exist", True)
        return vertex_label

    def edgeLabel(self, name):
        edge_label = EdgeLabel(self._sess)
        edge_label.create_parameter_holder()
        edge_label.add_parameter("name", name)
        edge_label.add_parameter("not_exist", True)
        return edge_label

    def indexLabel(self, name):
        index_label = IndexLabel(self._sess)
        index_label.create_parameter_holder()
        index_label.add_parameter("name", name)
        return index_label

    @router.http("GET", "schema?format={_format}")
    def getSchema(self, _format: str = "json") -> dict | None:  # pylint: disable=unused-argument
        return self._invoke_request()

    @router.http("GET", "schema/propertykeys/{property_name}")
    def getPropertyKey(self, property_name) -> PropertyKeyData | None:  # pylint: disable=unused-argument
        if response := self._invoke_request():
            return PropertyKeyData(response)
        return None

    @router.http("GET", "schema/propertykeys")
    def getPropertyKeys(self) -> list[PropertyKeyData] | None:
        if response := self._invoke_request():
            return [PropertyKeyData(item) for item in response["propertykeys"]]
        return None

    @router.http("GET", "schema/vertexlabels/{name}")
    def getVertexLabel(self, name) -> VertexLabelData | None:  # pylint: disable=unused-argument
        if response := self._invoke_request():
            return VertexLabelData(response)
        log.error("VertexLabel not found: %s", str(response))
        return None

    @router.http("GET", "schema/vertexlabels")
    def getVertexLabels(self) -> list[VertexLabelData] | None:
        if response := self._invoke_request():
            return [VertexLabelData(item) for item in response["vertexlabels"]]
        return None

    @router.http("GET", "schema/edgelabels/{label_name}")
    def getEdgeLabel(self, label_name: str) -> EdgeLabelData | None:  # pylint: disable=unused-argument
        if response := self._invoke_request():
            return EdgeLabelData(response)
        log.error("EdgeLabel not found: %s", str(response))
        return None

    @router.http("GET", "schema/edgelabels")
    def getEdgeLabels(self) -> list[EdgeLabelData] | None:
        if response := self._invoke_request():
            return [EdgeLabelData(item) for item in response["edgelabels"]]
        return None

    @router.http("GET", "schema/edgelabels")
    def getRelations(self) -> list[str] | None:
        """
        Retrieve all edge_label links/paths from the graph-sever.

        Returns a list of links representations for each edge_label, e.g:
        The format is like "source_vertexlabel--edge_label-->target_vertexlabel".(e.g. "Person--likes-->Animal")

        :return: A list of relationship links/paths for all edge_labels, or None if not found.
        """
        if response := self._invoke_request():
            return [EdgeLabelData(item).relations() for item in response["edgelabels"]]
        return None

    @router.http("GET", "schema/indexlabels/{name}")
    def getIndexLabel(self, name) -> IndexLabelData | None:  # pylint: disable=unused-argument
        if response := self._invoke_request():
            return IndexLabelData(response)
        log.error("IndexLabel not found: %s", str(response))
        return None

    @router.http("GET", "schema/indexlabels")
    def getIndexLabels(self) -> list[IndexLabelData] | None:
        if response := self._invoke_request():
            return [IndexLabelData(item) for item in response["indexlabels"]]
        return None
