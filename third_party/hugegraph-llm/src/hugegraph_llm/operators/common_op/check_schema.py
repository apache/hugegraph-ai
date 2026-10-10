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


from typing import Any, Dict, Optional

from hugegraph_llm.enums.property_cardinality import PropertyCardinality
from hugegraph_llm.enums.property_data_type import PropertyDataType
from hugegraph_llm.utils.log import log


def log_and_raise(message: str) -> None:
    log.warning(message)
    raise ValueError(message)


def check_type(value: Any, expected_type: type, message: str) -> None:
    if not isinstance(value, expected_type):
        log_and_raise(message)


class CheckSchema:
    def __init__(self, data: Dict[str, Any]):
        self.result = None
        self.data = data

    def run(self, context: Optional[Dict[str, Any]] = None) -> Any:
        if context is None:
            context = {}

        # 1. Validate the schema structure
        schema = self.data or context.get("schema")
        self._validate_schema(schema)
        # 2. Process property labels and also create a set for it
        property_labels, property_label_set = self._process_property_labels(schema)
        # 3. Process properties in given vertex/edge labels
        self._process_vertex_labels(schema, property_labels, property_label_set)
        self._process_edge_labels(schema, property_labels, property_label_set)
        # 4. Update schema with processed pks
        schema["propertykeys"] = property_labels
        context.update({"schema": schema})
        return context

    def _validate_schema(self, schema: Dict[str, Any]) -> None:
        check_type(schema, dict, "Input data is not a dictionary.")
        if "vertexlabels" not in schema or "edgelabels" not in schema:
            log_and_raise("Input data does not contain 'vertexlabels' or 'edgelabels'.")
        check_type(schema["vertexlabels"], list, "'vertexlabels' in input data is not a list.")
        check_type(schema["edgelabels"], list, "'edgelabels' in input data is not a list.")

    def _process_property_labels(self, schema: Dict[str, Any]) -> (list, set):
        property_labels = schema.get("propertykeys", [])
        check_type(
            property_labels,
            list,
            "'propertykeys' in input data is not of correct type.",
        )
        property_label_set = {label["name"] for label in property_labels}
        return property_labels, property_label_set

    def _process_vertex_labels(self, schema: Dict[str, Any], property_labels: list, property_label_set: set) -> None:
        for vertex_label in schema["vertexlabels"]:
            self._validate_vertex_label(vertex_label)
            properties = vertex_label["properties"]
            primary_keys = self._process_keys(vertex_label, "primary_keys", properties[:1])
            if len(primary_keys) == 0:
                log_and_raise(f"'primary_keys' of {vertex_label['name']} is empty.")
            vertex_label["primary_keys"] = primary_keys
            nullable_keys = self._process_keys(vertex_label, "nullable_keys", properties[1:])
            vertex_label["nullable_keys"] = nullable_keys
            self._add_missing_properties(properties, property_labels, property_label_set)

    def _process_edge_labels(self, schema: Dict[str, Any], property_labels: list, property_label_set: set) -> None:
        for edge_label in schema["edgelabels"]:
            self._validate_edge_label(edge_label)
            properties = edge_label.get("properties", [])
            self._add_missing_properties(properties, property_labels, property_label_set)

    def _validate_vertex_label(self, vertex_label: Dict[str, Any]) -> None:
        check_type(vertex_label, dict, "VertexLabel in input data is not a dictionary.")
        if "name" not in vertex_label:
            log_and_raise("VertexLabel in input data does not contain 'name'.")
        check_type(vertex_label["name"], str, "'name' in vertex_label is not of correct type.")
        if "properties" not in vertex_label:
            log_and_raise("VertexLabel in input data does not contain 'properties'.")
        check_type(
            vertex_label["properties"],
            list,
            "'properties' in vertex_label is not of correct type.",
        )
        if len(vertex_label["properties"]) == 0:
            log_and_raise("'properties' in vertex_label is empty.")

    def _validate_edge_label(self, edge_label: Dict[str, Any]) -> None:
        check_type(edge_label, dict, "EdgeLabel in input data is not a dictionary.")
        if "name" not in edge_label or "source_label" not in edge_label or "target_label" not in edge_label:
            log_and_raise("EdgeLabel in input data does not contain 'name', 'source_label', 'target_label'.")
        check_type(edge_label["name"], str, "'name' in edge_label is not of correct type.")
        check_type(
            edge_label["source_label"],
            str,
            "'source_label' in edge_label is not of correct type.",
        )
        check_type(
            edge_label["target_label"],
            str,
            "'target_label' in edge_label is not of correct type.",
        )

    def _process_keys(self, label: Dict[str, Any], key_type: str, default_keys: list) -> list:
        keys = label.get(key_type, default_keys)
        check_type(keys, list, f"'{key_type}' in {label['name']} is not of correct type.")
        new_keys = [key for key in keys if key in label["properties"]]
        return new_keys

    def _add_missing_properties(self, properties: list, property_labels: list, property_label_set: set) -> None:
        for prop in properties:
            if prop not in property_label_set:
                property_labels.append(
                    {
                        "name": prop,
                        "data_type": PropertyDataType.DEFAULT.value,
                        "cardinality": PropertyCardinality.DEFAULT.value,
                    }
                )
                property_label_set.add(prop)
