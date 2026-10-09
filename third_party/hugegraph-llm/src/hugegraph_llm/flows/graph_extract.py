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

from hugegraph_llm.config import huge_settings
from hugegraph_llm.flows.common import BaseFlow
from hugegraph_llm.nodes.document_node.chunk_split import ChunkSplitNode
from hugegraph_llm.nodes.hugegraph_node.schema import SchemaNode
from hugegraph_llm.nodes.llm_node.extract_info import ExtractNode
from hugegraph_llm.operators.document_op.chunk_split import (
    SPLIT_TYPE_DOCUMENT,
    VALID_SPLIT_TYPES,
)
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState
from hugegraph_llm.utils.log import log


# pylint: disable=arguments-differ,keyword-arg-before-vararg
class GraphExtractFlow(BaseFlow):
    def __init__(self):
        pass

    def prepare(
        self,
        prepared_input: WkFlowInput,
        schema,
        texts,
        example_prompt,
        extract_type,
        split_type=SPLIT_TYPE_DOCUMENT,
        language="zh",
        **kwargs,
    ):
        # prepare input data
        prepared_input.texts = texts
        prepared_input.language = language
        if split_type not in VALID_SPLIT_TYPES:
            raise ValueError("split_type must be document, paragraph, or sentence")

        prepared_input.split_type = split_type
        prepared_input.example_prompt = example_prompt
        prepared_input.schema = schema
        prepared_input.extract_type = extract_type
        client_config = kwargs.get("client_config")
        if client_config:
            # URL stays server-controlled; only identity/graphspace are request-scoped.
            prepared_input.graph_client_config = {
                "url": huge_settings.graph_url,
                "user": client_config.user,
                "pwd": client_config.pwd,
                "graphspace": client_config.gs,
            }
        else:
            prepared_input.graph_client_config = None

    def build_flow(
        self,
        schema,
        texts,
        example_prompt,
        extract_type,
        split_type=SPLIT_TYPE_DOCUMENT,
        language="zh",
        **kwargs,
    ):
        pipeline = GPipeline()
        prepared_input = WkFlowInput()
        # prepare input data
        self.prepare(
            prepared_input,
            schema,
            texts,
            example_prompt,
            extract_type,
            split_type,
            language,
            **kwargs,
        )

        pipeline.createGParam(prepared_input, "wkflow_input")
        pipeline.createGParam(WkFlowState(), "wkflow_state")
        schema_node = SchemaNode()

        chunk_split_node = ChunkSplitNode()
        graph_extract_node = ExtractNode()
        pipeline.registerGElement(schema_node, set(), "schema_node")
        pipeline.registerGElement(chunk_split_node, set(), "chunk_split")
        pipeline.registerGElement(graph_extract_node, {schema_node, chunk_split_node}, "graph_extract")

        return pipeline

    def post_deal(self, pipeline=None, **kwargs):
        res = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()
        vertices = res.get("vertices", [])
        edges = res.get("edges", [])
        chunk_count = len(res.get("chunks", []))
        log.info("Graph extraction chunk_count: %s", chunk_count)
        if not vertices and not edges:
            log.info("Please check the schema.(The schema may not match the Doc)")
            return json.dumps(
                {
                    "vertices": vertices,
                    "edges": edges,
                    "warning": "The schema may not match the Doc",
                },
                ensure_ascii=False,
                indent=2,
            )
        return json.dumps(
            {"vertices": vertices, "edges": edges},
            ensure_ascii=False,
            indent=2,
        )
