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

# pylint: disable=protected-access,no-member

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.operators.llm_op.gremlin_generate import GremlinGenerateSynthesize
from tests.fixtures.fake_llm import FakeLLM

pytestmark = pytest.mark.contract


class TestGremlinGenerateSynthesize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up class-level fixtures for immutable test data."""
        cls.sample_schema = {
            "vertexLabels": [
                {"name": "person", "properties": ["name", "age"]},
                {"name": "movie", "properties": ["title", "year"]},
            ],
            "edgeLabels": [{"name": "acted_in", "sourceLabel": "person", "targetLabel": "movie"}],
        }

        cls.sample_vertices = ["person:1", "movie:2"]

        cls.sample_query = "Find all movies that Tom Hanks acted in"

        cls.sample_custom_prompt = "Custom prompt template: {query}, {schema}, {example}, {vertices}"

        cls.sample_examples = [
            {"query": "who is Tom Hanks", "gremlin": "g.V().has('person', 'name', 'Tom Hanks')"},
            {
                "query": "what movies did Tom Hanks act in",
                "gremlin": "g.V().has('person', 'name', 'Tom Hanks').out('acted_in')",
            },
        ]

        cls.sample_gremlin_response = (
            "Here is the Gremlin query:\n```gremlin\ng.V().has('person', 'name', 'Tom Hanks').out('acted_in')\n```"
        )

        cls.sample_gremlin_query = "g.V().has('person', 'name', 'Tom Hanks').out('acted_in')"

    def setUp(self):
        """Set up instance-level fixtures for each test."""
        # Create mock LLM (fresh for each test)
        self.mock_llm = self._create_mock_llm()

        # Use class-level fixtures
        self.schema = self.sample_schema
        self.vertices = self.sample_vertices
        self.query = self.sample_query

    def _create_mock_llm(self):
        """Helper method to create a mock LLM."""
        mock_llm = MagicMock(spec=BaseLLM)
        mock_llm.agenerate = AsyncMock()
        mock_llm.generate.return_value = self.__class__.sample_gremlin_response
        return mock_llm

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        with patch("hugegraph_llm.operators.llm_op.gremlin_generate.LLMs") as mock_llms_class:
            mock_llms_instance = MagicMock()
            mock_llms_instance.get_text2gql_llm.return_value = self.mock_llm
            mock_llms_class.return_value = mock_llms_instance

            generator = GremlinGenerateSynthesize()

            self.assertEqual(generator.llm, self.mock_llm)
            self.assertIsNone(generator.schema)
            self.assertIsNone(generator.vertices)
            self.assertIsNotNone(generator.gremlin_prompt)

    def test_init_with_parameters(self):
        """Test initialization with provided parameters."""
        generator = GremlinGenerateSynthesize(
            llm=self.mock_llm,
            schema=self.schema,
            vertices=self.vertices,
            gremlin_prompt=self.sample_custom_prompt,
        )

        self.assertEqual(generator.llm, self.mock_llm)
        self.assertEqual(generator.schema, json.dumps(self.schema, ensure_ascii=False))
        self.assertEqual(generator.vertices, self.vertices)
        self.assertEqual(generator.gremlin_prompt, self.sample_custom_prompt)

    def test_init_with_string_schema(self):
        """Test initialization with schema as string."""
        schema_str = json.dumps(self.schema, ensure_ascii=False)

        generator = GremlinGenerateSynthesize(llm=self.mock_llm, schema=schema_str)

        self.assertEqual(generator.schema, schema_str)

    def test_extract_gremlin(self):
        """Test the _extract_response method."""
        generator = GremlinGenerateSynthesize(llm=self.mock_llm)

        # Test with valid gremlin code block
        gremlin = generator._extract_response(self.sample_gremlin_response)
        self.assertEqual(gremlin, self.sample_gremlin_query)

        # Test with invalid response - should return the original response stripped
        result = generator._extract_response("No gremlin code block here")
        self.assertEqual(result, "No gremlin code block here")

    def test_extract_gremlin_from_explanation_plus_block(self):
        """Test explanation text is stripped when a Gremlin block exists."""
        generator = GremlinGenerateSynthesize(llm=self.mock_llm)
        response = "Use this query:\n```gremlin\ng.V().hasLabel('person')\n```\nIt returns people."

        self.assertEqual(generator._extract_response(response), "g.V().hasLabel('person')")

    def test_extract_gremlin_uses_first_candidate_block(self):
        """Test multiple candidate blocks resolve to the first public result."""
        generator = GremlinGenerateSynthesize(llm=self.mock_llm)
        response = "```gremlin\ng.V().limit(1)\n```\n```gremlin\ng.E().limit(1)\n```"

        self.assertEqual(generator._extract_response(response), "g.V().limit(1)")

    def test_run_with_fake_llm_empty_output_returns_empty_gremlin(self):
        """Test empty LLM output is exposed as an empty Gremlin string."""
        generator = GremlinGenerateSynthesize(llm=FakeLLM(["", ""]))

        result = generator.run({"query": self.query})

        self.assertEqual(result["result"], "")
        self.assertEqual(result["raw_result"], "")
        self.assertEqual(result["call_count"], 2)

    def test_format_examples(self):
        """Test the _format_examples method."""
        generator = GremlinGenerateSynthesize(llm=self.mock_llm)

        # Test with valid examples
        formatted = generator._format_examples(self.sample_examples)
        self.assertIn("who is Tom Hanks", formatted)
        self.assertIn("g.V().has('person', 'name', 'Tom Hanks')", formatted)
        self.assertIn("what movies did Tom Hanks act in", formatted)

        # Test with empty examples
        self.assertIsNone(generator._format_examples([]))
        self.assertIsNone(generator._format_examples(None))

    def test_format_vertices(self):
        """Test the _format_vertices method."""
        generator = GremlinGenerateSynthesize(llm=self.mock_llm)

        # Test with valid vertices
        vertices = ["person:1", "movie:2", "person:3"]
        formatted = generator._format_vertices(vertices)
        self.assertIn("- 'person:1'", formatted)
        self.assertIn("- 'movie:2'", formatted)
        self.assertIn("- 'person:3'", formatted)

        # Test with empty vertices
        self.assertIsNone(generator._format_vertices([]))
        self.assertIsNone(generator._format_vertices(None))

    def test_run_with_valid_query(self):
        """Test the run method with a valid query."""
        # Create generator and run
        generator = GremlinGenerateSynthesize(llm=self.mock_llm)
        result = generator.run({"query": self.query})

        # Verify results
        self.assertEqual(result["query"], self.query)
        self.assertEqual(result["result"], self.sample_gremlin_query)

    def test_run_with_empty_query(self):
        """Test the run method with an empty query."""
        generator = GremlinGenerateSynthesize(llm=self.mock_llm)

        with self.assertRaises(ValueError):
            generator.run({})

        with self.assertRaises(ValueError):
            generator.run({"query": ""})

    def test_async_generate(self):
        """Test the run method with async functionality."""
        # Create generator with schema and vertices
        generator = GremlinGenerateSynthesize(llm=self.mock_llm, schema=self.schema, vertices=self.vertices)

        # Run the method
        result = generator.run({"query": self.query})

        # Verify results
        self.assertEqual(result["query"], self.query)
        self.assertEqual(result["result"], self.sample_gremlin_query)


if __name__ == "__main__":
    unittest.main()
