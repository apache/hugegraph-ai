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
from hugegraph_llm.nodes.hugegraph_node.fetch_graph_data import FetchGraphDataNode
from hugegraph_llm.nodes.index_node.build_semantic_index import BuildSemanticIndexNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


# pylint: disable=arguments-differ,keyword-arg-before-vararg
class UpdateVidEmbeddingsFlow(BaseFlow):
    def prepare(self, prepared_input: WkFlowInput, **kwargs):
        pass

    def build_flow(self, **kwargs):
        pipeline = GPipeline()
        prepared_input = WkFlowInput()
        # prepare input data
        self.prepare(prepared_input)

        pipeline.createGParam(prepared_input, "wkflow_input")
        pipeline.createGParam(WkFlowState(), "wkflow_state")

        fetch_node = FetchGraphDataNode()
        build_node = BuildSemanticIndexNode()
        pipeline.registerGElement(fetch_node, set(), "fetch_node")
        pipeline.registerGElement(build_node, {fetch_node}, "build_node")

        return pipeline

    def post_deal(self, pipeline, **kwargs):
        res = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()
        removed_num = res.get("removed_vid_vector_num", 0)
        added_num = res.get("added_vid_vector_num", 0)
        return f"Removed {removed_num} vectors, added {added_num} vectors."
