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

import unittest

import pytest

from hugegraph_llm.operators.llm_op.info_extract import (
    InfoExtract,
    extract_triples_by_regex,
    extract_triples_by_regex_with_schema,
)

pytestmark = pytest.mark.contract


class TestInfoExtract(unittest.TestCase):
    def setUp(self):
        self.schema = {
            "vertices": [
                {"vertex_label": "person", "properties": ["name", "age", "occupation"]},
                {"vertex_label": "webpage", "properties": ["name", "url"]},
            ],
            "edges": [
                {
                    "edge_label": "roommate",
                    "source_vertex_label": "person",
                    "target_vertex_label": "person",
                    "properties": [],
                }
            ],
        }

        self.llm = None
        self.info_extract = InfoExtract(self.llm, "text")

        self.llm_output = """
        {"id": "as-rymwkgbvqf", "object": "chat.completion", "created": 1706599975,
                  "result": "Based on the given graph schema and the extracted text, we can extract
                  the following triples:\n\n
                  1. (Alice, name, Alice) - person\n
                  2. (Alice, age, 25) - person\n
                  3. (Alice, occupation, lawyer) - person\n
                  4. (Bob, name, Bob) - person\n
                  5. (Bob, occupation, journalist) - person\n
                  6. (Alice, roommate, Bob) - roommate\n
                  7. (www.alice.com, name, www.alice.com) - webpage\n
                  8. (www.alice.com, url, www.alice.com) - webpage\n
                  9. (www.bob.com, name, www.bob.com) - webpage\n
                  10. (www.bob.com, url, www.bob.com) - webpage\n\n
                  However, the schema does not provide a direct relationship between people and
                  webpages they own. To establish such a relationship, we might need to introduce
                  a new edge label like \"owns\" or modify the schema accordingly. Assuming we
                  introduce a new edge label \"owns\", we can extract the following additional
                  triples:\n\n
                  1. (Alice, owns, www.alice.com) - owns\n2. (Bob, owns, www.bob.com) - owns\n\n
                  Please note that the extraction of some triples, like the webpage name and URL,
                  might seem redundant since they are the same. However,
                  I included them to strictly follow the given format. In a real-world scenario,
                  such redundancy might be avoided or handled differently.",
                  "is_truncated": false, "need_clear_history": false, "finish_reason": "normal",
                  "usage": {"prompt_tokens": 221, "completion_tokens": 325, "total_tokens": 546}}
    """

    def test_extract_by_regex_with_schema(self):
        graph = {"triples": [], "vertices": [], "edges": [], "schema": self.schema}
        extract_triples_by_regex_with_schema(self.schema, self.llm_output, graph)
        graph.pop("triples")
        # Convert dict_values to list for comparison
        expected_vertices = [
            {
                "id": "person-Alice",
                "name": "Alice",
                "label": "person",
                "properties": {"name": "Alice", "age": "25", "occupation": "lawyer"},
            },
            {
                "id": "person-Bob",
                "name": "Bob",
                "label": "person",
                "properties": {"name": "Bob", "occupation": "journalist"},
            },
            {
                "id": "webpage-www.alice.com",
                "name": "www.alice.com",
                "label": "webpage",
                "properties": {"name": "www.alice.com", "url": "www.alice.com"},
            },
            {
                "id": "webpage-www.bob.com",
                "name": "www.bob.com",
                "label": "webpage",
                "properties": {"name": "www.bob.com", "url": "www.bob.com"},
            },
        ]

        expected_edges = [{"start": "person-Alice", "end": "person-Bob", "type": "roommate", "properties": {}}]

        # Sort vertices and edges for consistent comparison
        actual_vertices = sorted(graph["vertices"], key=lambda x: x["id"])
        expected_vertices = sorted(expected_vertices, key=lambda x: x["id"])
        actual_edges = sorted(graph["edges"], key=lambda x: (x["start"], x["end"]))
        expected_edges = sorted(expected_edges, key=lambda x: (x["start"], x["end"]))

        self.assertEqual(actual_vertices, expected_vertices)
        self.assertEqual(actual_edges, expected_edges)
        self.assertEqual(graph["schema"], self.schema)

    def test_extract_by_regex(self):
        graph = {"triples": []}
        extract_triples_by_regex(self.llm_output, graph)
        self.assertEqual(
            graph,
            {
                "triples": [
                    ("Alice", "name", "Alice"),
                    ("Alice", "age", "25"),
                    ("Alice", "occupation", "lawyer"),
                    ("Bob", "name", "Bob"),
                    ("Bob", "occupation", "journalist"),
                    ("Alice", "roommate", "Bob"),
                    ("www.alice.com", "name", "www.alice.com"),
                    ("www.alice.com", "url", "www.alice.com"),
                    ("www.bob.com", "name", "www.bob.com"),
                    ("www.bob.com", "url", "www.bob.com"),
                    ("Alice", "owns", "www.alice.com"),
                    ("Bob", "owns", "www.bob.com"),
                ]
            },
        )
