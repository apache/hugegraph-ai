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
import time
import unittest
from unittest.mock import MagicMock, patch

import pytest

from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.operators.llm_op.property_graph_extract import (
    PropertyGraphExtract,
    filter_item,
    generate_extract_property_graph_prompt,
    split_text,
)
from tests.fixtures.fake_llm import FakeLLM

pytestmark = pytest.mark.contract


class TestPropertyGraphExtract(unittest.TestCase):
    def setUp(self):
        # Create mock LLM
        self.mock_llm = MagicMock(spec=BaseLLM)

        # Sample schema
        self.schema = {
            "vertexlabels": [
                {
                    "id": 1,
                    "name": "person",
                    "primary_keys": ["name"],
                    "nullable_keys": ["age"],
                    "properties": ["name", "age"],
                },
                {
                    "id": 2,
                    "name": "movie",
                    "primary_keys": ["title"],
                    "nullable_keys": ["year"],
                    "properties": ["title", "year"],
                },
            ],
            "edgelabels": [
                {"name": "acted_in", "properties": ["role"], "source_label": "person", "target_label": "movie"}
            ],
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
                    "label": "person",
                    "properties": {
                        "name": "Tom Hanks"
                    }
                },
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
                    "year": 1994,  # Non-string value
                    "ignored": "not in schema",
                },
            },
            {
                "type": "edge",
                "label": "acted_in",
                "properties": {
                    "role": "Forrest Gump",
                    "ignored": "not in schema",
                },
            },
        ]

        filtered_items = filter_item(self.schema, items)

        # Missing properties stay absent so Commit2Graph can apply schema-typed defaults.
        self.assertNotIn("age", filtered_items[0]["properties"])
        self.assertNotIn("title", filtered_items[1]["properties"])

        # Check that schema-typed values are preserved for Commit2Graph
        self.assertEqual(filtered_items[1]["properties"]["year"], 1994)
        self.assertNotIn("ignored", filtered_items[1]["properties"])
        self.assertEqual(filtered_items[2]["properties"]["role"], "Forrest Gump")
        self.assertNotIn("ignored", filtered_items[2]["properties"])

    def test_filter_item_accepts_parent_edge_label_without_properties(self):
        """Test parent edge labels without properties do not break filtering."""
        schema = {
            "vertexlabels": self.schema["vertexlabels"],
            "edgelabels": [
                {"name": "BELONGS_TO", "edgelabel_type": "PARENT"},
                *self.schema["edgelabels"],
            ],
        }

        filtered_items = filter_item(schema, [])

        self.assertEqual(filtered_items, [])

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

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["type"], "vertex")
        self.assertEqual(result[0]["label"], "person")
        self.assertEqual(result[1]["type"], "vertex")
        self.assertEqual(result[1]["label"], "movie")
        self.assertEqual(result[2]["type"], "edge")
        self.assertEqual(result[2]["label"], "acted_in")

    def test_extract_and_filter_label_markdown_json(self):
        """Test _extract_and_filter_label with JSON wrapped in markdown fences."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = f"""```json
{self.llm_responses[1]}
```"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["type"], "vertex")
        self.assertEqual(result[0]["label"], "person")
        self.assertEqual(result[1]["type"], "vertex")
        self.assertEqual(result[1]["label"], "movie")
        self.assertEqual(result[2]["type"], "edge")
        self.assertEqual(result[2]["label"], "acted_in")

    def test_extract_and_filter_label_markdown_json_with_prose(self):
        """Test fenced JSON can be parsed when the LLM adds prose."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = f"""Here is the extracted graph:
```
{self.llm_responses[1]}
```
Hope this helps."""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["type"], "vertex")
        self.assertEqual(result[0]["label"], "person")
        self.assertEqual(result[1]["type"], "vertex")
        self.assertEqual(result[1]["label"], "movie")
        self.assertEqual(result[2]["type"], "edge")
        self.assertEqual(result[2]["label"], "acted_in")

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
                "type": "vertex",
                "label": "movie",
                "properties": {
                    "title": "Forrest Gump"
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

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["type"], "vertex")
        self.assertEqual(result[0]["label"], "person")
        self.assertEqual(result[1]["type"], "vertex")
        self.assertEqual(result[1]["label"], "movie")
        self.assertEqual(result[2]["type"], "edge")
        self.assertEqual(result[2]["label"], "acted_in")

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
                "label": "movie",
                "properties": {
                    "title": "Forrest Gump"
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

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["type"], "vertex")
        self.assertEqual(result[0]["label"], "person")
        self.assertEqual(result[1]["type"], "vertex")
        self.assertEqual(result[1]["label"], "movie")
        self.assertEqual(result[2]["type"], "edge")
        self.assertEqual(result[2]["label"], "acted_in")

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

    def test_property_graph_extract_strips_fenced_json_with_fake_llm(self):
        """Test fake LLM fixture drives fenced JSON parser behavior."""
        llm = FakeLLM(['```json\n{"vertices": [], "edges": []}\n```'])
        extractor = PropertyGraphExtract(llm=llm)

        result = extractor._extract_and_filter_label({"vertexlabels": [], "edgelabels": []}, llm.generate())

        self.assertEqual(result, [])
        self.assertEqual(len(llm.calls), 1)

    def test_extract_and_filter_label_resolves_numeric_vertex_ids(self):
        """Test numeric LLM vertex ids can be resolved before commit."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """{
            "vertices": [
            {
                "id": 101,
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            },
            {
                "id": 202,
                "label": "movie",
                "properties": {
                    "title": "Forrest Gump"
                }
            }
            ],
            "edges": [
            {
                "label": "acted_in",
                "outV": 101,
                "outVLabel": "person",
                "inV": 202,
                "inVLabel": "movie",
                "properties": {
                    "role": "Forrest Gump"
                }
            }
            ]
        }"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(result[0]["id"], "1:Tom Hanks")
        self.assertEqual(result[1]["id"], "2:Forrest Gump")
        self.assertEqual(result[2]["outV"], "1:Tom Hanks")
        self.assertEqual(result[2]["inV"], "2:Forrest Gump")

    def test_extract_and_filter_label_preserves_duplicate_items_deterministically(self):
        """Test duplicate vertices and edges are parsed in stable order."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """{
            "vertices": [
            {
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            },
            {
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            },
            {
                "label": "movie",
                "properties": {
                    "title": "Forrest Gump"
                }
            }
            ],
            "edges": [
            {
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
        }"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual([item["type"] for item in result], ["vertex", "vertex", "vertex", "edge", "edge"])
        self.assertEqual(result[0]["id"], "1:Tom Hanks")
        self.assertEqual(result[1]["id"], "1:Tom Hanks")

    def test_extract_and_filter_label_infers_type_from_grouped_arrays(self):
        """Infer item type from vertices/edges containers when LLM omits it."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """{
            "vertices": [
            {
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            },
            {
                "label": "movie",
                "properties": {
                    "title": "Forrest Gump"
                }
            }
            ],
            "edges": [
            {
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
        }"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["type"], "vertex")
        self.assertEqual(result[0]["label"], "person")
        self.assertEqual(result[1]["type"], "vertex")
        self.assertEqual(result[1]["label"], "movie")
        self.assertEqual(result[2]["type"], "edge")
        self.assertEqual(result[2]["label"], "acted_in")

    def test_extract_and_filter_label_normalizes_primary_key_ids(self):
        """Normalize LLM vertex ids to schema-derived primary-key ids."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """{
            "vertices": [
            {
                "id": "person:Tom Hanks",
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            },
            {
                "id": "movie:Forrest Gump",
                "label": "movie",
                "properties": {
                    "title": "Forrest Gump"
                }
            }
            ],
            "edges": [
            {
                "label": "acted_in",
                "outV": "person:Tom Hanks",
                "outVLabel": "person",
                "inV": "movie:Forrest Gump",
                "inVLabel": "movie",
                "properties": {
                    "role": "Forrest Gump"
                }
            }
            ]
        }"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(result[0]["id"], "1:Tom Hanks")
        self.assertEqual(result[1]["id"], "2:Forrest Gump")
        self.assertEqual(result[2]["outV"], "1:Tom Hanks")
        self.assertEqual(result[2]["inV"], "2:Forrest Gump")

    def test_extract_and_filter_label_keeps_canonical_primary_key_ids(self):
        """Keep already-canonical vertex and edge ids intact."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """{
            "vertices": [
            {
                "id": "1:Tom Hanks",
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            },
            {
                "id": "2:Forrest Gump",
                "label": "movie",
                "properties": {
                    "title": "Forrest Gump"
                }
            }
            ],
            "edges": [
            {
                "label": "acted_in",
                "outV": "1:Tom Hanks",
                "outVLabel": "person",
                "inV": "2:Forrest Gump",
                "inVLabel": "movie",
                "properties": {
                    "role": "Forrest Gump"
                }
            }
            ]
        }"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(result[0]["id"], "1:Tom Hanks")
        self.assertEqual(result[1]["id"], "2:Forrest Gump")
        self.assertEqual(result[2]["outV"], "1:Tom Hanks")
        self.assertEqual(result[2]["inV"], "2:Forrest Gump")

    def test_extract_and_filter_label_normalizes_multiple_primary_key_ids(self):
        """Normalize multi-primary-key vertex ids in schema primary-key order."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        schema = {
            "vertexlabels": [
                {
                    "id": 3,
                    "name": "character",
                    "primary_keys": ["name", "universe"],
                    "nullable_keys": [],
                    "properties": ["name", "universe"],
                }
            ],
            "edgelabels": [],
        }
        text = """{
            "vertices": [
            {
                "id": "character:Tom!movie",
                "label": "character",
                "properties": {
                    "name": "Tom",
                    "universe": "movie"
                }
            }
            ],
            "edges": []
        }"""

        result = extractor._extract_and_filter_label(schema, text)

        self.assertEqual(result[0]["id"], "3:Tom!movie")

    def test_extract_and_filter_label_resolves_source_target_edge_refs(self):
        """Resolve source/target edge endpoints to canonical outV/inV ids."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """{
            "vertices": [
            {
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            },
            {
                "label": "movie",
                "properties": {
                    "title": "Forrest Gump"
                }
            }
            ],
            "edges": [
            {
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
        }"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(result[0]["id"], "1:Tom Hanks")
        self.assertEqual(result[1]["id"], "2:Forrest Gump")
        self.assertEqual(result[2]["outV"], "1:Tom Hanks")
        self.assertEqual(result[2]["outVLabel"], "person")
        self.assertEqual(result[2]["inV"], "2:Forrest Gump")
        self.assertEqual(result[2]["inVLabel"], "movie")

    def test_extract_and_filter_label_drops_edges_with_unresolved_endpoints(self):
        """Drop edges whose endpoints cannot be resolved before commit."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """{
            "vertices": [
            {
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            }
            ],
            "edges": [
            {
                "label": "acted_in",
                "outV": "person:Missing",
                "outVLabel": "person",
                "inV": "movie:Missing",
                "inVLabel": "movie",
                "properties": {
                    "role": "Forrest Gump"
                }
            }
            ]
        }"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "vertex")

    def test_extract_and_filter_label_drops_legacy_edges_with_missing_vertices(self):
        """Drop legacy source/target edges unless both endpoints are emitted as vertices."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """{
            "vertices": [
            {
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            }
            ],
            "edges": [
            {
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
        }"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "vertex")

    def test_extract_and_filter_label_keeps_explicit_custom_ids(self):
        """Keep self-consistent explicit ids when schema cannot derive primary-key ids."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        schema = {
            "vertexlabels": [
                {"name": "person", "id_strategy": "CUSTOMIZE_STRING", "properties": ["name"], "nullable_keys": []},
                {"name": "movie", "id_strategy": "CUSTOMIZE_STRING", "properties": ["title"], "nullable_keys": []},
            ],
            "edgelabels": [{"name": "acted_in", "properties": [], "source_label": "person", "target_label": "movie"}],
        }
        text = """{
            "vertices": [
            {
                "id": "Tom Hanks",
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            },
            {
                "id": "Forrest Gump",
                "label": "movie",
                "properties": {
                    "title": "Forrest Gump"
                }
            }
            ],
            "edges": [
            {
                "label": "acted_in",
                "outV": "Tom Hanks",
                "outVLabel": "person",
                "inV": "Forrest Gump",
                "inVLabel": "movie",
                "properties": {}
            }
            ]
        }"""

        result = extractor._extract_and_filter_label(schema, text)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[2]["outV"], "Tom Hanks")
        self.assertEqual(result[2]["inV"], "Forrest Gump")

    def test_extract_and_filter_label_keeps_explicit_custom_ids_with_label_metadata(self):
        """Do not rewrite custom ids even when schema includes ids and primary keys."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        schema = {
            "vertexlabels": [
                {
                    "id": 7,
                    "name": "person",
                    "id_strategy": "CUSTOMIZE_STRING",
                    "primary_keys": ["name"],
                    "properties": ["name"],
                    "nullable_keys": [],
                },
                {
                    "id": 8,
                    "name": "movie",
                    "id_strategy": "CUSTOMIZE_STRING",
                    "primary_keys": ["title"],
                    "properties": ["title"],
                    "nullable_keys": [],
                },
            ],
            "edgelabels": [{"name": "acted_in", "properties": [], "source_label": "person", "target_label": "movie"}],
        }
        text = """{
            "vertices": [
            {
                "id": "Tom Hanks",
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            },
            {
                "id": "Forrest Gump",
                "label": "movie",
                "properties": {
                    "title": "Forrest Gump"
                }
            }
            ],
            "edges": [
            {
                "label": "acted_in",
                "outV": "Tom Hanks",
                "outVLabel": "person",
                "inV": "Forrest Gump",
                "inVLabel": "movie",
                "properties": {}
            }
            ]
        }"""

        result = extractor._extract_and_filter_label(schema, text)

        self.assertEqual(result[0]["id"], "Tom Hanks")
        self.assertEqual(result[1]["id"], "Forrest Gump")
        self.assertEqual(result[2]["outV"], "Tom Hanks")
        self.assertEqual(result[2]["inV"], "Forrest Gump")

    def test_extract_and_filter_label_drops_edges_with_mismatched_endpoint_labels(self):
        """Drop edges whose endpoint labels conflict with the edge schema."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """{
            "vertices": [
            {
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            },
            {
                "label": "movie",
                "properties": {
                    "title": "Forrest Gump"
                }
            }
            ],
            "edges": [
            {
                "label": "acted_in",
                "outV": "1:Tom Hanks",
                "outVLabel": "movie",
                "inV": "2:Forrest Gump",
                "inVLabel": "person",
                "properties": {
                    "role": "Forrest Gump"
                }
            }
            ]
        }"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(len(result), 2)
        self.assertTrue(all(item["type"] == "vertex" for item in result))

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

    def test_extract_and_filter_label_rejects_explicit_type_mismatch(self):
        """Do not override an explicit item type that conflicts with its container."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """{
            "vertices": [
            {
                "type": "edge",
                "label": "person",
                "properties": {
                    "name": "Tom Hanks"
                }
            }
            ],
            "edges": [
            {
                "type": "vertex",
                "label": "acted_in",
                "properties": {
                    "role": "Forrest Gump"
                }
            }
            ]
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

    def test_extract_and_filter_label_drops_items_with_non_object_properties(self):
        """Drop malformed LLM items whose properties field is not an object."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        text = """{
            "vertices": [
            {
                "label": "person",
                "properties": null
            },
            {
                "label": "movie",
                "properties": {
                    "title": "Forrest Gump"
                }
            }
            ],
            "edges": [
            {
                "label": "acted_in",
                "properties": ["role"],
                "source": {
                    "label": "person",
                    "properties": ["Tom Hanks"]
                },
                "target": {
                    "label": "movie",
                    "properties": {
                        "title": "Forrest Gump"
                    }
                }
            }
            ]
        }"""

        result = extractor._extract_and_filter_label(self.schema, text)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "vertex")
        self.assertEqual(result[0]["label"], "movie")

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
        self.assertEqual(len(result["vertices"]), 3)
        self.assertEqual(len(result["edges"]), 1)
        self.assertEqual(result["call_count"], 2)

        # Check vertex properties
        self.assertEqual(result["vertices"][0]["properties"]["name"], "Tom Hanks")
        self.assertEqual(result["vertices"][2]["properties"]["title"], "Forrest Gump")

        # Check edge properties
        self.assertEqual(result["edges"][0]["properties"]["role"], "Forrest Gump")

    def test_run_with_parallel_chunks_preserves_input_order(self):
        """Test parallel chunk extraction keeps deterministic aggregation order."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)

        def fake_extract(_schema, chunk):
            if chunk == "slow chunk":
                time.sleep(0.02)
            name = "Alice" if chunk == "slow chunk" else "Bob"
            return json.dumps(
                {
                    "vertices": [
                        {
                            "type": "vertex",
                            "label": "person",
                            "properties": {"name": name},
                        }
                    ],
                    "edges": [],
                }
            )

        extractor.extract_property_graph_by_llm = MagicMock(side_effect=fake_extract)
        context = {
            "schema": self.schema,
            "chunks": ["slow chunk", "fast chunk"],
            "max_parallel_chunks": 8,
        }

        result = extractor.run(context)

        self.assertEqual([vertex["properties"]["name"] for vertex in result["vertices"]], ["Alice", "Bob"])
        self.assertEqual(result["call_count"], 2)
        self.assertEqual(result["max_parallel_chunks"], 2)
        self.assertEqual(extractor.extract_property_graph_by_llm.call_count, 2)

    @patch("hugegraph_llm.operators.llm_op.property_graph_extract.ThreadPoolExecutor")
    def test_run_with_single_parallel_chunk_uses_serial_path(self, mock_executor):
        """Test max_parallel_chunks=1 keeps the existing serial extraction path."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        extractor.extract_property_graph_by_llm = MagicMock(side_effect=self.llm_responses)
        context = {
            "schema": self.schema,
            "chunks": self.chunks,
            "max_parallel_chunks": 1,
        }

        result = extractor.run(context)

        mock_executor.assert_not_called()
        self.assertEqual(extractor.extract_property_graph_by_llm.call_count, 2)
        self.assertEqual(result["call_count"], 2)

    @patch("hugegraph_llm.operators.llm_op.property_graph_extract.ThreadPoolExecutor")
    def test_run_with_one_chunk_reduces_parallelism_to_direct_extract(self, mock_executor):
        """Test one pre-split chunk is extracted directly even when parallelism is higher."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        extractor.extract_property_graph_by_llm = MagicMock(return_value=self.llm_responses[0])
        context = {
            "schema": self.schema,
            "chunks": [self.chunks[0]],
            "max_parallel_chunks": 4,
        }

        result = extractor.run(context)

        mock_executor.assert_not_called()
        self.assertEqual(extractor.extract_property_graph_by_llm.call_count, 1)
        self.assertEqual(result["call_count"], 1)
        self.assertEqual(result["max_parallel_chunks"], 1)

    @patch("hugegraph_llm.operators.llm_op.property_graph_extract.ThreadPoolExecutor")
    def test_run_with_empty_chunks_keeps_parallelism_metadata_positive(self, mock_executor):
        """Test empty chunks do not record max_parallel_chunks as zero."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        extractor.extract_property_graph_by_llm = MagicMock()
        context = {
            "schema": self.schema,
            "chunks": [],
            "max_parallel_chunks": 4,
        }

        result = extractor.run(context)

        mock_executor.assert_not_called()
        extractor.extract_property_graph_by_llm.assert_not_called()
        self.assertEqual(result["call_count"], 0)
        self.assertEqual(result["max_parallel_chunks"], 1)

    def test_run_raises_when_chunk_output_is_malformed_json(self):
        """Test flow execution fails instead of silently dropping malformed chunk output."""
        extractor = PropertyGraphExtract(llm=self.mock_llm)
        extractor.extract_property_graph_by_llm = MagicMock(return_value='{"vertices": [], "edges": [}')
        context = {
            "schema": self.schema,
            "chunks": ["malformed output chunk"],
        }

        with self.assertRaisesRegex(ValueError, "Invalid property graph JSON") as error:
            extractor.run(context)

        self.assertIsInstance(error.exception.__cause__, json.JSONDecodeError)

    def test_run_falls_back_to_default_parallelism_for_invalid_context_value(self):
        """Test invalid operator-level parallelism input does not fail before extraction."""
        extractor = PropertyGraphExtract(llm=self.mock_llm, max_parallel_chunks=2)
        extractor.extract_property_graph_by_llm = MagicMock(return_value=self.llm_responses[0])
        context = {
            "schema": self.schema,
            "chunks": [self.chunks[0]],
            "max_parallel_chunks": "not-an-int",
        }

        result = extractor.run(context)

        self.assertEqual(result["call_count"], 1)
        self.assertEqual(result["max_parallel_chunks"], 1)

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
        self.assertEqual(len(result["vertices"]), 4)  # 1 existing + 3 new
        self.assertEqual(len(result["edges"]), 2)  # 1 existing + 1 new
        self.assertEqual(result["call_count"], 2)

        # Check that existing data is preserved
        self.assertEqual(result["vertices"][0]["properties"]["name"], "Leonardo DiCaprio")
        self.assertEqual(result["edges"][0]["properties"]["role"], "Jack Dawson")


def test_run_debug_logs_do_not_include_raw_chunk_or_llm_output():
    schema = {
        "vertexlabels": [
            {
                "id": 1,
                "name": "person",
                "primary_keys": ["name"],
                "nullable_keys": [],
                "properties": ["name"],
            }
        ],
        "edgelabels": [],
    }
    sensitive_chunk = "Alice secret source document"
    sensitive_output = json.dumps(
        {
            "vertices": [
                {
                    "type": "vertex",
                    "label": "person",
                    "properties": {"name": "Alice secret model output"},
                }
            ],
            "edges": [],
        }
    )
    extractor = PropertyGraphExtract(llm=MagicMock(spec=BaseLLM))
    extractor.extract_property_graph_by_llm = MagicMock(return_value=sensitive_output)

    with patch("hugegraph_llm.operators.llm_op.property_graph_extract.log.debug") as debug_log:
        extractor.run({"schema": schema, "chunks": [sensitive_chunk]})

    logged_args = " ".join(str(arg) for call in debug_log.call_args_list for arg in call.args)
    assert "chunk processed" in logged_args
    assert sensitive_chunk not in logged_args
    assert "Alice secret model output" not in logged_args


def test_invalid_edge_warning_does_not_include_raw_edge_payload():
    schema = {
        "vertexlabels": [
            {
                "id": 1,
                "name": "person",
                "primary_keys": ["name"],
                "nullable_keys": [],
                "properties": ["name"],
            },
            {
                "id": 2,
                "name": "movie",
                "primary_keys": ["title"],
                "nullable_keys": [],
                "properties": ["title"],
            },
        ],
        "edgelabels": [{"name": "acted_in", "properties": ["role"], "source_label": "person", "target_label": "movie"}],
    }
    graph_json = json.dumps(
        {
            "vertices": [
                {
                    "type": "vertex",
                    "label": "person",
                    "properties": {"name": "Alice secret vertex"},
                }
            ],
            "edges": [
                {
                    "type": "edge",
                    "label": "acted_in",
                    "properties": {"role": "sensitive role"},
                    "source": {"label": "person", "properties": {"name": "Alice secret vertex"}},
                    "target": {"label": "movie", "properties": {"title": "Missing secret movie"}},
                }
            ],
        }
    )
    extractor = PropertyGraphExtract(llm=MagicMock(spec=BaseLLM))

    with patch("hugegraph_llm.operators.llm_op.property_graph_extract.log.warning") as warning_log:
        extractor._extract_and_filter_label(schema, graph_json, raise_on_invalid=True)

    logged_args = " ".join(str(arg) for call in warning_log.call_args_list for arg in call.args)
    assert "Invalid edge endpoints" in logged_args
    assert "sensitive role" not in logged_args
    assert "Alice secret vertex" not in logged_args
    assert "Missing secret movie" not in logged_args


if __name__ == "__main__":
    unittest.main()
