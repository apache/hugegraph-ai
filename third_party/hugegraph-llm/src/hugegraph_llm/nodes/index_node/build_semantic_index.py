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

from hugegraph_llm.config import index_settings
from hugegraph_llm.models.embeddings.init_embedding import Embeddings
from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.index_op.build_semantic_index import BuildSemanticIndex
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


class BuildSemanticIndexNode(BaseNode):
    build_semantic_index_op: BuildSemanticIndex
    context: WkFlowState = None
    wk_input: WkFlowInput = None

    def node_init(self):
        # Lazy import to avoid circular dependency
        # pylint: disable=import-outside-toplevel
        from hugegraph_llm.utils.vector_index_utils import get_vector_index_class

        vector_index = get_vector_index_class(index_settings.cur_vector_index)
        embedding = Embeddings().get_embedding()
        self.build_semantic_index_op = BuildSemanticIndex(embedding, vector_index)
        return super().node_init()

    def operator_schedule(self, data_json):
        return self.build_semantic_index_op.run(data_json)
