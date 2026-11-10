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

from typing import Any, Dict, List, Tuple

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
        skipped_ids = set()  # local IDs of input vertices that were not imported
        skip_reports: List[str] = []  # human-readable reasons, named in the import summary
        imported_vertices = skipped_vertices = 0
        imported_edges = skipped_edges = 0

        for vertex in vertices:
            input_label = vertex["label"]
            # 1. ensure the input_label in the graph schema
            if input_label not in vertex_label_map:
                log.critical(
                    "(Input) VertexLabel %s not found in schema, skip & need check it!",
                    input_label,
                )
                skipped_vertices += 1
                skip_reports.append(f"{vertex.get('id') or input_label}: unknown VertexLabel")
                if vertex.get("id"):
                    skipped_ids.add(vertex["id"])
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
                skipped_vertices += 1
                skip_reports.append(f"{vertex.get('id') or input_label}: primary-key '{pk}' missing")
                if vertex.get("id"):
                    skipped_ids.add(vertex["id"])
                continue

            # 3. Ensure all non-nullable props are set
            for key in non_null_keys:
                if key not in input_properties:
                    self._set_default_property(key, input_properties, property_label_map)

            explicit_id = vertex.get("id")
            mapping_id = explicit_id
            if not mapping_id and primary_keys:
                mapping_id = f"{input_label}:{'!'.join(str(input_properties[pk]) for pk in primary_keys)}"

            # 4. Coerce property values onto their declared types. A nullable property
            # whose value cannot be converted is dropped on its own; a non-nullable one
            # skips only this vertex (the old code dropped the whole vertex for any
            # single mismatch while logging as if just the property was skipped).
            coerced_properties = {}
            for key, value in input_properties.items():
                prop_def = property_label_map.get(key)
                if prop_def is None:
                    log.warning("Property '%s' not found in schema, drop it & need check it again", key)
                    continue
                coerced, ok = self._coerce_property_value(prop_def["data_type"], prop_def["cardinality"], value)
                if ok:
                    coerced_properties[key] = coerced
                elif key in nullable_keys:
                    log.warning(
                        "Property '%s' value %r does not fit %s, drop the property & keep the vertex",
                        key,
                        value,
                        prop_def["data_type"],
                    )
                else:
                    log.error(
                        "Property '%s' value %r does not fit %s (non-nullable), skip vertex %s",
                        key,
                        value,
                        prop_def["data_type"],
                        vertex,
                    )
                    has_problem = True
                    break
            if has_problem:
                skipped_vertices += 1
                skip_reports.append(f"{mapping_id or input_label}: property '{key}' value {value!r} does not fit")
                if mapping_id:
                    skipped_ids.add(mapping_id)
                continue
            input_properties = coerced_properties
            vertex["properties"] = coerced_properties

            # TODO: we could try batch add vertices first, setback to single-mode if failed
            if vertex_label.get("id_strategy") == "CUSTOMIZE_STRING" and explicit_id:
                result = self._handle_graph_creation(
                    self.client.graph().add_vertex,
                    input_label,
                    input_properties,
                    id=explicit_id,
                )
            else:
                result = self._handle_graph_creation(self.client.graph().add_vertex, input_label, input_properties)
            if result is None:
                log.error(
                    "Failed to create vertex '%s' with properties %s, skip it & need check it again",
                    input_label,
                    input_properties,
                )
                skipped_vertices += 1
                skip_reports.append(f"{mapping_id or input_label}: server rejected the vertex")
                if mapping_id:
                    skipped_ids.add(mapping_id)
                continue
            vid = result.id
            vertex["id"] = vid
            if mapping_id:
                vid_mapping[mapping_id] = vid
            imported_vertices += 1

        log.info(
            "(Loading) import summary: %d vertices created, %d vertices skipped (%s)",
            imported_vertices,
            skipped_vertices,
            "; ".join(skip_reports) or "none",
        )
        if vertices and not imported_vertices:
            raise ValueError(
                f"Failed to create vertex: no vertex could be imported (skipped {skipped_vertices}: "
                f"{'; '.join(skip_reports)})"
            )

        for edge in edges:
            label = edge["label"]
            properties = edge["properties"]

            if label not in edge_label_map:
                log.critical(
                    "(Input) EdgeLabel %s not found in schema, skip & need check it!",
                    label,
                )
                skipped_edges += 1
                continue

            out_v, in_v = edge.get("outV"), edge.get("inV")
            failed_endpoints = [endpoint for endpoint in (out_v, in_v) if endpoint in skipped_ids]
            if failed_endpoints:
                log.error(
                    "Edge %s references skipped vertex id(s) %s, skip it & need check it again",
                    edge,
                    failed_endpoints,
                )
                skipped_edges += 1
                continue

            start = vid_mapping.get(out_v, out_v)
            end = vid_mapping.get(in_v, in_v)
            for endpoint in (out_v, in_v):
                if endpoint not in vid_mapping:
                    log.warning(
                        "Edge endpoint '%s' was not created in this import, passing it to the server unchanged.",
                        endpoint,
                    )

            # TODO: we could try batch add edges first, setback to single-mode if failed
            if self._handle_graph_creation(self.client.graph().add_edge, label, start, end, properties) is None:
                log.error("Failed to create edge '%s' (%s -> %s), skip it & need check it again", label, start, end)
                skipped_edges += 1
            else:
                imported_edges += 1

        log.info(
            "(Loading) import summary: %d edges created, %d edges skipped",
            imported_edges,
            skipped_edges,
        )

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
            self.schema.vertex_label(vertex_label).properties(*properties).nullable_keys(
                *nullable_keys
            ).use_primary_key_id().primary_keys(*primary_keys).if_not_exist().create()

        for edge in edges:
            edge_label = edge["name"]
            source_vertex_label = edge["source_label"]
            target_vertex_label = edge["target_label"]
            properties = edge["properties"]
            self.schema.edge_label(edge_label).source_label(source_vertex_label).target_label(
                target_vertex_label
            ).properties(*properties).nullable_keys(*properties).if_not_exist().create()

    def schema_free_mode(self, data):
        self.schema.property_key("name").as_text().if_not_exist().create()
        self.schema.vertex_label("vertex").use_customize_string_id().properties("name").if_not_exist().create()
        self.schema.edge_label("edge").source_label("vertex").target_label("vertex").properties(
            "name"
        ).if_not_exist().create()

        self.schema.index_label("vertexByName").on_v("vertex").by("name").secondary().if_not_exist().create()
        self.schema.index_label("edgeByName").on_e("edge").by("name").secondary().if_not_exist().create()

        for item in data:
            s, p, o = (element.strip() for element in item)
            s_id = self.client.graph().add_vertex("vertex", {"name": s}, id=s).id
            t_id = self.client.graph().add_vertex("vertex", {"name": o}, id=o).id
            self.client.graph().add_edge("edge", s_id, t_id, {"name": p})

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

        property_key = self.schema.property_key(name)
        self._set_property_data_type(property_key, data_type)
        self._set_property_cardinality(property_key, cardinality)
        property_key.if_not_exist().create()

    def _set_property_data_type(self, property_key, data_type):
        if data_type == PropertyDataType.BOOLEAN:
            log.error("Boolean type is not supported")
        elif data_type == PropertyDataType.BYTE:
            log.warning("Byte type is not supported, use int instead")
            property_key.as_int()
        elif data_type == PropertyDataType.INT:
            property_key.as_int()
        elif data_type == PropertyDataType.LONG:
            property_key.as_long()
        elif data_type == PropertyDataType.FLOAT:
            log.warning("Float type is not supported, use double instead")
            property_key.as_double()
        elif data_type == PropertyDataType.DOUBLE:
            property_key.as_double()
        elif data_type == PropertyDataType.TEXT:
            property_key.as_text()
        elif data_type == PropertyDataType.BLOB:
            log.warning("Blob type is not supported, use text instead")
            property_key.as_text()
        elif data_type == PropertyDataType.DATE:
            property_key.as_date()
        elif data_type == PropertyDataType.UUID:
            log.warning("UUID type is not supported, use text instead")
            property_key.as_text()
        else:
            log.error("Unknown data type %s for property_key %s", data_type, property_key)

    def _set_property_cardinality(self, property_key, cardinality):
        if cardinality == PropertyCardinality.SINGLE:
            property_key.value_single()
        elif cardinality == PropertyCardinality.LIST:
            property_key.value_list()
        elif cardinality == PropertyCardinality.SET:
            property_key.value_set()
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
            # bool is an int subclass in Python, but True is not a valid number here
            return isinstance(value, int) and not isinstance(value, bool)
        if data_type in (PropertyDataType.FLOAT.value, PropertyDataType.DOUBLE.value):
            return isinstance(value, float)
        if data_type in (
            PropertyDataType.TEXT.value,
            PropertyDataType.UUID.value,
            PropertyDataType.BLOB.value,
        ):
            # BLOB is created as TEXT (see _set_property_data_type), so it validates as text
            return isinstance(value, str)
        # TODO: check ok below
        if data_type == PropertyDataType.DATE.value:  # the format should be "yyyy-MM-dd"
            import re

            return isinstance(value, str) and bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value))
        raise ValueError(f"Unknown/Unsupported data type: {data_type}")

    def _coerce_property_value(self, data_type: str, cardinality: str, value) -> Tuple[Any, bool]:
        """Losslessly coerce a property value to its declared type and cardinality.

        Returns ``(coerced_value, True)`` when the value is already valid or convertible
        without losing information (numeric strings to numbers, numbers to text, scalars
        to single-element collections), otherwise ``(None, False)`` so the caller can
        report the value instead of silently dropping it.
        """
        if cardinality in (PropertyCardinality.LIST.value, PropertyCardinality.SET.value):
            items = value if isinstance(value, list) else [value]
            coerced_items = []
            for item in items:
                coerced, ok = self._coerce_single_value(data_type, item)
                if not ok:
                    return None, False
                coerced_items.append(coerced)
            return coerced_items, True
        return self._coerce_single_value(data_type, value)

    def _coerce_single_value(self, data_type: str, value) -> Tuple[Any, bool]:
        try:
            if self._check_property_data_type(data_type, PropertyCardinality.SINGLE.value, value):
                return value, True
            candidates = self._lossless_candidates(data_type, value)
            for candidate in candidates:
                if self._check_property_data_type(data_type, PropertyCardinality.SINGLE.value, candidate):
                    return candidate, True
        except ValueError:
            return None, False  # unknown data type: the caller reports the value
        return None, False

    @staticmethod
    def _lossless_candidates(data_type: str, value) -> List[Any]:
        """Values that carry the same information as ``value`` in the declared type."""
        if isinstance(value, bool):
            return []
        if data_type in (PropertyDataType.TEXT.value, PropertyDataType.UUID.value, PropertyDataType.BLOB.value):
            return [str(value)] if isinstance(value, (int, float)) else []
        if data_type in (
            PropertyDataType.BYTE.value,
            PropertyDataType.INT.value,
            PropertyDataType.LONG.value,
        ):
            if isinstance(value, float):
                return [int(value)] if value.is_integer() else []
            if isinstance(value, str):
                try:
                    return [int(value)]
                except ValueError:
                    return []
            return []
        if data_type in (PropertyDataType.FLOAT.value, PropertyDataType.DOUBLE.value):
            if isinstance(value, (int, float, str)):
                try:
                    return [float(value)]
                except ValueError:
                    return []
            return []
        return []
