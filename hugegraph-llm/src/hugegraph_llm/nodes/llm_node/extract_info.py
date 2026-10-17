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

from hugegraph_llm.config import llm_settings, snapshot_llm_settings
from hugegraph_llm.extraction_runtime.property_graph import PropertyGraphBundle
from hugegraph_llm.extraction_runtime.v1 import ChunkInput, run_chunks_v1
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
        if self.wk_input.example_prompt is None:
            return CStatus(-1, "Error occurs when prepare for workflow input")
        example_prompt = self.wk_input.example_prompt
        extract_type = self.wk_input.extract_type
        self.extract_type = extract_type
        if self.wk_input.review_options is not None:
            if extract_type != "property_graph":
                return CStatus(-1, "Review is only supported for property_graph extraction")
            return super().node_init()
        llm = get_chat_llm(llm_settings)
        if extract_type == "triples":
            self.info_extract = InfoExtract(llm, example_prompt)
        elif extract_type == "property_graph":
            self.property_graph_extract = PropertyGraphExtract(llm, example_prompt)
        else:
            return CStatus(-1, f"Unsupported extract_type: {extract_type}")
        return super().node_init()

    def operator_schedule(self, data_json):
        if self.wk_input.review_options is not None:
            return self._extract_with_review(data_json)
        if self.extract_type == "triples":
            return self.info_extract.run(data_json)
        if self.extract_type == "property_graph":
            return self.property_graph_extract.run(data_json)
        raise ValueError("Unsupport extract type")

    def _extract_with_review(self, data_json):
        chunks = [ChunkInput(index=index, text=text) for index, text in enumerate(data_json.get("chunks", []))]
        if not chunks:
            raise ValueError("No text chunks available for graph extraction")
        schema = data_json["schema"]
        example_prompt = self.wk_input.example_prompt

        settings = snapshot_llm_settings()

        def prepare(_chunk):
            # Clients and bundles belong to one chunk; workers never mutate workflow state.
            return PropertyGraphBundle(
                llm=get_chat_llm(settings, limit_output=False, raise_on_truncation=True),
                schema=schema,
                example_prompt=example_prompt,
            )

        results = run_chunks_v1(chunks=chunks, prepare=prepare, options=self.wk_input.review_options)
        final_results = [result for result in results if result.status == "final"]
        if len(final_results) == len(results):
            extraction_status = "succeeded"
        elif final_results:
            extraction_status = "partial"
        else:
            extraction_status = "failed"
        return {
            "vertices": [vertex for result in final_results for vertex in result.graph["vertices"]],
            "edges": [edge for result in final_results for edge in result.graph["edges"]],
            "chunk_results": [result.as_dict() for result in results],
            "extraction_status": extraction_status,
            "call_count": sum(result.llm_calls for result in results),
        }
