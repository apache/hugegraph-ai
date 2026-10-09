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

from pycgraph import CStatus

from hugegraph_llm.config import huge_settings, index_settings
from hugegraph_llm.models.embeddings.init_embedding import Embeddings
from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.index_op.semantic_id_query import SemanticIdQuery
from hugegraph_llm.utils.log import log


class SemanticIdQueryNode(BaseNode):
    """
    Semantic ID query node, responsible for semantic matching based on keywords.
    """

    semantic_id_query: SemanticIdQuery

    def node_init(self):
        """
        Initialize the semantic ID query operator.
        """
        try:
            # Lazy import to avoid circular dependency
            # pylint: disable=import-outside-toplevel
            from hugegraph_llm.utils.vector_index_utils import get_vector_index_class

            graph_name = huge_settings.graph_name
            if not graph_name:
                return CStatus(-1, "graph_name is required in wk_input")

            vector_index = get_vector_index_class(index_settings.cur_vector_index)
            embedding = Embeddings().get_embedding()
            by = self.wk_input.semantic_by if self.wk_input.semantic_by is not None else "keywords"
            topk_per_keyword = (
                self.wk_input.topk_per_keyword
                if self.wk_input.topk_per_keyword is not None
                else huge_settings.topk_per_keyword
            )
            topk_per_query = self.wk_input.topk_per_query if self.wk_input.topk_per_query is not None else 10
            vector_dis_threshold = (
                self.wk_input.vector_dis_threshold
                if self.wk_input.vector_dis_threshold is not None
                else huge_settings.vector_dis_threshold
            )

            # Initialize the semantic ID query operator
            self.semantic_id_query = SemanticIdQuery(
                embedding=embedding,
                vector_index=vector_index,
                by=by,
                topk_per_keyword=topk_per_keyword,
                topk_per_query=topk_per_query,
                vector_dis_threshold=vector_dis_threshold,
            )

            return super().node_init()
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error("Failed to initialize SemanticIdQueryNode: %s", e)

            return CStatus(-1, f"SemanticIdQueryNode initialization failed: {e}")

    def operator_schedule(self, data_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the semantic ID query operation.
        """
        # Get the query text and keywords from input
        query = data_json.get("query", "")
        keywords = data_json.get("keywords", [])

        if not query and not keywords:
            log.warning("No query text or keywords provided for semantic query")
            return data_json

        # Perform the semantic query
        semantic_result = self.semantic_id_query.run(data_json)

        match_vids = semantic_result.get("match_vids", [])
        log.info("Semantic query completed, found %d matching vertex IDs", len(match_vids))

        return semantic_result
