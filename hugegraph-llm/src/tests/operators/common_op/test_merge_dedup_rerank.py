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

import unittest
from unittest.mock import MagicMock, patch

from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.operators.common_op.merge_dedup_rerank import (
    MergeDedupRerank,
    _bleu_rerank,
    get_bleu_score,
)


class BaseMergeDedupRerankTest(unittest.TestCase):
    """Base test class with common setup and test data."""

    def setUp(self):
        """Set up common test fixtures."""
        self.mock_embedding = MagicMock(spec=BaseEmbedding)
        self.query = "What is artificial intelligence?"
        self.vector_results = [
            "Artificial intelligence is a branch of computer science.",
            "AI is the simulation of human intelligence by machines.",
            "Artificial intelligence involves creating systems that can perform tasks requiring human intelligence.",
        ]
        self.graph_results = [
            "AI research includes reasoning, knowledge representation, "
            "planning, learning, natural language processing.",
            "Machine learning is a subset of artificial intelligence.",
            "Deep learning is a type of machine learning based on artificial neural networks.",
        ]


class TestMergeDedupRerankInit(BaseMergeDedupRerankTest):
    """Test initialization and basic functionality."""

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        merger = MergeDedupRerank(self.mock_embedding)
        self.assertEqual(merger.embedding, self.mock_embedding)
        self.assertEqual(merger.method, "bleu")
        self.assertEqual(merger.graph_ratio, 0.5)
        self.assertFalse(merger.near_neighbor_first)
        self.assertIsNone(merger.custom_related_information)

    @patch("hugegraph_llm.operators.common_op.merge_dedup_rerank.llm_settings")
    def test_init_with_parameters(self, mock_llm_settings):
        """Test initialization with provided parameters."""
        # Mock the reranker_type to allow reranker method
        mock_llm_settings.reranker_type = "mock_reranker"

        merger = MergeDedupRerank(
            self.mock_embedding,
            topk_return_results=5,
            graph_ratio=0.7,
            method="reranker",
            near_neighbor_first=True,
            custom_related_information="Additional context",
        )
        self.assertEqual(merger.embedding, self.mock_embedding)
        self.assertEqual(merger.topk_return_results, 5)
        self.assertEqual(merger.graph_ratio, 0.7)
        self.assertEqual(merger.method, "reranker")
        self.assertTrue(merger.near_neighbor_first)
        self.assertEqual(merger.custom_related_information, "Additional context")

    def test_init_with_invalid_method(self):
        """Test initialization with invalid method."""
        with self.assertRaises(AssertionError):
            MergeDedupRerank(self.mock_embedding, method="invalid_method")

    def test_init_with_priority(self):
        """Test initialization with priority flag."""
        with self.assertRaises(ValueError):
            MergeDedupRerank(self.mock_embedding, priority=True)


class TestMergeDedupRerankBleu(BaseMergeDedupRerankTest):
    """Test BLEU scoring and ranking functionality."""

    def test_get_bleu_score(self):
        """Test the get_bleu_score function."""
        query = "artificial intelligence"
        content = "AI is artificial intelligence"
        score = get_bleu_score(query, content)
        self.assertIsInstance(score, float)
        self.assertTrue(0 <= score <= 1)

    def test_bleu_rerank(self):
        """Test the _bleu_rerank function."""
        query = "artificial intelligence"
        results = [
            "Natural language processing is a field of AI.",
            "AI is artificial intelligence.",
            "Machine learning is a subset of AI.",
        ]
        reranked = _bleu_rerank(query, results)
        self.assertEqual(len(reranked), 3)
        # The second result should be ranked first as it contains the exact query terms
        self.assertEqual(reranked[0], "AI is artificial intelligence.")

    @patch("hugegraph_llm.operators.common_op.merge_dedup_rerank._bleu_rerank")
    def test_dedup_and_rerank_bleu(self, mock_bleu_rerank):
        """Test the _dedup_and_rerank method with bleu method."""
        # Setup mock
        mock_bleu_rerank.return_value = ["result1", "result2", "result3"]

        # Create merger with bleu method
        merger = MergeDedupRerank(self.mock_embedding, method="bleu")

        # Call the method
        results = ["result1", "result2", "result2", "result3"]  # Note the duplicate
        reranked = merger._dedup_and_rerank("query", results, 2)

        # Verify that duplicates were removed and _bleu_rerank was called
        mock_bleu_rerank.assert_called_once()
        self.assertEqual(len(reranked), 2)


class TestMergeDedupRerankReranker(BaseMergeDedupRerankTest):
    """Test external reranker integration."""

    @patch("hugegraph_llm.operators.common_op.merge_dedup_rerank.llm_settings")
    @patch("hugegraph_llm.operators.common_op.merge_dedup_rerank.Rerankers")
    def test_dedup_and_rerank_reranker(self, mock_rerankers_class, mock_llm_settings):
        """Test the _dedup_and_rerank method with reranker method."""
        # Mock the reranker_type to allow reranker method
        mock_llm_settings.reranker_type = "mock_reranker"

        # Setup mock for reranker
        mock_reranker = MagicMock()
        mock_reranker.get_rerank_lists.return_value = ["result3", "result1"]
        mock_rerankers_instance = MagicMock()
        mock_rerankers_instance.get_reranker.return_value = mock_reranker
        mock_rerankers_class.return_value = mock_rerankers_instance

        # Create merger with reranker method
        merger = MergeDedupRerank(self.mock_embedding, method="reranker")

        # Call the method
        results = ["result1", "result2", "result2", "result3"]  # Note the duplicate
        reranked = merger._dedup_and_rerank("query", results, 2)

        # Verify that duplicates were removed and reranker was called
        mock_reranker.get_rerank_lists.assert_called_once()
        self.assertEqual(len(reranked), 2)
        self.assertEqual(reranked[0], "result3")

    @patch("hugegraph_llm.operators.common_op.merge_dedup_rerank.llm_settings")
    @patch("hugegraph_llm.operators.common_op.merge_dedup_rerank.Rerankers")
    def test_rerank_with_vertex_degree(self, mock_rerankers_class, mock_llm_settings):
        """Test the _rerank_with_vertex_degree method."""
        # Mock the reranker_type to allow reranker method
        mock_llm_settings.reranker_type = "mock_reranker"

        # Setup mock for reranker
        mock_reranker = MagicMock()
        mock_reranker.get_rerank_lists.side_effect = [
            ["vertex1_1", "vertex1_2"],
            ["vertex2_1", "vertex2_2"],
        ]
        mock_rerankers_instance = MagicMock()
        mock_rerankers_instance.get_reranker.return_value = mock_reranker
        mock_rerankers_class.return_value = mock_rerankers_instance

        # Create merger with reranker method and near_neighbor_first
        merger = MergeDedupRerank(self.mock_embedding, method="reranker", near_neighbor_first=True)

        # Create test data
        results = ["result1", "result2"]
        vertex_degree_list = [["vertex1_1", "vertex1_2"], ["vertex2_1", "vertex2_2"]]
        knowledge_with_degree = {
            "result1": ["vertex1_1", "vertex2_1"],
            "result2": ["vertex1_2", "vertex2_2"],
        }

        # Call the method
        reranked = merger._rerank_with_vertex_degree(self.query, results, 2, vertex_degree_list, knowledge_with_degree)

        # Verify that reranker was called for each vertex degree list
        self.assertEqual(mock_reranker.get_rerank_lists.call_count, 2)

        # Verify the results
        self.assertEqual(len(reranked), 2)

    def test_rerank_with_vertex_degree_no_list(self):
        """Test the _rerank_with_vertex_degree method with no vertex degree list."""
        # Create merger
        merger = MergeDedupRerank(self.mock_embedding)

        # Mock the _dedup_and_rerank method
        merger._dedup_and_rerank = MagicMock()
        merger._dedup_and_rerank.return_value = ["result1", "result2"]

        # Call the method with empty vertex_degree_list
        reranked = merger._rerank_with_vertex_degree(self.query, ["result1", "result2"], 2, [], {})

        # Verify that _dedup_and_rerank was called
        merger._dedup_and_rerank.assert_called_once()

        # Verify the results
        self.assertEqual(reranked, ["result1", "result2"])


class TestMergeDedupRerankRun(BaseMergeDedupRerankTest):
    """Test main run functionality with different search configurations."""

    def test_run_with_vector_and_graph_search(self):
        """Test the run method with both vector and graph search."""
        # Create merger
        merger = MergeDedupRerank(self.mock_embedding, topk_return_results=4, graph_ratio=0.5)

        # Create context
        context = {
            "query": self.query,
            "vector_search": True,
            "graph_search": True,
            "vector_result": self.vector_results,
            "graph_result": self.graph_results,
        }

        # Mock the _dedup_and_rerank method
        merger._dedup_and_rerank = MagicMock()
        merger._dedup_and_rerank.side_effect = [
            ["vector1", "vector2"],  # For vector results
            ["graph1", "graph2"],  # For graph results
        ]

        # Run the method
        result = merger.run(context)

        # Verify that _dedup_and_rerank was called twice with correct parameters
        self.assertEqual(merger._dedup_and_rerank.call_count, 2)
        # First call for vector results
        merger._dedup_and_rerank.assert_any_call(self.query, self.vector_results, 2)
        # Second call for graph results
        merger._dedup_and_rerank.assert_any_call(self.query, self.graph_results, 2)

        # Verify the results
        self.assertEqual(result["vector_result"], ["vector1", "vector2"])
        self.assertEqual(result["graph_result"], ["graph1", "graph2"])
        self.assertEqual(result["graph_ratio"], 0.5)

    def test_run_with_only_vector_search(self):
        """Test the run method with only vector search."""
        # Create merger
        merger = MergeDedupRerank(self.mock_embedding, topk_return_results=3)

        # Create context
        context = {
            "query": self.query,
            "vector_search": True,
            "graph_search": False,
            "vector_result": self.vector_results,
        }

        # Mock the _dedup_and_rerank method to return different values for different calls
        original_dedup_and_rerank = merger._dedup_and_rerank

        def mock_dedup_and_rerank(query, results, topn):  # pylint: disable=unused-argument
            if results == self.vector_results:
                return ["vector1", "vector2", "vector3"]
            return []  # For empty graph results

        merger._dedup_and_rerank = mock_dedup_and_rerank

        # Run the method
        result = merger.run(context)

        # Restore the original method
        merger._dedup_and_rerank = original_dedup_and_rerank

        # Verify the results
        self.assertEqual(result["vector_result"], ["vector1", "vector2", "vector3"])
        self.assertEqual(result["graph_result"], [])

    def test_run_with_only_graph_search(self):
        """Test the run method with only graph search."""
        # Create merger
        merger = MergeDedupRerank(self.mock_embedding, topk_return_results=3)

        # Create context
        context = {
            "query": self.query,
            "vector_search": False,
            "graph_search": True,
            "graph_result": self.graph_results,
        }

        # Mock the _dedup_and_rerank method to return different values for different calls
        original_dedup_and_rerank = merger._dedup_and_rerank

        def mock_dedup_and_rerank(query, results, topn):  # pylint: disable=unused-argument
            if results == self.graph_results:
                return ["graph1", "graph2", "graph3"]
            return []  # For empty vector results

        merger._dedup_and_rerank = mock_dedup_and_rerank

        # Run the method
        result = merger.run(context)

        # Restore the original method
        merger._dedup_and_rerank = original_dedup_and_rerank

        # Verify the results
        self.assertEqual(result["vector_result"], [])
        self.assertEqual(result["graph_result"], ["graph1", "graph2", "graph3"])

    @patch("hugegraph_llm.operators.common_op.merge_dedup_rerank.llm_settings")
    @patch("hugegraph_llm.operators.common_op.merge_dedup_rerank.Rerankers")
    def test_run_reranker_handles_empty_and_duplicate_results(self, mock_rerankers_class, mock_llm_settings):
        """Empty inputs, zero top_n, and duplicate-shrunk inputs must not trip reranker validation."""
        from hugegraph_llm.models.rerankers.cohere import CohereReranker

        mock_llm_settings.reranker_type = "cohere"
        real_reranker = CohereReranker(api_key="test-key", base_url="https://example.com/rerank", model="test")
        mock_rerankers_instance = MagicMock()
        mock_rerankers_instance.get_reranker.return_value = real_reranker
        mock_rerankers_class.return_value = mock_rerankers_instance

        merger = MergeDedupRerank(
            self.mock_embedding,
            topk_return_results=4,
            graph_ratio=0.5,
            method="reranker",
            custom_related_information=" extra",
        )

        # Missing query, empty vector_result, and duplicate-collapsed graph_result (1 unique < top_n=2)
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"results": [{"index": 0}]}
            mock_post.return_value = mock_resp

            result = merger.run(
                {
                    "vector_search": True,
                    "graph_search": True,
                    "vector_result": [],
                    "graph_result": ["only_one", "only_one"],
                }
            )

        self.assertEqual(result["vector_result"], [])
        self.assertEqual(result["graph_result"], ["only_one"])
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["json"]["top_n"], 1)
        self.assertEqual(mock_post.call_args.kwargs["json"]["query"], " extra")

    def test_rerank_with_vertex_degree_missing_or_unindexed_entries(self):
        """near_neighbor_first handles None knowledge_with_degree and entries absent from vertex_degree_list."""
        merger = MergeDedupRerank(self.mock_embedding, method="bleu", near_neighbor_first=True)
        reranked = merger._rerank_with_vertex_degree(
            self.query,
            ["unlisted_result", "listed_result"],
            2,
            [["v1"]],
            None,
        )
        self.assertEqual(set(reranked), {"unlisted_result", "listed_result"})

        # Entry present in knowledge_with_degree but absent from vertex_degree_list[0], plus duplicate + non-mutation
        knowledge_map = {"missing_node": ["unknown_v"], "present_node": ["present_v"]}
        reranked_partial = merger._rerank_with_vertex_degree(
            self.query,
            ["missing_node", "present_node", "present_node", "unmapped_node"],
            3,
            [["present_v"], ["d2_v"]],
            knowledge_map,
        )
        self.assertEqual(reranked_partial, ["present_node", "missing_node", "unmapped_node"])
        self.assertEqual(knowledge_map, {"missing_node": ["unknown_v"], "present_node": ["present_v"]})

    @patch("hugegraph_llm.operators.common_op.merge_dedup_rerank.llm_settings")
    @patch("hugegraph_llm.operators.common_op.merge_dedup_rerank.Rerankers")
    def test_rerank_with_vertex_degree_reranker_empty_sublist(self, mock_rerankers_class, mock_llm_settings):
        """Empty depth buckets in vertex_degree_list should not call online reranker with []."""
        from hugegraph_llm.models.rerankers.cohere import CohereReranker

        mock_llm_settings.reranker_type = "cohere"
        real_reranker = CohereReranker(api_key="test-key", base_url="https://example.com/rerank", model="test")
        mock_rerankers_instance = MagicMock()
        mock_rerankers_instance.get_reranker.return_value = real_reranker
        mock_rerankers_class.return_value = mock_rerankers_instance

        merger = MergeDedupRerank(self.mock_embedding, method="reranker", near_neighbor_first=True)
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"results": [{"index": 1}, {"index": 0}]}
            mock_post.return_value = mock_resp

            reranked = merger._rerank_with_vertex_degree(
                self.query,
                ["res_a", "res_b"],
                2,
                [[], ["v_a", "v_b"]],
                {"res_a": ["", "v_a"], "res_b": ["", "v_b"]},
            )

        self.assertEqual(reranked, ["res_b", "res_a"])
        mock_post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
