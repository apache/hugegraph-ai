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

from typing import Any, Dict

from hugegraph_llm.config import huge_settings, llm_settings
from hugegraph_llm.models.embeddings.init_embedding import get_embedding
from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.common_op.merge_dedup_rerank import MergeDedupRerank
from hugegraph_llm.utils.log import log


class MergeRerankNode(BaseNode):
    """
    Merge and rerank node, responsible for merging vector and graph query results, deduplication and reranking.
    """

    operator: MergeDedupRerank

    def node_init(self):
        """
        Initialize the merge and rerank operator.
        """
        try:
            # Read user configuration parameters from wk_input
            embedding = get_embedding(llm_settings)
            graph_ratio = self.wk_input.graph_ratio or 0.5
            rerank_method = self.wk_input.rerank_method or "bleu"
            near_neighbor_first = self.wk_input.near_neighbor_first or False
            custom_related_information = self.wk_input.custom_related_information or ""
            topk_return_results = self.wk_input.topk_return_results or huge_settings.topk_return_results

            self.operator = MergeDedupRerank(
                embedding=embedding,
                graph_ratio=graph_ratio,
                method=rerank_method,
                near_neighbor_first=near_neighbor_first,
                custom_related_information=custom_related_information,
                topk_return_results=topk_return_results,
            )
            return super().node_init()
        except ValueError as e:
            log.error("Failed to initialize MergeRerankNode: %s", e)
            from pycgraph import CStatus

            return CStatus(-1, f"MergeRerankNode initialization failed: {e}")

    def operator_schedule(self, data_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the merge and rerank operation.
        """
        try:
            # Perform merge, deduplication, and rerank
            result = self.operator.run(data_json)

            # Log result statistics
            vector_count = len(result.get("vector_result", []))
            graph_count = len(result.get("graph_result", []))
            merged_count = len(result.get("merged_result", []))

            log.info(
                "Merge and rerank completed: %d vector results, %d graph results, %d merged results",
                vector_count,
                graph_count,
                merged_count,
            )

            return result

        except ValueError as e:
            log.error("Merge and rerank failed: %s", e)
            return data_json
