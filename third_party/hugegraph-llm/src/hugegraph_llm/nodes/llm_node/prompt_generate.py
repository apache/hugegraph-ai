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

from hugegraph_llm.config import llm_settings
from hugegraph_llm.models.llms.init_llm import get_chat_llm
from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.llm_op.prompt_generate import PromptGenerate
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


class PromptGenerateNode(BaseNode):
    prompt_generate: PromptGenerate
    context: WkFlowState = None
    wk_input: WkFlowInput = None

    def node_init(self):
        """
        Node initialization method, initialize PromptGenerate operator
        """
        llm = get_chat_llm(llm_settings)
        if not all(
            [
                self.wk_input.source_text,
                self.wk_input.scenario,
                self.wk_input.example_name,
            ]
        ):
            return CStatus(
                -1,
                "Missing required parameters: source_text, scenario, or example_name",
            )

        self.prompt_generate = PromptGenerate(llm)
        context = {
            "source_text": self.wk_input.source_text,
            "scenario": self.wk_input.scenario,
            "example_name": self.wk_input.example_name,
        }
        self.context.assign_from_json(context)
        return super().node_init()

    def operator_schedule(self, data_json):
        """
        Schedule the execution of PromptGenerate operator
        """
        return self.prompt_generate.run(data_json)
