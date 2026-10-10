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

# pylint: disable=W0621

import json
import re
from typing import Any, Dict, List

from hugegraph_llm.config import prompt
from hugegraph_llm.document.chunk_split import ChunkSplitter
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.utils.log import log

# TODO: It is not clear whether there is any other dependence on the SCHEMA_EXAMPLE_PROMPT variable.
# Because the SCHEMA_EXAMPLE_PROMPT variable will no longer change based on
# prompt.extract_graph_prompt changes after the system loads, this does not seem to meet expectations.
SCHEMA_EXAMPLE_PROMPT = prompt.extract_graph_prompt


def generate_extract_property_graph_prompt(text, schema=None) -> str:
    return f"""---
Following the full instructions above, try to extract the following text from the given schema, output the JSON result:
# Input
## Text:
{text}
## Graph schema
{schema}

# Output"""


def split_text(text: str) -> List[str]:
    chunk_splitter = ChunkSplitter(split_type="paragraph", language="zh")
    chunks = chunk_splitter.split(text)
    return chunks


def filter_item(schema, items) -> List[Dict[str, Any]]:
    # filter vertex and edge with invalid properties
    filtered_items = []
    properties_map = {"vertex": {}, "edge": {}}
    for vertex in schema["vertexlabels"]:
        properties_map["vertex"][vertex["name"]] = {
            "primary_keys": vertex["primary_keys"],
            "nullable_keys": vertex["nullable_keys"],
            "properties": vertex["properties"],
        }
    for edge in schema["edgelabels"]:
        properties_map["edge"][edge["name"]] = {"properties": edge["properties"]}
    log.info("properties_map: %s", properties_map)
    for item in items:
        item_type = item["type"]
        if item_type in properties_map:
            label = item["label"]
            item["properties"] = {
                key: value
                for key, value in item["properties"].items()
                if key in properties_map[item_type][label]["properties"]
            }
        filtered_items.append(item)

    return filtered_items


class PropertyGraphExtract:
    def __init__(self, llm: BaseLLM, example_prompt: str = prompt.extract_graph_prompt) -> None:
        self.llm = llm
        self.example_prompt = example_prompt
        self.NECESSARY_ITEM_KEYS = {"label", "type", "properties"}  # pylint: disable=invalid-name

    def run(self, context: Dict[str, Any]) -> Dict[str, List[Any]]:
        schema = context["schema"]
        chunks = context["chunks"]
        if "vertices" not in context:
            context["vertices"] = []
        if "edges" not in context:
            context["edges"] = []
        items = []
        for chunk in chunks:
            proceeded_chunk = self.extract_property_graph_by_llm(schema, chunk)
            log.debug(
                "[LLM] %s input: %s \n output:%s",
                self.__class__.__name__,
                chunk,
                proceeded_chunk,
            )
            items.extend(self._extract_and_filter_label(schema, proceeded_chunk))
        items = filter_item(schema, items)
        for item in items:
            if item["type"] == "vertex":
                context["vertices"].append(item)
            elif item["type"] == "edge":
                context["edges"].append(item)

        context["call_count"] = context.get("call_count", 0) + len(chunks)
        return context

    def extract_property_graph_by_llm(self, schema, chunk):
        prompt = generate_extract_property_graph_prompt(chunk, schema)
        if self.example_prompt is not None:
            prompt = self.example_prompt + prompt
        return self.llm.generate(prompt=prompt)

    @staticmethod
    def _primary_key_id(vertex_label, properties):
        id_strategy = vertex_label.get("id_strategy")
        if id_strategy and str(id_strategy).upper() != "PRIMARY_KEY":
            return None
        primary_keys = vertex_label.get("primary_keys", [])
        if not primary_keys or "id" not in vertex_label:
            return None
        values = []
        for key in primary_keys:
            value = properties.get(key)
            if value is None or value == "":
                return None
            values.append(str(value))
        return f"{vertex_label['id']}:{'!'.join(values)}"

    def _normalize_vertices(self, vertices, vertex_label_map):
        vertex_id_map = {}
        normalized_vertices = []
        for vertex in vertices:
            label = vertex["label"]
            properties = vertex["properties"]
            canonical_id = self._primary_key_id(vertex_label_map[label], properties)
            original_id = vertex.get("id")
            if canonical_id is None:
                if original_id:
                    vertex_id_map[(label, original_id)] = original_id
                normalized_vertices.append(vertex)
                continue

            vertex["id"] = canonical_id
            vertex_id_map[(label, canonical_id)] = canonical_id
            if original_id:
                vertex_id_map[(label, original_id)] = canonical_id
            normalized_vertices.append(vertex)
        return normalized_vertices, vertex_id_map

    def _resolve_endpoint(self, edge, endpoint_key, label_key, legacy_key, vertex_label_map, vertex_id_map):
        endpoint = edge.get(endpoint_key)
        label = edge.get(label_key)
        if endpoint and label:
            return vertex_id_map.get((label, endpoint)), label

        legacy_endpoint = edge.get(legacy_key)
        if not isinstance(legacy_endpoint, dict):
            return None, label

        label = legacy_endpoint.get("label")
        properties = legacy_endpoint.get("properties", {})
        if label not in vertex_label_map:
            return None, label
        canonical_id = self._primary_key_id(vertex_label_map[label], properties)
        return vertex_id_map.get((label, canonical_id)), label

    def _normalize_edges(self, edges, edge_label_map, vertex_label_map, vertex_id_map):
        normalized_edges = []
        for edge in edges:
            edge_label = edge_label_map[edge["label"]]
            out_v, out_v_label = self._resolve_endpoint(
                edge,
                "outV",
                "outVLabel",
                "source",
                vertex_label_map,
                vertex_id_map,
            )
            in_v, in_v_label = self._resolve_endpoint(
                edge,
                "inV",
                "inVLabel",
                "target",
                vertex_label_map,
                vertex_id_map,
            )
            if not out_v or not in_v:
                log.warning("Invalid edge endpoints '%s' have been ignored.", edge)
                continue
            if out_v_label != edge_label.get("source_label") or in_v_label != edge_label.get("target_label"):
                log.warning("Invalid edge endpoint labels '%s' have been ignored.", edge)
                continue

            edge["outV"] = out_v
            edge["outVLabel"] = out_v_label
            edge["inV"] = in_v
            edge["inVLabel"] = in_v_label
            normalized_edges.append(edge)
        return normalized_edges

    def _extract_and_filter_label(self, schema, text) -> List[Dict[str, Any]]:
        # Strip markdown code blocks (e.g. ```json ... ```)
        text = re.sub(r"```\w*\n?", "", text)
        text = re.sub(r"```", "", text)
        text = text.strip()

        # Try to extract JSON (object or array)
        json_match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if not json_match:
            log.critical("Invalid property graph! No JSON found, please check the output format example in prompt.")
            return []
        json_str = json_match.group(1).strip()

        items = []
        try:
            property_graph = json.loads(json_str)
            # Handle flat array format: convert to {"vertices": [...], "edges": [...]}
            if isinstance(property_graph, list):
                vertices = [item for item in property_graph if isinstance(item, dict) and item.get("type") == "vertex"]
                edges = [item for item in property_graph if isinstance(item, dict) and item.get("type") == "edge"]
                property_graph = {"vertices": vertices, "edges": edges}
            # Expect property_graph to be a dict with keys "vertices" and "edges"
            if not (isinstance(property_graph, dict) and "vertices" in property_graph and "edges" in property_graph):
                log.critical("Invalid property graph format; expecting 'vertices' and 'edges'.")
                return items

            # Create sets for valid vertex and edge labels based on the schema
            vertex_label_map = {vertex["name"]: vertex for vertex in schema["vertexlabels"]}
            edge_label_map = {edge["name"]: edge for edge in schema["edgelabels"]}
            vertex_label_set = set(vertex_label_map)
            edge_label_set = set(edge_label_map)

            def process_items(item_list, valid_labels, item_type):
                parsed_items = []
                for item in item_list:
                    if not isinstance(item, dict):
                        log.warning("Invalid property graph item type '%s'.", type(item))
                        continue
                    item = dict(item)
                    item_type_value = item.get("type", item_type)
                    item["type"] = item_type_value
                    if not self.NECESSARY_ITEM_KEYS.issubset(item.keys()):
                        log.warning("Invalid item keys '%s'.", item.keys())
                        continue
                    if item_type_value != item_type:
                        log.warning("Invalid %s type '%s' has been ignored.", item_type, item_type_value)
                        continue
                    if item["label"] not in valid_labels:
                        log.warning(
                            "Invalid %s label '%s' has been ignored.",
                            item_type,
                            item["label"],
                        )
                        continue
                    parsed_items.append(item)
                return parsed_items

            vertex_items = process_items(property_graph["vertices"], vertex_label_set, "vertex")
            vertices, vertex_id_map = self._normalize_vertices(vertex_items, vertex_label_map)
            edge_items = process_items(property_graph["edges"], edge_label_set, "edge")
            edges = self._normalize_edges(edge_items, edge_label_map, vertex_label_map, vertex_id_map)
            items = vertices + edges
        except json.JSONDecodeError:
            log.critical("Invalid property graph JSON! Please check the extracted JSON data carefully")
        return items
