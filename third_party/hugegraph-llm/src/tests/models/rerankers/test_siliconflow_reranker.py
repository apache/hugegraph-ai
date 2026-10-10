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

from hugegraph_llm.models.rerankers.siliconflow import SiliconReranker


class TestSiliconReranker(unittest.TestCase):
    def setUp(self):
        self.reranker = SiliconReranker(api_key="test_api_key", model="bge-reranker-large")

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
        query = "What is the capital of China?"
        documents = [
            "Beijing is the capital of China.",
            "Shanghai is the largest city in China.",
            "Beijing is home to the Forbidden City.",
        ]

        # Call the method
        result = self.reranker.get_rerank_lists(query, documents)

        # Assertions
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], "Beijing is home to the Forbidden City.")
        self.assertEqual(result[1], "Beijing is the capital of China.")
        self.assertEqual(result[2], "Shanghai is the largest city in China.")

        # Verify the API call
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["query"], query)
        self.assertEqual(kwargs["json"]["documents"], documents)
        self.assertEqual(kwargs["json"]["top_n"], 3)
        self.assertEqual(kwargs["json"]["model"], "bge-reranker-large")
        self.assertEqual(kwargs["headers"]["authorization"], "Bearer test_api_key")

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
        query = "What is the capital of China?"
        documents = [
            "Beijing is the capital of China.",
            "Shanghai is the largest city in China.",
            "Beijing is home to the Forbidden City.",
        ]

        # Call the method with top_n=2
        result = self.reranker.get_rerank_lists(query, documents, top_n=2)

        # Assertions
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "Beijing is home to the Forbidden City.")
        self.assertEqual(result[1], "Beijing is the capital of China.")

        # Verify the API call
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["top_n"], 2)

    def test_get_rerank_lists_empty_documents(self):
        # Test with empty documents
        query = "What is the capital of China?"
        documents = []

        # Call the method
        with self.assertRaises(ValueError) as cm:
            self.reranker.get_rerank_lists(query, documents, top_n=1)

        # Verify the error message
        self.assertIn("Documents list cannot be empty", str(cm.exception))

    def test_get_rerank_lists_negative_top_n(self):
        # Test with negative top_n
        query = "What is the capital of China?"
        documents = ["Beijing is the capital of China."]

        # Call the method
        with self.assertRaises(ValueError) as cm:
            self.reranker.get_rerank_lists(query, documents, top_n=-1)

        # Verify the error message
        self.assertIn("'top_n' should be non-negative", str(cm.exception))

    def test_get_rerank_lists_top_n_exceeds_documents(self):
        # Test with top_n greater than number of documents
        query = "What is the capital of China?"
        documents = ["Beijing is the capital of China."]

        # Call the method
        with self.assertRaises(ValueError) as cm:
            self.reranker.get_rerank_lists(query, documents, top_n=5)

        # Verify the error message
        self.assertIn("'top_n' should be less than or equal to the number of documents", str(cm.exception))

    @patch("requests.post")
    def test_get_rerank_lists_top_n_zero(self, mock_post):
        # Test with top_n=0
        query = "What is the capital of China?"
        documents = ["Beijing is the capital of China."]

        # Call the method
        result = self.reranker.get_rerank_lists(query, documents, top_n=0)

        # Assertions
        self.assertEqual(result, [])
        # Verify that no API call was made due to short-circuit logic
        mock_post.assert_not_called()
