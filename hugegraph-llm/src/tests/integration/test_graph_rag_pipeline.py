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


import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

import pytest

from tests.utils.mock import MockEmbedding

pytestmark = [pytest.mark.external, pytest.mark.slow]


class BaseLLM:
    def generate(self, prompt, **kwargs):
        pass

    async def async_generate(self, prompt, **kwargs):
        pass

    def get_llm_type(self):
        pass


# 模拟RAGPipeline类
class RAGPipeline:
    def __init__(self, llm=None, embedding=None):
        self.llm = llm
        self.embedding = embedding
        self.operators = {}

    def extract_word(self, text=None, language="english"):
        if "word_extract" in self.operators:
            return self.operators["word_extract"]({"query": text})
        return {"words": []}

    def extract_keywords(self, text=None, max_keywords=5, language="english", extract_template=None):
        if "keyword_extract" in self.operators:
            return self.operators["keyword_extract"]({"query": text})
        return {"keywords": []}

    def keywords_to_vid(self, by="keywords", topk_per_keyword=5, topk_per_query=10):
        if "semantic_id_query" in self.operators:
            return self.operators["semantic_id_query"]({"keywords": []})
        return {"match_vids": []}

    def query_graphdb(
        self,
        max_deep=2,
        max_graph_items=10,
        max_v_prop_len=2048,
        max_e_prop_len=256,
        prop_to_match=None,
        num_gremlin_generate_example=1,
        gremlin_prompt=None,
    ):
        if "graph_rag_query" in self.operators:
            return self.operators["graph_rag_query"]({"match_vids": []})
        return {"graph_result": []}

    def query_vector_index(self, max_items=3):
        if "vector_index_query" in self.operators:
            return self.operators["vector_index_query"]({"query": ""})
        return {"vector_result": []}

    def merge_dedup_rerank(
        self, graph_ratio=0.5, rerank_method="bleu", near_neighbor_first=False, custom_related_information=""
    ):
        if "merge_dedup_rerank" in self.operators:
            return self.operators["merge_dedup_rerank"]({"graph_result": [], "vector_result": []})
        return {"merged_result": []}

    def synthesize_answer(
        self,
        raw_answer=False,
        vector_only_answer=True,
        graph_only_answer=False,
        graph_vector_answer=False,
        answer_prompt=None,
    ):
        if "answer_synthesize" in self.operators:
            return self.operators["answer_synthesize"]({"merged_result": []})
        return {"answer": ""}

    def run(self, **kwargs):
        context = {"query": kwargs.get("query", "")}

        # 执行各个步骤
        if not kwargs.get("skip_extract_word", False):
            context.update(self.extract_word(text=context["query"]))

        if not kwargs.get("skip_extract_keywords", False):
            context.update(self.extract_keywords(text=context["query"]))

        if not kwargs.get("skip_keywords_to_vid", False):
            context.update(self.keywords_to_vid())

        if not kwargs.get("skip_query_graphdb", False):
            context.update(self.query_graphdb())

        if not kwargs.get("skip_query_vector_index", False):
            context.update(self.query_vector_index())

        if not kwargs.get("skip_merge_dedup_rerank", False):
            context.update(self.merge_dedup_rerank())

        if not kwargs.get("skip_synthesize_answer", False):
            context.update(
                self.synthesize_answer(
                    vector_only_answer=kwargs.get("vector_only_answer", False),
                    graph_only_answer=kwargs.get("graph_only_answer", False),
                    graph_vector_answer=kwargs.get("graph_vector_answer", False),
                )
            )

        return context


class MockLLM(BaseLLM):
    """Mock LLM class for testing"""

    def __init__(self):
        self.model = "mock_llm"

    def generate(self, prompt, **kwargs):
        # Return a simple mock response based on the prompt
        if "person" in prompt.lower():
            return "This is information about a person."
        if "movie" in prompt.lower():
            return "This is information about a movie."
        return "I don't have specific information about that."

    async def async_generate(self, prompt, **kwargs):
        # Async version returns the same as the sync version
        return self.generate(prompt, **kwargs)

    def get_llm_type(self):
        return "mock"


class TestGraphRAGPipeline(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for testing
        self.test_dir = tempfile.mkdtemp()

        # Create mock models
        self.embedding = MockEmbedding()
        self.llm = MockLLM()

        # Create mock operators
        self.mock_word_extract = MagicMock()
        self.mock_word_extract.return_value = {"words": ["person", "movie"]}

        self.mock_keyword_extract = MagicMock()
        self.mock_keyword_extract.return_value = {"keywords": ["person", "movie"]}

        self.mock_semantic_id_query = MagicMock()
        self.mock_semantic_id_query.return_value = {"match_vids": ["1:person", "2:movie"]}

        self.mock_graph_rag_query = MagicMock()
        self.mock_graph_rag_query.return_value = {
            "graph_result": ["Person: John Doe, Age: 30", "Movie: The Matrix, Year: 1999"]
        }

        self.mock_vector_index_query = MagicMock()
        self.mock_vector_index_query.return_value = {
            "vector_result": ["John Doe is a software engineer.", "The Matrix is a science fiction movie."]
        }

        self.mock_merge_dedup_rerank = MagicMock()
        self.mock_merge_dedup_rerank.return_value = {
            "merged_result": [
                "Person: John Doe, Age: 30",
                "Movie: The Matrix, Year: 1999",
                "John Doe is a software engineer.",
                "The Matrix is a science fiction movie.",
            ]
        }

        self.mock_answer_synthesize = MagicMock()
        self.mock_answer_synthesize.return_value = {
            "answer": (
                "John Doe is a 30-year-old software engineer. The Matrix is a science fiction movie released in 1999."
            )
        }

        # 创建RAGPipeline实例
        self.pipeline = RAGPipeline(llm=self.llm, embedding=self.embedding)
        self.pipeline.operators = {
            "word_extract": self.mock_word_extract,
            "keyword_extract": self.mock_keyword_extract,
            "semantic_id_query": self.mock_semantic_id_query,
            "graph_rag_query": self.mock_graph_rag_query,
            "vector_index_query": self.mock_vector_index_query,
            "merge_dedup_rerank": self.mock_merge_dedup_rerank,
            "answer_synthesize": self.mock_answer_synthesize,
        }

    def tearDown(self):
        # Clean up the temporary directory
        shutil.rmtree(self.test_dir)

    def test_rag_pipeline_end_to_end(self):
        # Run the pipeline with a query
        query = "Tell me about John Doe and The Matrix movie"
        result = self.pipeline.run(query=query)

        # Verify the result
        self.assertIn("answer", result)
        self.assertEqual(
            result["answer"],
            "John Doe is a 30-year-old software engineer. The Matrix is a science fiction movie released in 1999.",
        )

        # Verify that all operators were called
        self.mock_word_extract.assert_called_once()
        self.mock_keyword_extract.assert_called_once()
        self.mock_semantic_id_query.assert_called_once()
        self.mock_graph_rag_query.assert_called_once()
        self.mock_vector_index_query.assert_called_once()
        self.mock_merge_dedup_rerank.assert_called_once()
        self.mock_answer_synthesize.assert_called_once()

    def test_rag_pipeline_vector_only(self):
        # Run the pipeline with a query, skipping graph-related steps
        query = "Tell me about John Doe and The Matrix movie"
        result = self.pipeline.run(
            query=query,
            skip_keywords_to_vid=True,
            skip_query_graphdb=True,
            skip_merge_dedup_rerank=True,
            vector_only_answer=True,
        )

        # Verify the result
        self.assertIn("answer", result)
        self.assertEqual(
            result["answer"],
            "John Doe is a 30-year-old software engineer. The Matrix is a science fiction movie released in 1999.",
        )

        # Verify that only vector-related operators were called
        self.mock_word_extract.assert_called_once()
        self.mock_keyword_extract.assert_called_once()
        self.mock_semantic_id_query.assert_not_called()
        self.mock_graph_rag_query.assert_not_called()
        self.mock_vector_index_query.assert_called_once()
        self.mock_merge_dedup_rerank.assert_not_called()
        self.mock_answer_synthesize.assert_called_once()

    def test_rag_pipeline_graph_only(self):
        # Run the pipeline with a query, skipping vector-related steps
        query = "Tell me about John Doe and The Matrix movie"
        result = self.pipeline.run(
            query=query, skip_query_vector_index=True, skip_merge_dedup_rerank=True, graph_only_answer=True
        )

        # Verify the result
        self.assertIn("answer", result)
        self.assertEqual(
            result["answer"],
            "John Doe is a 30-year-old software engineer. The Matrix is a science fiction movie released in 1999.",
        )

        # Verify that only graph-related operators were called
        self.mock_word_extract.assert_called_once()
        self.mock_keyword_extract.assert_called_once()
        self.mock_semantic_id_query.assert_called_once()
        self.mock_graph_rag_query.assert_called_once()
        self.mock_vector_index_query.assert_not_called()
        self.mock_merge_dedup_rerank.assert_not_called()
        self.mock_answer_synthesize.assert_called_once()
