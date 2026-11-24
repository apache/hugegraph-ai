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

from hugegraph_llm.config import huge_settings, index_settings
from hugegraph_llm.flows.common import BaseFlow
from hugegraph_llm.models.embeddings.init_embedding import Embeddings
from hugegraph_llm.nodes.hugegraph_node.fetch_graph_data import FetchGraphDataNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


# pylint: disable=arguments-differ,keyword-arg-before-vararg
class GetGraphIndexInfoFlow(BaseFlow):
    def __init__(self):
        pass

    def prepare(self, prepared_input: WkFlowInput, **kwargs):
        return

    def build_flow(self, **kwargs):
        pipeline = GPipeline()
        prepared_input = WkFlowInput()
        self.prepare(prepared_input, **kwargs)
        pipeline.createGParam(prepared_input, "wkflow_input")
        pipeline.createGParam(WkFlowState(), "wkflow_state")
        fetch_node = FetchGraphDataNode()
        pipeline.registerGElement(fetch_node, set(), "fetch_node")
        return pipeline

    def post_deal(self, pipeline=None):
        # Lazy import to avoid circular dependency
        from hugegraph_llm.utils.vector_index_utils import (
            get_vector_index_class,  # pylint: disable=import-outside-toplevel
        )

        graph_summary_info = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()

        try:
            from hugegraph_llm.operators.index_op.build_semantic_index import (  # pylint: disable=import-outside-toplevel
                read_vid_index_meta,
                vid_index_name_parts,
            )

            vector_index_class = get_vector_index_class(index_settings.cur_vector_index)
            embedding = Embeddings().get_embedding()
            index_parts = vid_index_name_parts(huge_settings.graph_name, huge_settings.graph_space)
            if vector_index_class.exist(*index_parts):
                vector_index = vector_index_class.from_name(embedding.get_embedding_dim(), *index_parts, read_only=True)
                graph_summary_info["vid_index"] = vector_index.get_vector_index_info()
            graph_summary_info["vid_index_meta"] = read_vid_index_meta(
                huge_settings.graph_name, huge_settings.graph_space
            )
        except Exception:  # pylint: disable=broad-except
            # If vector index doesn't exist or fails to load, just return graph summary
            pass

        return json.dumps(graph_summary_info, ensure_ascii=False, indent=2)
