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

from pycgraph import GPipeline

from hugegraph_llm.flows.common import BaseFlow
from hugegraph_llm.nodes.llm_node.prompt_generate import PromptGenerateNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


# pylint: disable=arguments-differ,keyword-arg-before-vararg
class PromptGenerateFlow(BaseFlow):
    def __init__(self):
        pass

    def prepare(self, prepared_input: WkFlowInput, source_text, scenario, example_name, **kwargs):
        """
        Prepare input data for PromptGenerate workflow
        """
        prepared_input.source_text = source_text
        prepared_input.scenario = scenario
        prepared_input.example_name = example_name

    def build_flow(self, source_text, scenario, example_name, **kwargs):
        """
        Build the PromptGenerate workflow
        """
        pipeline = GPipeline()
        # Prepare workflow input
        prepared_input = WkFlowInput()
        self.prepare(prepared_input, source_text, scenario, example_name)

        pipeline.createGParam(prepared_input, "wkflow_input")
        pipeline.createGParam(WkFlowState(), "wkflow_state")

        # Create PromptGenerate node
        prompt_generate_node = PromptGenerateNode()
        pipeline.registerGElement(prompt_generate_node, set(), "prompt_generate")

        return pipeline

    def post_deal(self, pipeline=None, **kwargs):
        """
        Process the execution result of PromptGenerate workflow
        """
        res = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()
        return res.get("generated_extract_prompt", "Generation failed. Please check the logs.")
