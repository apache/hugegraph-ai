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

from pycgraph import CStatus

from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.document_op.chunk_split import ChunkSplit
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


class ChunkSplitNode(BaseNode):
    chunk_split_op: ChunkSplit
    context: WkFlowState = None
    wk_input: WkFlowInput = None

    def node_init(self):
        if self.wk_input.texts is None or self.wk_input.language is None or self.wk_input.split_type is None:
            return CStatus(-1, "Error occurs when prepare for workflow input")
        texts = self.wk_input.texts
        language = self.wk_input.language
        split_type = self.wk_input.split_type
        if isinstance(texts, str):
            texts = [texts]
        self.chunk_split_op = ChunkSplit(texts, split_type, language)
        return super().node_init()

    def operator_schedule(self, data_json):
        return self.chunk_split_op.run(data_json)
