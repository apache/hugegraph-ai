#  Licensed to the Apache Software Foundation (ASF) under one or more
#  contributor license agreements.  See the NOTICE file distributed with
#  this work for additional information regarding copyright ownership.
#  The ASF licenses this file to You under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance with
#  the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.


from typing import Literal, Optional, cast

from pycgraph import GCondition, GPipeline, GRegion

from hugegraph_llm.config import huge_settings, prompt
from hugegraph_llm.flows.common import BaseFlow
from hugegraph_llm.nodes.common_node.merge_rerank_node import MergeRerankNode
from hugegraph_llm.nodes.hugegraph_node.graph_query_node import GraphQueryNode
from hugegraph_llm.nodes.hugegraph_node.schema import SchemaNode
from hugegraph_llm.nodes.index_node.semantic_id_query_node import SemanticIdQueryNode
from hugegraph_llm.nodes.llm_node.answer_synthesize_node import AnswerSynthesizeNode
from hugegraph_llm.nodes.llm_node.keyword_extract_node import KeywordExtractNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState
from hugegraph_llm.utils.log import log


class GraphRecallCondition(GCondition):
    def choose(self):
        prepared_input: WkFlowInput = cast(WkFlowInput, self.getGParamWithNoEmpty("wkflow_input"))
        return 0 if prepared_input.is_graph_rag_recall else 1


class VectorOnlyCondition(GCondition):
    def choose(self):
        prepared_input: WkFlowInput = cast(WkFlowInput, self.getGParamWithNoEmpty("wkflow_input"))
        return 0 if prepared_input.is_vector_only else 1


# pylint: disable=arguments-differ,keyword-arg-before-vararg
class RAGGraphOnlyFlow(BaseFlow):
    """
    Workflow for graph-only answering (graph_only_answer)
    """

    def prepare(
        self,
        prepared_input: WkFlowInput,
        query: str,
        vector_search: bool = False,
        graph_search: bool = True,
        raw_answer: bool = False,
        vector_only_answer: bool = False,
        graph_only_answer: bool = True,
        graph_vector_answer: bool = False,
        rerank_method: Literal["bleu", "reranker"] = "bleu",
        near_neighbor_first: bool = False,
        custom_related_information: str = "",
        answer_prompt: Optional[str] = None,
        keywords_extract_prompt: Optional[str] = None,
        gremlin_tmpl_num: Optional[int] = -1,
        gremlin_prompt: Optional[str] = None,
        max_graph_items: Optional[int] = None,
        topk_return_results: Optional[int] = None,
        vector_dis_threshold: Optional[float] = None,
        topk_per_keyword: Optional[int] = None,
        is_graph_rag_recall: bool = False,
        is_vector_only: bool = False,
        **kwargs,
    ):
        prepared_input.query = query
        prepared_input.vector_search = vector_search
        prepared_input.graph_search = graph_search
        prepared_input.raw_answer = raw_answer
        prepared_input.vector_only_answer = vector_only_answer
        prepared_input.graph_only_answer = graph_only_answer
        prepared_input.graph_vector_answer = graph_vector_answer
        prepared_input.gremlin_tmpl_num = gremlin_tmpl_num
        prepared_input.gremlin_prompt = gremlin_prompt or prompt.gremlin_generate_prompt
        prepared_input.max_graph_items = max_graph_items or huge_settings.max_graph_items
        prepared_input.topk_per_keyword = topk_per_keyword or huge_settings.topk_per_keyword
        prepared_input.topk_return_results = topk_return_results or huge_settings.topk_return_results
        prepared_input.rerank_method = rerank_method
        prepared_input.near_neighbor_first = near_neighbor_first
        prepared_input.keywords_extract_prompt = keywords_extract_prompt or prompt.keywords_extract_prompt
        prepared_input.answer_prompt = answer_prompt or prompt.answer_prompt
        prepared_input.custom_related_information = custom_related_information
        prepared_input.vector_dis_threshold = vector_dis_threshold or huge_settings.vector_dis_threshold
        prepared_input.schema = huge_settings.graph_name

        prepared_input.is_graph_rag_recall = is_graph_rag_recall
        prepared_input.is_vector_only = is_vector_only
        prepared_input.data_json = {
            "query": query,
            "vector_search": vector_search,
            "graph_search": graph_search,
            "max_graph_items": max_graph_items or huge_settings.max_graph_items,
            "is_graph_rag_recall": is_graph_rag_recall,
        }

    def build_flow(self, **kwargs):
        pipeline = GPipeline()
        prepared_input = WkFlowInput()
        self.prepare(prepared_input, **kwargs)
        pipeline.createGParam(prepared_input, "wkflow_input")
        pipeline.createGParam(WkFlowState(), "wkflow_state")

        # Create nodes and register them with registerGElement
        only_keyword_extract_node = KeywordExtractNode("only_keyword")
        only_semantic_id_query_node = SemanticIdQueryNode({only_keyword_extract_node}, "only_semantic")
        vector_region: GRegion = GRegion([only_keyword_extract_node, only_semantic_id_query_node])

        only_schema_node = SchemaNode()
        schema_node = VectorOnlyCondition([GRegion(), only_schema_node])
        only_graph_query_node = GraphQueryNode("only_graph")
        merge_rerank_node = MergeRerankNode({only_graph_query_node}, "merge_rerank")
        graph_region: GRegion = GRegion([only_graph_query_node, merge_rerank_node])
        graph_condition_region = VectorOnlyCondition([GRegion(), graph_region])

        answer_synthesize_node = AnswerSynthesizeNode()
        answer_node = GraphRecallCondition([GRegion(), answer_synthesize_node])

        pipeline.registerGElement(vector_region, set(), "vector_fetch")
        pipeline.registerGElement(schema_node, set(), "schema_condition")
        pipeline.registerGElement(
            graph_condition_region,
            {schema_node, vector_region},
            "graph_condition",
        )
        pipeline.registerGElement(answer_node, {graph_condition_region}, "answer_condition")
        log.info("RAGGraphOnlyFlow pipeline built successfully")
        return pipeline

    def post_deal(self, pipeline=None, **kwargs):
        if pipeline is None:
            return {"error": "No pipeline provided"}
        res = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()
        log.info("RAGGraphOnlyFlow post processing success")
        return (
            {
                "raw_answer": res.get("raw_answer", ""),
                "vector_only_answer": res.get("vector_only_answer", ""),
                "graph_only_answer": res.get("graph_only_answer", ""),
                "graph_vector_answer": res.get("graph_vector_answer", ""),
            }
            if not res.get("is_graph_rag_recall", False)
            else res
        )
