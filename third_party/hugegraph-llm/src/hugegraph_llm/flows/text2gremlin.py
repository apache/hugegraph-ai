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

from typing import Any, Dict, List, Optional

from pycgraph import GPipeline

from hugegraph_llm.flows.common import BaseFlow
from hugegraph_llm.nodes.hugegraph_node.gremlin_execute import GremlinExecuteNode
from hugegraph_llm.nodes.hugegraph_node.schema import SchemaNode
from hugegraph_llm.nodes.index_node.gremlin_example_index_query import (
    GremlinExampleIndexQueryNode,
)
from hugegraph_llm.nodes.llm_node.text2gremlin import Text2GremlinNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


# pylint: disable=arguments-differ,keyword-arg-before-vararg
class Text2GremlinFlow(BaseFlow):
    def __init__(self):
        pass

    def prepare(
        self,
        prepared_input: WkFlowInput,
        query: str,
        example_num: int,
        schema_input: str,
        gremlin_prompt_input: Optional[str],
        requested_outputs: Optional[List[str]],
        graph_client_config: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        # sanitize example_num to [0,10], fallback to 2 if invalid
        if not isinstance(example_num, int):
            example_num = 2
        example_num = max(0, min(10, example_num))

        # filter requested_outputs to allowed set and cap to 5
        allowed = {
            "match_result",
            "template_gremlin",
            "raw_gremlin",
            "template_execution_result",
            "raw_execution_result",
        }
        req = requested_outputs or ["template_gremlin"]
        req = [x for x in req if x in allowed]
        if not req:
            req = ["template_gremlin"]
        if len(req) > 5:
            req = req[:5]

        prepared_input.query = query
        prepared_input.example_num = example_num
        prepared_input.schema = schema_input
        prepared_input.gremlin_prompt = gremlin_prompt_input
        prepared_input.requested_outputs = req
        prepared_input.graph_client_config = graph_client_config

    def build_flow(
        self,
        query: str,
        example_num: int,
        schema_input: str,
        gremlin_prompt_input: Optional[str] = None,
        requested_outputs: Optional[List[str]] = None,
        graph_client_config: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        pipeline = GPipeline()

        prepared_input = WkFlowInput()
        self.prepare(
            prepared_input,
            query=query,
            example_num=example_num,
            schema_input=schema_input,
            gremlin_prompt_input=gremlin_prompt_input,
            requested_outputs=requested_outputs,
            graph_client_config=graph_client_config,
        )

        pipeline.createGParam(prepared_input, "wkflow_input")
        pipeline.createGParam(WkFlowState(), "wkflow_state")

        schema_node = SchemaNode()
        ieq_node = GremlinExampleIndexQueryNode()
        tgn_node = Text2GremlinNode()
        exe_node = GremlinExecuteNode()

        pipeline.registerGElement(schema_node, set(), "schema_node")
        pipeline.registerGElement(ieq_node, set(), "gremlin_example_index_query")
        pipeline.registerGElement(tgn_node, {schema_node, ieq_node}, "text2gremlin")
        pipeline.registerGElement(exe_node, {tgn_node}, "gremlin_execute")

        return pipeline

    def post_deal(self, pipeline=None, **kwargs) -> Dict[str, Any]:
        state = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()
        # Always return the five standard keys so filtering errors do not hide fields.
        return {
            "match_result": state.get("match_result", []),
            "template_gremlin": state.get("result", ""),
            "raw_gremlin": state.get("raw_result", ""),
            "template_execution_result": state.get("template_exec_res", ""),
            "raw_execution_result": state.get("raw_exec_res", ""),
        }
