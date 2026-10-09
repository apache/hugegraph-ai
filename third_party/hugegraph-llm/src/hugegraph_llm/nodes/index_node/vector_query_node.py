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

from hugegraph_llm.config import index_settings
from hugegraph_llm.models.embeddings.init_embedding import Embeddings
from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.index_op.vector_index_query import VectorIndexQuery
from hugegraph_llm.utils.log import log


class VectorQueryNode(BaseNode):
    """
    Vector query node, responsible for retrieving relevant documents from the vector index
    """

    operator: VectorIndexQuery

    def node_init(self):
        """
        Initialize the vector query operator
        """
        try:
            # Lazy import to avoid circular dependency
            # pylint: disable=import-outside-toplevel
            from hugegraph_llm.utils.vector_index_utils import get_vector_index_class

            # Read user configuration parameters from wk_input.
            vector_index = get_vector_index_class(index_settings.cur_vector_index)
            embedding = Embeddings().get_embedding()
            max_items = self.wk_input.max_items if self.wk_input.max_items is not None else 3

            self.operator = VectorIndexQuery(vector_index=vector_index, embedding=embedding, topk=max_items)
            return super().node_init()
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error("Failed to initialize VectorQueryNode: %s", e)
            from pycgraph import CStatus

            return CStatus(-1, f"VectorQueryNode initialization failed: {e}")

    def operator_schedule(self, data_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the vector query operation
        """
        try:
            # Get the query text from input
            query = data_json.get("query", "")
            if not query:
                log.warning("No query text provided for vector query")
                return data_json

            # Perform the vector query
            result = self.operator.run({"query": query})

            # Update the state
            data_json.update(result)
            log.info(
                "Vector query completed, found %d results",
                len(result.get("vector_result", [])),
            )

            return data_json

        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error("Vector query failed: %s", e)
            return data_json
