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

import re
from typing import Any, Dict, List, Optional

from hugegraph_llm.document.chunk_split import ChunkSplitter
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.utils.log import log

SCHEMA_EXAMPLE_PROMPT = """## Main Task
Extract Triples from the given text and graph schema

## Basic Rules
1. The output format must be: (X,Y,Z) - LABEL
In this format, Y must be a value from "properties" or "edge_label",
and LABEL must be X's vertex_label or Y's edge_label.
2. Don't extract attribute/property fields that do not exist in the given schema
3. Ensure the extract property is in the same type as the schema (like 'age' should be a number)
4. Translate the given schema filed into Chinese if the given text is Chinese but the schema is in English (Optional)

## Example (Note: Update the example to correspond to the given text and schema)
### Input example:
Graph schema:
{"vertices":[{"vertex_label":"person","properties":["name","age","occupation"]}], "edges":[{"edge_label":"roommate",
"source_vertex_label":"person","target_vertex_label":"person","properties":["date"]]}
Text:
Meet Sarah, a 30-year-old attorney, and her roommate,
James, whom she's shared a home with since 2010. James,
in his professional life, works as a journalist.

### Output example:
(Sarah, name, Sarah) - person
(Sarah, age, 30) - person
(Sarah, occupation, attorney) - person
(James, name, James) - person
(James, occupation, journalist) - person
(Sarah, roommate, James) - roommate
(James, roommate, Sarah) - roommate
(Sarah, date, 2010) - roommate
"""


def generate_extract_triple_prompt(text, schema=None) -> str:
    text_based_prompt = f"""
Extract subject-verb-object (SPO) triples from text strictly according to the
following format, each structure has only three elements: ("vertex_1", "edge", "vertex_2").
For example:
Alice lawyer and is 25 years old and Bob is her roommate since 2001. Bob works as a journalist.
Alice owns the webpage www.alice.com and Bob owns the webpage www.bob.com
Output: [("Alice", "Age", "25"),("Alice", "Profession", "lawyer"),("Bob", "Job", "journalist"),
("Alice", "Roommate of", "Bob"),("Alice", "Owns", "https://www.alice.com"),
("Bob", "Owns", "https://www.bob.com")]

The extracted text is: {text}"""

    schema_real_prompt = f"""## Real result
1. The extracted text is: {text}
2. The graph schema is: {schema}
"""

    if schema:
        return schema_real_prompt
    log.warning("Recommend to provide a graph schema to improve the extraction accuracy. Now using the default schema.")
    return text_based_prompt


def split_text(text: str) -> List[str]:
    chunk_splitter = ChunkSplitter(split_type="paragraph", language="en")
    chunks = chunk_splitter.split(text)
    return chunks


def extract_triples_by_regex(text, triples):
    text = text.replace("\\n", " ").replace("\\", " ").replace("\n", " ")
    pattern = r"\((.*?), (.*?), (.*?)\)"
    triples["triples"] += re.findall(pattern, text)


def extract_triples_by_regex_with_schema(schema, text, graph):
    text = text.replace("\\n", " ").replace("\\", " ").replace("\n", " ")
    pattern = r"\((.*?), (.*?), (.*?)\) - ([^ ]*)"
    matches = re.findall(pattern, text)

    vertices_dict = {v["id"]: v for v in graph["vertices"]}
    for match in matches:
        s, p, o, label = [item.strip() for item in match]
        if None in [label, s, p, o]:
            continue
        # TODO: use a more efficient way to compare the extract & input property
        p_lower = p.lower()
        for vertex in schema["vertices"]:
            if vertex["vertex_label"] == label and any(pp.lower() == p_lower for pp in vertex["properties"]):
                id = f"{label}-{s}"
                if id not in vertices_dict:
                    vertices_dict[id] = {
                        "id": id,
                        "name": s,
                        "label": label,
                        "properties": {p: o},
                    }
                else:
                    vertices_dict[id]["properties"].update({p: o})
                break
        for edge in schema["edges"]:
            if edge["edge_label"] == label:
                source_label = edge["source_vertex_label"]
                source_id = f"{source_label}-{s}"
                if source_id not in vertices_dict:
                    vertices_dict[source_id] = {
                        "id": source_id,
                        "name": s,
                        "label": source_label,
                        "properties": {},
                    }
                target_label = edge["target_vertex_label"]
                target_id = f"{target_label}-{o}"
                if target_id not in vertices_dict:
                    vertices_dict[target_id] = {
                        "id": target_id,
                        "name": o,
                        "label": target_label,
                        "properties": {},
                    }
                graph["edges"].append(
                    {
                        "start": source_id,
                        "end": target_id,
                        "type": label,
                        "properties": {},
                    }
                )
                break
    graph["vertices"] = list(vertices_dict.values())


class InfoExtract:
    def __init__(self, llm: BaseLLM, example_prompt: Optional[str] = None) -> None:
        self.llm = llm
        self.example_prompt = example_prompt

    def run(self, context: Dict[str, Any]) -> Dict[str, List[Any]]:
        chunks = context["chunks"]
        schema = context["schema"]

        if schema:
            context["vertices"] = []
            context["edges"] = []
        else:
            context["triples"] = []

        for sentence in chunks:
            proceeded_chunk = self.extract_triples_by_llm(schema, sentence)
            log.debug(
                "[Legacy] %s input: %s \n output:%s",
                self.__class__.__name__,
                sentence,
                proceeded_chunk,
            )
            if schema:
                extract_triples_by_regex_with_schema(schema, proceeded_chunk, context)
            else:
                extract_triples_by_regex(proceeded_chunk, context)

        context["call_count"] = context.get("call_count", 0) + len(chunks)
        return self._filter_long_id(context)

    def extract_triples_by_llm(self, schema, chunk) -> str:
        prompt = generate_extract_triple_prompt(chunk, schema)
        if self.example_prompt is not None:
            prompt = self.example_prompt + prompt
        return self.llm.generate(prompt=prompt)

    # TODO: make 'max_length' be a configurable param in settings.py/settings.cfg
    def valid(self, element_id: str, max_length: int = 256) -> bool:
        if len(element_id.encode("utf-8")) >= max_length:
            log.warning("Filter out GraphElementID too long: %s", element_id)
            return False
        return True

    def _filter_long_id(self, graph) -> Dict[str, List[Any]]:
        graph["vertices"] = [vertex for vertex in graph["vertices"] if self.valid(vertex["id"])]
        graph["edges"] = [edge for edge in graph["edges"] if self.valid(edge["start"]) and self.valid(edge["end"])]
        return graph
