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


from typing import Optional

from pycgraph import GPipeline

from hugegraph_llm.config import huge_settings, prompt
from hugegraph_llm.flows.common import BaseFlow
from hugegraph_llm.nodes.llm_node.answer_synthesize_node import AnswerSynthesizeNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState
from hugegraph_llm.utils.log import log


# pylint: disable=arguments-differ,keyword-arg-before-vararg
class RAGRawFlow(BaseFlow):
    """
    Workflow for basic LLM answering only (raw_answer)
    """

    def prepare(
        self,
        prepared_input: WkFlowInput,
        query: str,
        vector_search: bool = False,
        graph_search: bool = False,
        raw_answer: bool = True,
        vector_only_answer: bool = False,
        graph_only_answer: bool = False,
        graph_vector_answer: bool = False,
        custom_related_information: str = "",
        answer_prompt: Optional[str] = None,
        max_graph_items: Optional[int] = None,
        **kwargs,
    ):
        prepared_input.query = query
        prepared_input.raw_answer = raw_answer
        prepared_input.vector_only_answer = vector_only_answer
        prepared_input.graph_only_answer = graph_only_answer
        prepared_input.graph_vector_answer = graph_vector_answer
        prepared_input.custom_related_information = custom_related_information
        prepared_input.answer_prompt = answer_prompt or prompt.answer_prompt
        prepared_input.schema = huge_settings.graph_name

        prepared_input.data_json = {
            "query": query,
            "vector_search": vector_search,
            "graph_search": graph_search,
            "max_graph_items": max_graph_items or huge_settings.max_graph_items,
        }

    def build_flow(self, **kwargs):
        pipeline = GPipeline()
        prepared_input = WkFlowInput()
        self.prepare(prepared_input, **kwargs)
        pipeline.createGParam(prepared_input, "wkflow_input")
        pipeline.createGParam(WkFlowState(), "wkflow_state")

        # Create nodes and register with registerGElement (no GRegion required)
        answer_synthesize_node = AnswerSynthesizeNode()
        pipeline.registerGElement(answer_synthesize_node, set(), "raw")
        log.info("RAGRawFlow pipeline built successfully")
        return pipeline

    def post_deal(self, pipeline=None, **kwargs):
        if pipeline is None:
            return {"error": "No pipeline provided"}
        res = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()
        log.info("RAGRawFlow post processing success")
        return {
            "raw_answer": res.get("raw_answer", ""),
            "vector_only_answer": res.get("vector_only_answer", ""),
            "graph_only_answer": res.get("graph_only_answer", ""),
            "graph_vector_answer": res.get("graph_vector_answer", ""),
        }
