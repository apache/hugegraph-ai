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


from typing import Any, Dict, List, Literal, Optional, Tuple

import jieba
import requests
from nltk.translate.bleu_score import sentence_bleu

from hugegraph_llm.config import huge_settings, llm_settings
from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.models.rerankers.init_reranker import Rerankers
from hugegraph_llm.utils.log import log


def get_bleu_score(query: str, content: str) -> float:
    query_tokens = jieba.lcut(query)
    content_tokens = jieba.lcut(content)
    return sentence_bleu([query_tokens], content_tokens)


def _bleu_rerank(query: str, results: List[str]) -> List[str]:
    result_score_list = [[res, get_bleu_score(query, res)] for res in results]
    result_score_list.sort(key=lambda x: x[1], reverse=True)
    return [res[0] for res in result_score_list]


class MergeDedupRerank:
    def __init__(
        self,
        embedding: BaseEmbedding,
        topk_return_results: int = huge_settings.topk_return_results,
        graph_ratio: float = 0.5,
        method: Literal["bleu", "reranker"] = "bleu",
        near_neighbor_first: bool = False,
        custom_related_information: Optional[str] = None,
        priority: bool = False,  # TODO: implement priority
    ):
        assert method in ["bleu", "reranker"], f"Unimplemented rerank method '{method}'."
        if llm_settings.reranker_type is None:
            assert method == "bleu", "Please set the online reranker first"
        self.embedding = embedding
        self.graph_ratio = graph_ratio
        self.topk_return_results = topk_return_results
        self.method = method
        self.near_neighbor_first = near_neighbor_first
        self.custom_related_information = custom_related_information
        if priority:
            raise ValueError("Unimplemented rerank strategy: priority.")
        self.switch_to_bleu = False

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        query = context.get("query")
        if self.custom_related_information:
            query = query + self.custom_related_information
        context["graph_ratio"] = self.graph_ratio
        vector_search = context.get("vector_search", False)
        graph_search = context.get("graph_search", False)
        if graph_search and vector_search:
            graph_length = int(self.topk_return_results * self.graph_ratio)
            vector_length = self.topk_return_results - graph_length
        else:
            graph_length = self.topk_return_results
            vector_length = self.topk_return_results

        vector_result = context.get("vector_result", [])
        vector_length = min(len(vector_result), vector_length)
        vector_result = self._dedup_and_rerank(query, vector_result, vector_length)

        graph_result = context.get("graph_result", [])
        graph_length = min(len(graph_result), graph_length)
        if self.near_neighbor_first:
            graph_result = self._rerank_with_vertex_degree(
                query,
                graph_result,
                graph_length,
                context.get("vertex_degree_list"),
                context.get("knowledge_with_degree"),
            )
            if self.switch_to_bleu:
                context["switch_to_bleu"] = True
        else:
            graph_result = self._dedup_and_rerank(query, graph_result, graph_length)

        context["vector_result"] = vector_result
        context["graph_result"] = graph_result

        return context

    def _dedup_and_rerank(self, query: str, results: List[str], topn: int) -> List[str]:
        results = list(set(results))
        if self.method == "bleu":
            return _bleu_rerank(query, results)[:topn]
        if self.method == "reranker":
            reranker = Rerankers().get_reranker()
            return reranker.get_rerank_lists(query, results, topn)
        raise ValueError(f"Unimplemented rerank method '{self.method}'.")

    def _rerank_with_vertex_degree(
        self,
        query: str,
        results: List[str],
        topn: int,
        vertex_degree_list: Optional[List[List[str]]],
        knowledge_with_degree: Dict[str, List[str]],
    ) -> List[str]:
        if vertex_degree_list is None or len(vertex_degree_list) == 0:
            return self._dedup_and_rerank(query, results, topn)

        if self.method == "reranker":
            reranker = Rerankers().get_reranker()
            try:
                vertex_rerank_res = [
                    reranker.get_rerank_lists(query, vertex_degree) + [""] for vertex_degree in vertex_degree_list
                ]
            except requests.exceptions.RequestException as e:
                log.warning("Online reranker fails, automatically switches to local bleu method: %s", e)
                self.method = "bleu"
                self.switch_to_bleu = True

        if self.method == "bleu":
            vertex_rerank_res = [_bleu_rerank(query, vertex_degree) + [""] for vertex_degree in vertex_degree_list]

        depth = len(vertex_degree_list)
        for result in results:
            if result not in knowledge_with_degree:
                knowledge_with_degree[result] = [result] + [""] * (depth - 1)
            if len(knowledge_with_degree[result]) < depth:
                knowledge_with_degree[result] += [""] * (depth - len(knowledge_with_degree[result]))

        def sort_key(res: str) -> Tuple[int, ...]:
            return tuple(vertex_rerank_res[i].index(knowledge_with_degree[res][i]) for i in range(depth))

        sorted_results = sorted(results, key=sort_key)
        return sorted_results[:topn]
