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
from hugegraph_llm.utils.schema_property import is_property_value_for_type


class Commit2Graph:
    def __init__(self, graph_config=None):
        graph_config = graph_config or {}

        def pick(key, default):
            value = graph_config[key] if key in graph_config else default
            return default if value is None else value

        self.client = PyHugeClient(
            url=pick("url", huge_settings.graph_url),
            graph=pick("graph", huge_settings.graph_name),
            user=pick("user", huge_settings.graph_user),
            pwd=pick("pwd", huge_settings.graph_pwd),
            graphspace=pick("gs", huge_settings.graph_space),
        )
        self.schema = self.client.schema()

    def _empty_import_result(self, vertices=None, edges=None, triples=None) -> Dict[str, Any]:
        return {
            "vertices_attempted": len(vertices or []),
            "vertices_created": 0,
            "vertices_skipped": 0,
            "edges_attempted": len(edges or []),
            "edges_created": 0,
            "edges_skipped": 0,
            "triples_attempted": len(triples or []),
            "triples_created": 0,
            "triples_skipped": 0,
            "errors": [],
        }

    def _import_error(self, kind, index, reason, label=None, key=None) -> Dict[str, Any]:
        error = {"kind": kind, "index": index, "reason": reason}
        if label:
            error["label"] = label
        if key:
            error["key"] = key
        return error

    def _vertex_mapping_id(self, vertex, vertex_label=None):
        explicit_id = vertex.get("id")
        if explicit_id:
            return explicit_id
        if vertex_label is None:
            return None
        primary_keys = vertex_label.get("primary_keys", [])
        properties = vertex.get("properties") or {}
        if primary_keys and all(properties.get(pk) for pk in primary_keys):
            return f"{vertex['label']}:{'!'.join(str(properties[pk]) for pk in primary_keys)}"
        return None

    def _validate_input_properties(
        self,
        kind,
        index,
        label,
        properties,
        allowed_properties,
        property_label_map,
        import_result,
    ) -> bool:
        allowed = set(allowed_properties)
        skipped_key = "vertices_skipped" if kind == "vertex" else "edges_skipped"
        for key, value in properties.items():
            property_label = property_label_map.get(key)
            if key not in allowed or property_label is None:
                log.error(
                    "(Input) %s property '%s' is not defined in schema label '%s', skip it & need check it again",
                    kind,
                    key,
                    label,
                )
                import_result[skipped_key] += 1
                import_result["errors"].append(self._import_error(kind, index, "unknown_property", label, key))
                return False
            # TODO: transform to Enum first (better in earlier step)
            data_type = property_label["data_type"]
            cardinality = property_label["cardinality"]
            if not self._check_property_data_type(data_type, cardinality, value):
                log.error(
                    "(Input) %s property type/format '%s' is not correct, skip it & need check it again",
                    kind,
                    key,
                )
                import_result[skipped_key] += 1
                import_result["errors"].append(self._import_error(kind, index, "invalid_property_type", label, key))
                return False
        return True

    def run(self, data: dict) -> Dict[str, Any]:
        schema = data.get("schema")
        vertices = data.get("vertices", []) or []
        edges = data.get("edges", []) or []
        triples = data.get("triples", []) or []
        if not vertices and not edges and not triples:
            log.critical("(Loading) vertices, edges, and triples are empty. Please check the input data again.")
            raise ValueError("vertices, edges, and triples input are empty.")

        if not schema:
            if vertices or edges:
                raise ValueError("Schema-free mode only supports triples input; vertices and edges require schema.")
            if not triples:
                raise ValueError("Schema-free mode requires non-empty triples input.")
            import_result = self.schema_free_mode(triples)
            log.warning("Using schema_free mode, could try schema_define mode for better effect!")
        else:
            if triples:
                raise ValueError("Triples input is not supported when schema is provided; use vertices and edges.")
            if not vertices and not edges:
                log.critical(
                    "(Loading) property-graph vertices and edges are empty. Please check the input data again."
                )
                raise ValueError("property-graph vertices and edges are required when schema is provided.")
            self.init_schema_if_need(schema)
            import_result = self.load_into_graph(vertices, edges, schema)
        data["import_result"] = import_result or self._empty_import_result(vertices, edges, triples)
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
        import_result = self._empty_import_result(vertices, edges)
        vertex_label_map = {v_label["name"]: v_label for v_label in schema["vertexlabels"]}
        edge_label_map = {e_label["name"]: e_label for e_label in schema["edgelabels"]}
        property_label_map = {p_label["name"]: p_label for p_label in schema["propertykeys"]}
        vid_mapping = {}  # mapping from LLM-generated vertex ID to actual server vertex ID
        batch_vertex_refs = set()
        failed_vertex_refs = set()

        for vertex_index, vertex in enumerate(vertices):
            input_label = vertex["label"]
            # 1. ensure the input_label in the graph schema
            if input_label not in vertex_label_map:
                log.critical(
                    "(Input) VertexLabel %s not found in schema, skip & need check it!",
                    input_label,
                )
                import_result["vertices_skipped"] += 1
                import_result["errors"].append(
                    self._import_error("vertex", vertex_index, "vertex_label_not_found", label=input_label)
                )
                vertex_ref = self._vertex_mapping_id(vertex)
                if vertex_ref:
                    batch_vertex_refs.add(vertex_ref)
                    failed_vertex_refs.add(vertex_ref)
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
                        import_result["errors"].append(
                            self._import_error("vertex", vertex_index, "missing_primary_key", input_label, pk)
                        )
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
                import_result["vertices_skipped"] += 1
                vertex_ref = self._vertex_mapping_id(vertex, vertex_label)
                if vertex_ref:
                    batch_vertex_refs.add(vertex_ref)
                    failed_vertex_refs.add(vertex_ref)
                continue
            mapping_id = self._vertex_mapping_id(vertex, vertex_label)
            if mapping_id:
                batch_vertex_refs.add(mapping_id)

            # 3. Ensure all non-nullable props are set
            for key in non_null_keys:
                if key not in input_properties:
                    self._set_default_property(key, input_properties, property_label_map)

            # 4. Check all property keys and data types are schema-compliant.
            if not self._validate_input_properties(
                "vertex",
                vertex_index,
                input_label,
                input_properties,
                vertex_label["properties"],
                property_label_map,
                import_result,
            ):
                if mapping_id:
                    failed_vertex_refs.add(mapping_id)
                continue

            # TODO: we could try batch add vertices first, setback to single-mode if failed
            explicit_id = vertex.get("id")
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
                import_result["vertices_skipped"] += 1
                import_result["errors"].append(
                    self._import_error("vertex", vertex_index, "create_failed", label=input_label)
                )
                if mapping_id:
                    failed_vertex_refs.add(mapping_id)
                continue
            vid = result.id
            import_result["vertices_created"] += 1
            vertex["id"] = vid
            if mapping_id:
                vid_mapping[mapping_id] = vid

        for edge_index, edge in enumerate(edges):
            label = edge["label"]
            properties = edge["properties"]

            if label not in edge_label_map:
                log.critical(
                    "(Input) EdgeLabel %s not found in schema, skip & need check it!",
                    label,
                )
                import_result["edges_skipped"] += 1
                import_result["errors"].append(
                    self._import_error("edge", edge_index, "edge_label_not_found", label=label)
                )
                continue

            edge_label = edge_label_map[label]
            if edge.get("outVLabel") is not None and edge.get("outVLabel") != edge_label.get("source_label"):
                import_result["edges_skipped"] += 1
                import_result["errors"].append(
                    self._import_error("edge", edge_index, "source_label_mismatch", label=label, key="outVLabel")
                )
                continue
            if edge.get("inVLabel") is not None and edge.get("inVLabel") != edge_label.get("target_label"):
                import_result["edges_skipped"] += 1
                import_result["errors"].append(
                    self._import_error("edge", edge_index, "target_label_mismatch", label=label, key="inVLabel")
                )
                continue

            start_ref = edge.get("outV")
            end_ref = edge.get("inV")
            endpoint_error = None
            for endpoint_key, endpoint_ref in (("outV", start_ref), ("inV", end_ref)):
                if endpoint_ref in failed_vertex_refs:
                    endpoint_error = ("endpoint_vertex_failed", endpoint_key)
                    break
                if endpoint_ref in batch_vertex_refs and endpoint_ref not in vid_mapping:
                    endpoint_error = ("missing_endpoint", endpoint_key)
                    break
            if endpoint_error is not None:
                reason, endpoint_key = endpoint_error
                import_result["edges_skipped"] += 1
                import_result["errors"].append(
                    self._import_error("edge", edge_index, reason, label=label, key=endpoint_key)
                )
                continue
            start = vid_mapping.get(start_ref, start_ref)
            end = vid_mapping.get(end_ref, end_ref)

            if not self._validate_input_properties(
                "edge",
                edge_index,
                label,
                properties,
                edge_label.get("properties", []),
                property_label_map,
                import_result,
            ):
                continue

            # TODO: we could try batch add edges first, setback to single-mode if failed
            result = self._handle_graph_creation(self.client.graph().addEdge, label, start, end, properties)
            if result is None:
                import_result["edges_skipped"] += 1
                import_result["errors"].append(self._import_error("edge", edge_index, "create_failed", label=label))
                continue
            import_result["edges_created"] += 1
        return import_result

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
            vertex_builder = self.schema.vertexLabel(vertex_label).properties(*properties).nullableKeys(*nullable_keys)
            if vertex.get("id_strategy") == "CUSTOMIZE_STRING":
                vertex_builder = vertex_builder.useCustomizeStringId()
            else:
                vertex_builder = vertex_builder.usePrimaryKeyId().primaryKeys(*primary_keys)
            vertex_builder.ifNotExist().create()

        for edge in edges:
            edge_label = edge["name"]
            source_vertex_label = edge["source_label"]
            target_vertex_label = edge["target_label"]
            properties = edge["properties"]
            self.schema.edgeLabel(edge_label).sourceLabel(source_vertex_label).targetLabel(
                target_vertex_label
            ).properties(*properties).nullableKeys(*properties).ifNotExist().create()

    def schema_free_mode(self, data):
        import_result = self._empty_import_result(triples=data)
        self.schema.propertyKey("name").asText().ifNotExist().create()
        self.schema.vertexLabel("vertex").useCustomizeStringId().properties("name").ifNotExist().create()
        self.schema.edgeLabel("edge").sourceLabel("vertex").targetLabel("vertex").properties(
            "name"
        ).ifNotExist().create()

        self.schema.indexLabel("vertexByName").onV("vertex").by("name").secondary().ifNotExist().create()
        self.schema.indexLabel("edgeByName").onE("edge").by("name").secondary().ifNotExist().create()

        for triple_index, item in enumerate(data):
            s, p, o = (element.strip() for element in item)
            s_vertex = self._handle_graph_creation(self.client.graph().addVertex, "vertex", {"name": s}, id=s)
            t_vertex = self._handle_graph_creation(self.client.graph().addVertex, "vertex", {"name": o}, id=o)
            if s_vertex is None or t_vertex is None:
                import_result["triples_skipped"] += 1
                import_result["errors"].append(self._import_error("triple", triple_index, "create_vertices_failed"))
                continue
            edge = self._handle_graph_creation(
                self.client.graph().addEdge, "edge", s_vertex.id, t_vertex.id, {"name": p}
            )
            if edge is None:
                import_result["triples_skipped"] += 1
                import_result["errors"].append(self._import_error("triple", triple_index, "create_edge_failed"))
                continue
            import_result["triples_created"] += 1
        return import_result

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
        return is_property_value_for_type(data_type, cardinality, value, strict_data_type=True)

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
            return isinstance(value, int) and not isinstance(value, bool)
        if data_type in (PropertyDataType.FLOAT.value, PropertyDataType.DOUBLE.value):
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if data_type in (PropertyDataType.TEXT.value, PropertyDataType.UUID.value):
            return isinstance(value, str)
        # TODO: check ok below
        if data_type == PropertyDataType.DATE.value:  # the format should be "yyyy-MM-dd"
            import re

            return isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", value)
        raise ValueError(f"Unknown/Unsupported data type: {data_type}")
