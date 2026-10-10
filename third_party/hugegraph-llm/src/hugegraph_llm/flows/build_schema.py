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

from pycgraph import GPipeline

from hugegraph_llm.flows.common import BaseFlow
from hugegraph_llm.nodes.llm_node.schema_build import SchemaBuildNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState
from hugegraph_llm.utils.log import log


# pylint: disable=arguments-differ,keyword-arg-before-vararg
class BuildSchemaFlow(BaseFlow):
    def __init__(self):
        pass

    def prepare(
        self,
        prepared_input: WkFlowInput,
        texts=None,
        query_examples=None,
        few_shot_schema=None,
        **kwargs,
    ):
        prepared_input.texts = texts
        # Optional fields packed into wk_input for SchemaBuildNode
        # Keep raw values; node will parse if strings
        prepared_input.query_examples = query_examples
        prepared_input.few_shot_schema = few_shot_schema

    def build_flow(self, texts=None, query_examples=None, few_shot_schema=None, **kwargs):
        pipeline = GPipeline()
        prepared_input = WkFlowInput()
        self.prepare(
            prepared_input,
            texts=texts,
            query_examples=query_examples,
            few_shot_schema=few_shot_schema,
        )

        pipeline.createGParam(prepared_input, "wkflow_input")
        pipeline.createGParam(WkFlowState(), "wkflow_state")

        schema_build_node = SchemaBuildNode()
        pipeline.registerGElement(schema_build_node, set(), "schema_build")

        return pipeline

    def post_deal(self, pipeline=None, **kwargs):
        state_json = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()
        if "schema" not in state_json:
            return ""
        res = state_json["schema"]
        try:
            formatted_schema = json.dumps(res, ensure_ascii=False, indent=2)
            return formatted_schema
        except (TypeError, ValueError) as e:
            log.error("Failed to format schema: %s", e)
            return str(res)
