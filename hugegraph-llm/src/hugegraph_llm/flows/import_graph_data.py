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

import json

import gradio as gr
from pycgraph import GPipeline

from hugegraph_llm.flows.common import BaseFlow
from hugegraph_llm.nodes.hugegraph_node.commit_to_hugegraph import Commit2GraphNode
from hugegraph_llm.nodes.hugegraph_node.schema import SchemaNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState
from hugegraph_llm.utils.log import log


# pylint: disable=arguments-differ,keyword-arg-before-vararg
class ImportGraphDataFlow(BaseFlow):
    def __init__(self):
        pass

    def prepare(self, prepared_input: WkFlowInput, data, schema, graph_config=None, **kwargs):
        try:
            data_json = json.loads(data.strip()) if isinstance(data, str) else data
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for 'data': {e.msg}") from e
        log.debug(
            "Import graph data (truncated): %s",
            (
                (data[:512] + "...")
                if isinstance(data, str) and len(data) > 512
                else (data if isinstance(data, str) else "<obj>")
            ),
        )
        prepared_input.data_json = data_json
        prepared_input.schema = schema
        prepared_input.graph_config = graph_config

    def build_flow(self, data, schema, graph_config=None, **kwargs):
        pipeline = GPipeline()
        prepared_input = WkFlowInput()
        # prepare input data
        self.prepare(prepared_input, data, schema, graph_config=graph_config)

        pipeline.createGParam(prepared_input, "wkflow_input")
        pipeline.createGParam(WkFlowState(), "wkflow_state")

        schema_node = SchemaNode()
        commit_node = Commit2GraphNode()
        pipeline.registerGElement(schema_node, set(), "schema_node")
        pipeline.registerGElement(commit_node, {schema_node}, "commit_node")

        return pipeline

    def post_deal(self, pipeline=None, **kwargs):
        res = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()
        gr.Info("Import graph data successfully!")
        return json.dumps(res, ensure_ascii=False, indent=2)
