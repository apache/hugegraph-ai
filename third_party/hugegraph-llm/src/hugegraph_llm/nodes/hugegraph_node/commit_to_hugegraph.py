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

from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph import Commit2Graph
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


class Commit2GraphNode(BaseNode):
    commit_to_graph_op: Commit2Graph
    context: WkFlowState = None
    wk_input: WkFlowInput = None

    def node_init(self):
        data_json = self.wk_input.data_json if self.wk_input.data_json else None
        if data_json:
            self.context.assign_from_json(data_json)
        self.commit_to_graph_op = Commit2Graph()
        return super().node_init()

    def operator_schedule(self, data_json):
        return self.commit_to_graph_op.run(data_json)
