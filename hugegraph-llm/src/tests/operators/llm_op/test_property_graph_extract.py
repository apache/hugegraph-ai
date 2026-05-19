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

# pylint: disable=protected-access

import json
import unittest
from unittest.mock import MagicMock, patch

from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.operators.llm_op.property_graph_extract import (
    PropertyGraphExtract,
    filter_item,
    generate_extract_property_graph_prompt,
    split_text,
)


class TestPropertyGraphExtract(unittest.TestCase):
    def setUp(self):
        # Create mock LLM
        self.mock_llm = MagicMock(spec=BaseLLM)

        # Sample schema
        self.schema = {
            "vertexlabels": [
                {
                    "name": "person",
                    "primary_keys": ["name"],
                    "nullable_keys": ["age"],
                    "properties": ["name", "age"],
                },
                {
                    "name": "movie",
                    "primary_keys": ["title"],
                    "nullable_keys": ["year"],
                    "properties": ["title", "year"],
                },
            ],
            "edgelabels": [{"name": "acted_in", "properties": ["role"]}],
        }

        # Sample text chunks
        self.chunks = [
            "Tom Hanks is an American actor born in 1956.",
            "Forrest Gump is a movie released in 1994. Tom Hanks played the role of Forrest Gump.",
        ]

        # Sample LLM responses
        self.llm_responses = [
            """{
                "vertices": [
                {
                    "type": "vertex",
                    "label": "person",
                    "properties": {
                        "name": "Tom Hanks",
                        "age": "1956"
                    }
                }
                ],
                "edges": []
            }""",
            """{
                "vertices": [
                {
                    "type": "vertex",
                    "label": "movie",
                    "properties": {
                        "title": "Forrest Gump",
                        "year": "1994"
                    }
                    }
                ],
                "edges": [
                {
                    "type": "edge",
                    "label": "acted_in",
                    "properties": {
                        "role": "Forrest Gump"
                    },
                    "source": {
                        "label": "person",
                        "properties": {
                            "name": "Tom Hanks"
                        }
                    },
                    "target": {
                        "label": "movie",
                        "properties": {
                            "title": "Forrest Gump"
                        }
                    }
                }
                ]
            }""",
        ]

    def test_init(self):
        """Test initialization of PropertyGraphExtract."""
        custom_prompt = "Custom prompt template"
        extractor = PropertyGraphExtract(llm=self.mock_llm, example_prompt=custom_prompt)

        self.assertEqual(extractor.llm, self.mock_llm)
        self.assertEqual(extractor.example_prompt, custom_prompt)
        self.assertEqual(extractor.NECESSARY_ITEM_KEYS, {"label", "type", "properties"})

    def test_generate_extract_property_graph_prompt(self):
        """Test the generate_extract_property_graph_prompt function."""
        text = "Sample text"
        schema = json.dumps(self.schema)

        prompt = generate_extract_property_graph_prompt(text, schema)

        self.assertIn("Sample text", prompt)
        self.assertIn(schema, prompt)

    def test_split_text(self):
        """Test the split_text function."""
        with patch("hugegraph_llm.operators.llm_op.property_graph_extract.ChunkSplitter") as mock_splitter_class:
            mock_splitter = MagicMock()
            mock_splitter.split.return_value = ["chunk1", "chunk2"]
            mock_splitter_class.return_value = mock_splitter

            result = split_text("Sample text with multiple paragraphs")

            mock_splitter_class.assert_called_once_with(split_type="paragraph", language="zh")
            mock_splitter.split.assert_called_once_with("Sample text with multiple paragraphs")
            self.assertEqual(result, ["chunk1", "chunk2"])

    def test_filter_item(self):
        """Test the filter_item function."""
        items = [
            {
                "type": "vertex",
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                    # Missing 'age' which is nullable
                },
            },
            {
                "type": "vertex",
                "label": "movie",
                "properties": {
                    # Missing 'title' which is non-nullable
                    "year": 1994  # Non-string value
                },
            },
        ]

        filtered_items = filter_item(self.schema, items)

        # Check that non-nullable keys are added with NULL value
        # Note: 'age' is nullable, so it won't be added automatically
        self.assertNotIn("age", filtered_items[0]["properties"])

        # Check that title (non-nullable) was added with NULL value
        self.assertEqual(filtered_items[1]["properties"]["title"], "NULL")

        # Check that year was converted to string
        self.assertEqual(filtered_items[1]["properties"]["year"], "1994")

    def test_extract_property_graph_by_llm(self):
        """Test the extract_property_graph_by_llm method."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        self.mock_llm.generate.return_value = self.llm_responses[0]

        result = extractor.extract_property_graph_by_llm(json.dumps(self.schema), self.chunks[0])

        self.mock_llm.generate.assert_called_once()
        self.assertEqual(result, self.llm_responses[0])

    def test_extract_and_filter_label_valid_json(self):
        """Test the _extract_and_filter_label method with valid JSON."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)

        # Valid JSON with vertex and edge
        text = self.llm_responses[1]

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "vertex")
        self.assertEqual(result[0]["label"], "movie")
        self.assertEqual(result[1]["type"], "edge")
        self.assertEqual(result[1]["label"], "acted_in")

    def test_extract_and_filter_label_markdown_json(self):
        """Test _extract_and_filter_label with JSON wrapped in markdown fences."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = f"""```json
{self.llm_responses[1]}
```"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "vertex")
        self.assertEqual(result[0]["label"], "movie")
        self.assertEqual(result[1]["type"], "edge")
        self.assertEqual(result[1]["label"], "acted_in")

    def test_extract_and_filter_label_markdown_json_with_prose(self):
        """Test fenced JSON can be parsed when the LLM adds prose."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = f"""Here is the extracted graph:
```
{self.llm_responses[1]}
```
Hope this helps."""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "vertex")
        self.assertEqual(result[0]["label"], "movie")
        self.assertEqual(result[1]["type"], "edge")
        self.assertEqual(result[1]["label"], "acted_in")

    def test_extract_and_filter_label_flat_array_json(self):
        """Test _extract_and_filter_label converts flat arrays to vertices and edges."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """```json
        [
            {
                "type": "vertex",
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            },
            {
                "type": "edge",
                "label": "acted_in",
                "properties": {
                    "role": "Forrest Gump"
                },
                "source": {
                    "label": "person",
                    "properties": {
                        "name": "Tom Hanks"
                    }
                },
                "target": {
                    "label": "movie",
                    "properties": {
                        "title": "Forrest Gump"
                    }
                }
            }
        ]
        ```"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "vertex")
        self.assertEqual(result[0]["label"], "person")
        self.assertEqual(result[1]["type"], "edge")
        self.assertEqual(result[1]["label"], "acted_in")

    def test_extract_and_filter_label_flat_array_filters_invalid_items(self):
        """Test flat arrays keep valid graph items and drop invalid ones."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """[
            {
                "type": "vertex",
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            },
            {
                "type": "vertex",
                "label": "unknown_label",
                "properties": {
                    "name": "Unknown"
                }
            },
            {
                "type": "edge",
                "label": "acted_in",
                "properties": {
                    "role": "Forrest Gump"
                },
                "source": {
                    "label": "person",
                    "properties": {
                        "name": "Tom Hanks"
                    }
                },
                "target": {
                    "label": "movie",
                    "properties": {
                        "title": "Forrest Gump"
                    }
                }
            },
            {
                "type": "edge",
                "label": "unknown_edge",
                "properties": {}
            },
            {
                "type": "note",
                "label": "person",
                "properties": {}
            },
            "not-a-dict"
        ]"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "vertex")
        self.assertEqual(result[0]["label"], "person")
        self.assertEqual(result[1]["type"], "edge")
        self.assertEqual(result[1]["label"], "acted_in")

    def test_extract_and_filter_label_malformed_fenced_json(self):
        """Test malformed fenced JSON returns no graph items."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """```json
        {
            "vertices": [
                {
                    "type": "vertex",
                    "label": "person",
                    "properties": {
                        "name": "Tom Hanks"
                    }
                }
            ],
            "edges": []
        ```
        """

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(result, [])

    def test_extract_and_filter_label_invalid_json(self):
        """Test the _extract_and_filter_label method with invalid JSON."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)

        # Invalid JSON
        text = "This is not a valid JSON"

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(result, [])

    def test_extract_and_filter_label_invalid_item_type(self):
        """Test the _extract_and_filter_label method with invalid item type."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)

        # JSON with invalid item type
        text = """{
            "vertices": [
            {
                "type": "invalid_type",
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            }
            ],
            "edges": []
        }"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(result, [])

    def test_extract_and_filter_label_invalid_label(self):
        """Test the _extract_and_filter_label method with invalid label."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)

        # JSON with invalid label
        text = """{
            "vertices": [
            {
                "type": "vertex",
                "label": "invalid_label",
                "properties": {
                    "name": "Tom Hanks"
                }
            }
            ],
            "edges": []
        }"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(result, [])

    def test_extract_and_filter_label_missing_keys(self):
        """Test the _extract_and_filter_label method with missing necessary keys."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)

        # JSON with missing necessary keys
        text = """{
            "vertices": [
            {
                "type": "vertex",
                "label": "person"
                // Missing properties key
            }
            ],
            "edges": []
        }"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(result, [])

    def test_run(self):
        """Test the run method."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)

        # Mock the extract_property_graph_by_llm method
        extractor.extract_property_graph_by_llm = MagicMock(side_effect=self.llm_responses)

        # Create context
        context = {"schema": self.schema, "chunks": self.chunks}

        # Run the method
        result = extractor.run(context)

        # Verify that extract_property_graph_by_llm was called for each chunk
        self.assertEqual(extractor.extract_property_graph_by_llm.call_count, 2)

        # Verify the results
        self.assertEqual(len(result["vertices"]), 2)
        self.assertEqual(len(result["edges"]), 1)
        self.assertEqual(result["call_count"], 2)

        # Check vertex properties
        self.assertEqual(result["vertices"][0]["properties"]["name"], "Tom Hanks")
        self.assertEqual(result["vertices"][1]["properties"]["title"], "Forrest Gump")

        # Check edge properties
        self.assertEqual(result["edges"][0]["properties"]["role"], "Forrest Gump")

    def test_run_with_existing_vertices_and_edges(self):
        """Test the run method with existing vertices and edges."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)

        # Mock the extract_property_graph_by_llm method
        extractor.extract_property_graph_by_llm = MagicMock(side_effect=self.llm_responses)

        # Create context with existing vertices and edges
        context = {
            "schema": self.schema,
            "chunks": self.chunks,
            "vertices": [
                {
                    "type": "vertex",
                    "label": "person",
                    "properties": {"name": "Leonardo DiCaprio", "age": "1974"},
                }
            ],
            "edges": [
                {
                    "type": "edge",
                    "label": "acted_in",
                    "properties": {"role": "Jack Dawson"},
                    "source": {"label": "person", "properties": {"name": "Leonardo DiCaprio"}},
                    "target": {"label": "movie", "properties": {"title": "Titanic"}},
                }
            ],
        }

        # Run the method
        result = extractor.run(context)

        # Verify the results
        self.assertEqual(len(result["vertices"]), 3)  # 1 existing + 2 new
        self.assertEqual(len(result["edges"]), 2)  # 1 existing + 1 new
        self.assertEqual(result["call_count"], 2)

        # Check that existing data is preserved
        self.assertEqual(result["vertices"][0]["properties"]["name"], "Leonardo DiCaprio")
        self.assertEqual(result["edges"][0]["properties"]["role"], "Jack Dawson")


if __name__ == "__main__":
    unittest.main()
