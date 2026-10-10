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
from typing import List, Literal, Optional, Union

from pyhugegraph.client import PyHugeClient

from hugegraph_llm.config import huge_settings
from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.operators.common_op.check_schema import CheckSchema
from hugegraph_llm.operators.common_op.merge_dedup_rerank import MergeDedupRerank
from hugegraph_llm.operators.common_op.print_result import PrintResult
from hugegraph_llm.operators.document_op.chunk_split import ChunkSplit
from hugegraph_llm.operators.document_op.word_extract import WordExtract
from hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph import Commit2Graph
from hugegraph_llm.operators.hugegraph_op.fetch_graph_data import FetchGraphData
from hugegraph_llm.operators.hugegraph_op.schema_manager import SchemaManager
from hugegraph_llm.operators.index_op.build_gremlin_example_index import (
    BuildGremlinExampleIndex,
)
from hugegraph_llm.operators.index_op.build_semantic_index import BuildSemanticIndex
from hugegraph_llm.operators.index_op.build_vector_index import BuildVectorIndex
from hugegraph_llm.operators.index_op.gremlin_example_index_query import (
    GremlinExampleIndexQuery,
)
from hugegraph_llm.operators.index_op.semantic_id_query import SemanticIdQuery
from hugegraph_llm.operators.index_op.vector_index_query import VectorIndexQuery
from hugegraph_llm.operators.llm_op.answer_synthesize import AnswerSynthesize
from hugegraph_llm.operators.llm_op.disambiguate_data import DisambiguateData
from hugegraph_llm.operators.llm_op.gremlin_generate import GremlinGenerateSynthesize
from hugegraph_llm.operators.llm_op.info_extract import InfoExtract
from hugegraph_llm.operators.llm_op.keyword_extract import KeywordExtract
from hugegraph_llm.operators.llm_op.property_graph_extract import PropertyGraphExtract
from hugegraph_llm.utils.decorators import log_operator_time, log_time, record_rpm


class OperatorList:
    def __init__(
        self,
        llm: BaseLLM,
        embedding: BaseEmbedding,
        graph: Optional[PyHugeClient] = None,
    ):
        self.llm = llm
        self.embedding = embedding
        self.result = None
        self.operators = []
        self.graph = graph

    def clear(self):
        self.operators = []
        return self

    def example_index_build(self, examples):
        self.operators.append(BuildGremlinExampleIndex(self.embedding, examples))
        return self

    def import_schema(self, from_hugegraph=None, from_extraction=None, from_user_defined=None):
        if from_hugegraph:
            self.operators.append(SchemaManager(from_hugegraph))
        elif from_user_defined:
            self.operators.append(CheckSchema(from_user_defined))
        elif from_extraction:
            raise NotImplementedError("Not implemented yet")
        else:
            raise ValueError("No input data / invalid schema type")
        return self

    def example_index_query(self, num_examples):
        self.operators.append(GremlinExampleIndexQuery(self.embedding, num_examples))
        return self

    def gremlin_generate_synthesize(
        self,
        schema,
        gremlin_prompt: Optional[str] = None,
        vertices: Optional[List[str]] = None,
    ):
        self.operators.append(GremlinGenerateSynthesize(self.llm, schema, vertices, gremlin_prompt))
        return self

    def print_result(self):
        self.operators.append(PrintResult())
        return self

    def fetch_graph_data(self):
        if self.graph is None:
            raise ValueError("graph client is required for fetch_graph_data operation")
        self.operators.append(FetchGraphData(self.graph))
        return self

    def chunk_split(
        self,
        text: Union[str, List[str]],  # text to be split
        split_type: Literal["document", "paragraph", "sentence"] = "document",
        language: Literal["zh", "en"] = "zh",
    ):
        self.operators.append(ChunkSplit(text, split_type, language))
        return self

    def extract_info(
        self,
        example_prompt: Optional[str] = None,
        extract_type: Literal["triples", "property_graph"] = "triples",
    ):
        if extract_type == "triples":
            self.operators.append(InfoExtract(self.llm, example_prompt))
        elif extract_type == "property_graph":
            self.operators.append(PropertyGraphExtract(self.llm, example_prompt))
        else:
            raise ValueError(f"invalid extract_type: {extract_type!r}, expected 'triples' or 'property_graph'")
        return self

    def disambiguate_word_sense(self):
        self.operators.append(DisambiguateData(self.llm))
        return self

    def commit_to_hugegraph(self):
        self.operators.append(Commit2Graph())
        return self

    def build_vertex_id_semantic_index(self):
        self.operators.append(BuildSemanticIndex(self.embedding))
        return self

    def build_vector_index(self):
        self.operators.append(BuildVectorIndex(self.embedding))
        return self

    def extract_word(self, text: Optional[str] = None):
        """
        Add a word extraction operator to the pipeline.

        :param text: Text to extract words from.
        :return: Self-instance for chaining.
        """
        self.operators.append(WordExtract(text=text))
        return self

    def extract_keywords(
        self,
        text: Optional[str] = None,
        extract_template: Optional[str] = None,
    ):
        """
        Add a keyword extraction operator to the pipeline.

        :param text: Text to extract keywords from.
        :param extract_template: Template for keyword extraction.
        :return: Self-instance for chaining.
        """
        self.operators.append(KeywordExtract(text=text, extract_template=extract_template))
        return self

    def keywords_to_vid(
        self,
        by: Literal["query", "keywords"] = "keywords",
        topk_per_keyword: int = huge_settings.topk_per_keyword,
        topk_per_query: int = 10,
        vector_dis_threshold: float = huge_settings.vector_dis_threshold,
    ):
        """
        Add a semantic ID query operator to the pipeline.
        :param by: Match by query or keywords.
        :param topk_per_keyword: Top K results per keyword.
        :param topk_per_query: Top K results per query.
        :param vector_dis_threshold: Vector distance threshold.
        :return: Self-instance for chaining.
        """
        self.operators.append(
            SemanticIdQuery(
                embedding=self.embedding,
                by=by,
                topk_per_keyword=topk_per_keyword,
                topk_per_query=topk_per_query,
                vector_dis_threshold=vector_dis_threshold,
            )
        )
        return self

    def query_vector_index(self, max_items: int = 3):
        """
        Add a vector index query operator to the pipeline.

        :param max_items: Maximum number of items to retrieve.
        :return: Self-instance for chaining.
        """
        self.operators.append(
            VectorIndexQuery(
                embedding=self.embedding,
                topk=max_items,
            )
        )
        return self

    def merge_dedup_rerank(
        self,
        graph_ratio: float = 0.5,
        rerank_method: Literal["bleu", "reranker"] = "bleu",
        near_neighbor_first: bool = False,
        custom_related_information: str = "",
        topk_return_results: int = huge_settings.topk_return_results,
    ):
        """
        Add a merge, deduplication, and rerank operator to the pipeline.

        :return: Self-instance for chaining.
        """
        self.operators.append(
            MergeDedupRerank(
                embedding=self.embedding,
                graph_ratio=graph_ratio,
                method=rerank_method,
                near_neighbor_first=near_neighbor_first,
                custom_related_information=custom_related_information,
                topk_return_results=topk_return_results,
            )
        )
        return self

    def synthesize_answer(
        self,
        raw_answer: bool = False,
        vector_only_answer: bool = True,
        graph_only_answer: bool = False,
        graph_vector_answer: bool = False,
        answer_prompt: Optional[str] = None,
    ):
        """
        Add an answer synthesis operator to the pipeline.

        :param raw_answer: Whether to return raw answers.
        :param vector_only_answer: Whether to return vector-only answers.
        :param graph_only_answer: Whether to return graph-only answers.
        :param graph_vector_answer: Whether to return graph-vector combined answers.
        :param answer_prompt: Template for the answer synthesis prompt.
        :return: Self-instance for chaining.
        """
        self.operators.append(
            AnswerSynthesize(
                raw_answer=raw_answer,
                vector_only_answer=vector_only_answer,
                graph_only_answer=graph_only_answer,
                graph_vector_answer=graph_vector_answer,
                prompt_template=answer_prompt,
            )
        )
        return self

    @log_time("total time")
    @record_rpm
    def run(self, **kwargs):
        context = kwargs
        for operator in self.operators:
            context = self._run_operator(operator, context)
        return context

    @log_operator_time
    def _run_operator(self, operator, context):
        return operator.run(context)
