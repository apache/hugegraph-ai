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

from hugegraph_llm.operators.llm_op.disambiguate_data import DisambiguateData

pytestmark = pytest.mark.contract


class TestDisambiguateData(unittest.TestCase):
    def setUp(self):
        self.triples = {
            "triples": [
                (' "Alice "', ' "Age "', ' "25 "'),
                (' "Alice "', ' "Profession "', ' "lawyer "'),
                (' "Bob "', ' "Job "', ' "journalist "'),
                (' "Alice "', ' "Roommate of "', ' "Bob "'),
                (' "lucy "', "roommate", ' "Bob "'),
                (' "Alice "', ' "is the ownner of "', ' "http://www.alice.com "'),
                (' "Bob "', ' "Owns "', ' "http://www.bob.com "'),
            ]
        }

        self.triples_with_schema = {
            "vertices": [
                {
                    "name": "Alice",
                    "label": "person",
                    "properties": {"name": "Alice", "age": "25", "occupation": "lawyer"},
                },
                {
                    "name": "Bob",
                    "label": "person",
                    "properties": {"name": "Bob", "occupation": "journalist"},
                },
                {
                    "name": "www.alice.com",
                    "label": "webpage",
                    "properties": {"name": "www.alice.com", "url": "www.alice.com"},
                },
                {
                    "name": "www.bob.com",
                    "label": "webpage",
                    "properties": {"name": "www.bob.com", "url": "www.bob.com"},
                },
            ],
            "edges": [{"start": "Alice", "end": "Bob", "type": "roommate", "properties": {}}],
            "schema": {
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
            },
        }
        self.llm = None
        self.disambiguate_data = DisambiguateData(self.llm)

    def test_run(self):
        result = self.disambiguate_data.run(self.triples_with_schema)
        self.assertDictEqual(result, self.triples_with_schema)
