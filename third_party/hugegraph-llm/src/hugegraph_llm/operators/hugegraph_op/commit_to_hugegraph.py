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

from typing import Any, Dict

from pyhugegraph.client import PyHugeClient
from pyhugegraph.utils.exceptions import CreateError, NotFoundError

from hugegraph_llm.config import huge_settings
from hugegraph_llm.enums.property_cardinality import PropertyCardinality
from hugegraph_llm.enums.property_data_type import PropertyDataType, default_value_map
from hugegraph_llm.utils.log import log


class Commit2Graph:
    def __init__(self):
        self.client = PyHugeClient(
            url=huge_settings.graph_url,
            graph=huge_settings.graph_name,
            user=huge_settings.graph_user,
            pwd=huge_settings.graph_pwd,
            graphspace=huge_settings.graph_space,
        )
        self.schema = self.client.schema()

    def run(self, data: dict) -> Dict[str, Any]:
        schema = data.get("schema")
        vertices = data.get("vertices", [])
        edges = data.get("edges", [])
        if not vertices and not edges:
            log.critical("(Loading) Both vertices and edges are empty. Please check the input data again.")
            raise ValueError("Both vertices and edges input are empty.")

        if not schema:
            # TODO: ensure the function works correctly (update the logic later)
            self.schema_free_mode(data.get("triples", []))
            log.warning("Using schema_free mode, could try schema_define mode for better effect!")
        else:
            self.init_schema_if_need(schema)
            self.load_into_graph(vertices, edges, schema)
        return data

    def _set_default_property(self, key, input_properties, property_label_map):
        data_type = property_label_map[key]["data_type"]
        cardinality = property_label_map[key]["cardinality"]
        if cardinality == PropertyCardinality.SINGLE.value:
            default_value = default_value_map(data_type)
            input_properties[key] = default_value
        else:
            # list or set
            default_value = []
            input_properties[key] = default_value
        log.warning("Property '%s' missing in vertex, set to '%s' for now", key, default_value)

    def _handle_graph_creation(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except NotFoundError as e:
            log.error(e)
            return None
        except CreateError as e:
            log.error("Error on creating: %s, %s", args, e)
            return None

    def load_into_graph(self, vertices, edges, schema):  # pylint: disable=too-many-statements
        # pylint: disable=R0912 (too-many-branches)
        vertex_label_map = {v_label["name"]: v_label for v_label in schema["vertexlabels"]}
        edge_label_map = {e_label["name"]: e_label for e_label in schema["edgelabels"]}
        property_label_map = {p_label["name"]: p_label for p_label in schema["propertykeys"]}
        vid_mapping = {}  # mapping from LLM-generated vertex ID to actual server vertex ID

        for vertex in vertices:
            input_label = vertex["label"]
            # 1. ensure the input_label in the graph schema
            if input_label not in vertex_label_map:
                log.critical(
                    "(Input) VertexLabel %s not found in schema, skip & need check it!",
                    input_label,
                )
                continue

            input_properties = vertex["properties"]
            vertex_label = vertex_label_map[input_label]
            primary_keys = vertex_label["primary_keys"]
            nullable_keys = vertex_label.get("nullable_keys", [])
            non_null_keys = [key for key in vertex_label["properties"] if key not in nullable_keys]

            has_problem = False
            # 2. Handle primary-keys mode vertex
            for pk in primary_keys:
                if not input_properties.get(pk):
                    if len(primary_keys) == 1:
                        log.error(
                            "Primary-key '%s' missing in vertex %s, skip it & need check it again",
                            pk,
                            vertex,
                        )
                        has_problem = True
                        break
                    # TODO: transform to Enum first (better in earlier step)
                    data_type = property_label_map[pk]["data_type"]
                    cardinality = property_label_map[pk]["cardinality"]
                    if cardinality == PropertyCardinality.SINGLE.value:
                        input_properties[pk] = default_value_map(data_type)
                    else:
                        input_properties[pk] = []
                    log.warning(
                        "Primary-key '%s' missing in vertex %s, mark empty & need check it again!",
                        pk,
                        vertex,
                    )
            if has_problem:
                continue

            # 3. Ensure all non-nullable props are set
            for key in non_null_keys:
                if key not in input_properties:
                    self._set_default_property(key, input_properties, property_label_map)

            # 4. Check all data type value is right
            for key, value in input_properties.items():
                # TODO: transform to Enum first (better in earlier step)
                data_type = property_label_map[key]["data_type"]
                cardinality = property_label_map[key]["cardinality"]
                if not self._check_property_data_type(data_type, cardinality, value):
                    log.error(
                        "Property type/format '%s' is not correct, skip it & need check it again",
                        key,
                    )
                    has_problem = True
                    break
            if has_problem:
                continue

            # TODO: we could try batch add vertices first, setback to single-mode if failed
            explicit_id = vertex.get("id")
            mapping_id = explicit_id
            if not mapping_id and primary_keys:
                mapping_id = f"{input_label}:{'!'.join(str(input_properties[pk]) for pk in primary_keys)}"

            if vertex_label.get("id_strategy") == "CUSTOMIZE_STRING" and explicit_id:
                result = self._handle_graph_creation(
                    self.client.graph().addVertex,
                    input_label,
                    input_properties,
                    id=explicit_id,
                )
            else:
                result = self._handle_graph_creation(self.client.graph().addVertex, input_label, input_properties)
            if result is None:
                raise ValueError(f"Failed to create vertex '{input_label}' with properties {input_properties}")
            vid = result.id
            vertex["id"] = vid
            if mapping_id:
                vid_mapping[mapping_id] = vid

        for edge in edges:
            start = vid_mapping.get(edge.get("outV"), edge.get("outV"))
            end = vid_mapping.get(edge.get("inV"), edge.get("inV"))
            label = edge["label"]
            properties = edge["properties"]

            if label not in edge_label_map:
                log.critical(
                    "(Input) EdgeLabel %s not found in schema, skip & need check it!",
                    label,
                )
                continue

            # TODO: we could try batch add edges first, setback to single-mode if failed
            self._handle_graph_creation(self.client.graph().addEdge, label, start, end, properties)

    def init_schema_if_need(self, schema: dict):
        properties = schema["propertykeys"]
        vertices = schema["vertexlabels"]
        edges = schema["edgelabels"]

        for prop in properties:
            self._create_property(prop)

        for vertex in vertices:
            vertex_label = vertex["name"]
            properties = vertex["properties"]
            nullable_keys = vertex["nullable_keys"]
            primary_keys = vertex["primary_keys"]
            self.schema.vertexLabel(vertex_label).properties(*properties).nullableKeys(
                *nullable_keys
            ).usePrimaryKeyId().primaryKeys(*primary_keys).ifNotExist().create()

        for edge in edges:
            edge_label = edge["name"]
            source_vertex_label = edge["source_label"]
            target_vertex_label = edge["target_label"]
            properties = edge["properties"]
            self.schema.edgeLabel(edge_label).sourceLabel(source_vertex_label).targetLabel(
                target_vertex_label
            ).properties(*properties).nullableKeys(*properties).ifNotExist().create()

    def schema_free_mode(self, data):
        self.schema.propertyKey("name").asText().ifNotExist().create()
        self.schema.vertexLabel("vertex").useCustomizeStringId().properties("name").ifNotExist().create()
        self.schema.edgeLabel("edge").sourceLabel("vertex").targetLabel("vertex").properties(
            "name"
        ).ifNotExist().create()

        self.schema.indexLabel("vertexByName").onV("vertex").by("name").secondary().ifNotExist().create()
        self.schema.indexLabel("edgeByName").onE("edge").by("name").secondary().ifNotExist().create()

        for item in data:
            s, p, o = (element.strip() for element in item)
            s_id = self.client.graph().addVertex("vertex", {"name": s}, id=s).id
            t_id = self.client.graph().addVertex("vertex", {"name": o}, id=o).id
            self.client.graph().addEdge("edge", s_id, t_id, {"name": p})

    def _create_property(self, prop: dict):
        name = prop["name"]
        try:
            data_type = PropertyDataType(prop["data_type"])
            cardinality = PropertyCardinality(prop["cardinality"])
        except ValueError:
            log.critical(
                "Invalid data type %s / cardinality %s for property %s, skip & should check it again",
                prop["data_type"],
                prop["cardinality"],
                name,
            )
            return

        property_key = self.schema.propertyKey(name)
        self._set_property_data_type(property_key, data_type)
        self._set_property_cardinality(property_key, cardinality)
        property_key.ifNotExist().create()

    def _set_property_data_type(self, property_key, data_type):
        if data_type == PropertyDataType.BOOLEAN:
            log.error("Boolean type is not supported")
        elif data_type == PropertyDataType.BYTE:
            log.warning("Byte type is not supported, use int instead")
            property_key.asInt()
        elif data_type == PropertyDataType.INT:
            property_key.asInt()
        elif data_type == PropertyDataType.LONG:
            property_key.asLong()
        elif data_type == PropertyDataType.FLOAT:
            log.warning("Float type is not supported, use double instead")
            property_key.asDouble()
        elif data_type == PropertyDataType.DOUBLE:
            property_key.asDouble()
        elif data_type == PropertyDataType.TEXT:
            property_key.asText()
        elif data_type == PropertyDataType.BLOB:
            log.warning("Blob type is not supported, use text instead")
            property_key.asText()
        elif data_type == PropertyDataType.DATE:
            property_key.asDate()
        elif data_type == PropertyDataType.UUID:
            log.warning("UUID type is not supported, use text instead")
            property_key.asText()
        else:
            log.error("Unknown data type %s for property_key %s", data_type, property_key)

    def _set_property_cardinality(self, property_key, cardinality):
        if cardinality == PropertyCardinality.SINGLE:
            property_key.valueSingle()
        elif cardinality == PropertyCardinality.LIST:
            property_key.valueList()
        elif cardinality == PropertyCardinality.SET:
            property_key.valueSet()
        else:
            log.error("Unknown cardinality %s for property_key %s", cardinality, property_key)

    def _check_property_data_type(self, data_type: str, cardinality: str, value) -> bool:
        if cardinality in (
            PropertyCardinality.LIST.value,
            PropertyCardinality.SET.value,
        ):
            return self._check_collection_data_type(data_type, value)
        return self._check_single_data_type(data_type, value)

    def _check_collection_data_type(self, data_type: str, value) -> bool:
        if not isinstance(value, list):
            return False
        for item in value:
            if not self._check_single_data_type(data_type, item):
                return False
        return True

    def _check_single_data_type(self, data_type: str, value) -> bool:
        if data_type == PropertyDataType.BOOLEAN.value:
            return isinstance(value, bool)
        if data_type in (
            PropertyDataType.BYTE.value,
            PropertyDataType.INT.value,
            PropertyDataType.LONG.value,
        ):
            return isinstance(value, int)
        if data_type in (PropertyDataType.FLOAT.value, PropertyDataType.DOUBLE.value):
            return isinstance(value, float)
        if data_type in (PropertyDataType.TEXT.value, PropertyDataType.UUID.value):
            return isinstance(value, str)
        # TODO: check ok below
        if data_type == PropertyDataType.DATE.value:  # the format should be "yyyy-MM-dd"
            import re

            return isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", value)
        raise ValueError(f"Unknown/Unsupported data type: {data_type}")
