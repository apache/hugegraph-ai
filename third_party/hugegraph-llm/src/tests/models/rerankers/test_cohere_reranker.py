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
from unittest.mock import MagicMock, patch

from hugegraph_llm.models.rerankers.cohere import CohereReranker


class TestCohereReranker(unittest.TestCase):
    def setUp(self):
        self.reranker = CohereReranker(
            api_key="test_api_key", base_url="https://api.cohere.ai/v1/rerank", model="rerank-english-v2.0"
        )

    @patch("requests.post")
    def test_get_rerank_lists(self, mock_post):
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": 2, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.7},
                {"index": 1, "relevance_score": 0.5},
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        # Test data
        query = "What is the capital of France?"
        documents = [
            "Paris is the capital of France.",
            "Berlin is the capital of Germany.",
            "Paris is known as the City of Light.",
        ]

        # Call the method
        result = self.reranker.get_rerank_lists(query, documents)

        # Assertions
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], "Paris is known as the City of Light.")
        self.assertEqual(result[1], "Paris is the capital of France.")
        self.assertEqual(result[2], "Berlin is the capital of Germany.")

        # Verify the API call
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["query"], query)
        self.assertEqual(kwargs["json"]["documents"], documents)
        self.assertEqual(kwargs["json"]["top_n"], 3)

    @patch("requests.post")
    def test_get_rerank_lists_with_top_n(self, mock_post):
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.7}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        # Test data
        query = "What is the capital of France?"
        documents = [
            "Paris is the capital of France.",
            "Berlin is the capital of Germany.",
            "Paris is known as the City of Light.",
        ]

        # Call the method with top_n=2
        result = self.reranker.get_rerank_lists(query, documents, top_n=2)

        # Assertions
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "Paris is known as the City of Light.")
        self.assertEqual(result[1], "Paris is the capital of France.")

        # Verify the API call
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["top_n"], 2)

    def test_get_rerank_lists_empty_documents(self):
        # Test with empty documents
        query = "What is the capital of France?"
        documents = []

        # Call the method
        with self.assertRaises(ValueError):
            self.reranker.get_rerank_lists(query, documents, top_n=1)

    def test_get_rerank_lists_top_n_zero(self):
        # Test with top_n=0
        query = "What is the capital of France?"
        documents = ["Paris is the capital of France."]

        # Call the method
        result = self.reranker.get_rerank_lists(query, documents, top_n=0)

        # Assertions
        self.assertEqual(result, [])
