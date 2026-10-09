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
from hugegraph_llm.operators.llm_op.info_extract import InfoExtract
from hugegraph_llm.operators.llm_op.property_graph_extract import PropertyGraphExtract
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


class ExtractNode(BaseNode):
    property_graph_extract: PropertyGraphExtract
    info_extract: InfoExtract
    context: WkFlowState = None
    wk_input: WkFlowInput = None

    extract_type: str = None

    def node_init(self):
        llm = get_chat_llm(llm_settings)
        if self.wk_input.example_prompt is None:
            return CStatus(-1, "Error occurs when prepare for workflow input")
        example_prompt = self.wk_input.example_prompt
        extract_type = self.wk_input.extract_type
        self.extract_type = extract_type
        if extract_type == "triples":
            self.info_extract = InfoExtract(llm, example_prompt)
        elif extract_type == "property_graph":
            self.property_graph_extract = PropertyGraphExtract(llm, example_prompt)
        else:
            return CStatus(-1, f"Unsupported extract_type: {extract_type}")
        return super().node_init()

    def operator_schedule(self, data_json):
        if self.extract_type == "triples":
            return self.info_extract.run(data_json)
        if self.extract_type == "property_graph":
            return self.property_graph_extract.run(data_json)
        raise ValueError("Unsupport extract type")
