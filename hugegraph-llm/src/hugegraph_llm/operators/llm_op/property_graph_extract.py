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
        if item_type == "vertex":
            label = item["label"]
            non_nullable_keys = set(properties_map[item_type][label]["properties"]).difference(
                set(properties_map[item_type][label]["nullable_keys"])
            )
            for key in non_nullable_keys:
                if key not in item["properties"]:
                    item["properties"][key] = "NULL"
        for key, value in item["properties"].items():
            if not isinstance(value, str):
                item["properties"][key] = str(value)
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
            vertex_label_set = {vertex["name"] for vertex in schema["vertexlabels"]}
            edge_label_set = {edge["name"] for edge in schema["edgelabels"]}

            def process_items(item_list, valid_labels, item_type):
                for item in item_list:
                    if not isinstance(item, dict):
                        log.warning("Invalid property graph item type '%s'.", type(item))
                        continue
                    if not self.NECESSARY_ITEM_KEYS.issubset(item.keys()):
                        log.warning("Invalid item keys '%s'.", item.keys())
                        continue
                    if item["type"] != item_type:
                        log.warning("Invalid %s type '%s' has been ignored.", item_type, item["type"])
                        continue
                    if item["label"] not in valid_labels:
                        log.warning(
                            "Invalid %s label '%s' has been ignored.",
                            item_type,
                            item["label"],
                        )
                        continue
                    items.append(item)

            process_items(property_graph["vertices"], vertex_label_set, "vertex")
            process_items(property_graph["edges"], edge_label_set, "edge")
        except json.JSONDecodeError:
            log.critical("Invalid property graph JSON! Please check the extracted JSON data carefully")
        return items
