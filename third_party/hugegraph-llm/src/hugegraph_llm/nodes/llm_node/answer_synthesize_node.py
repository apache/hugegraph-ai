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

from typing import Any, Dict

from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.llm_op.answer_synthesize import AnswerSynthesize
from hugegraph_llm.utils.log import log


class AnswerSynthesizeNode(BaseNode):
    """
    Answer synthesis node, responsible for generating the final answer based on retrieval results.
    """

    operator: AnswerSynthesize

    def node_init(self):
        """
        Initialize the answer synthesis operator.
        """
        prompt_template = self.wk_input.answer_prompt
        raw_answer = self.wk_input.raw_answer or False
        vector_only_answer = self.wk_input.vector_only_answer or False
        graph_only_answer = self.wk_input.graph_only_answer or False
        graph_vector_answer = self.wk_input.graph_vector_answer or False

        self.operator = AnswerSynthesize(
            prompt_template=prompt_template,
            raw_answer=raw_answer,
            vector_only_answer=vector_only_answer,
            graph_only_answer=graph_only_answer,
            graph_vector_answer=graph_vector_answer,
        )
        return super().node_init()

    def operator_schedule(self, data_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the answer synthesis operation.
        """
        if self.getGParamWithNoEmpty("wkflow_input").stream:
            # Streaming mode: return a generator for streaming output
            data_json["stream_generator"] = self.operator.run_streaming(data_json)
            return data_json
        # Non-streaming mode: execute answer synthesis
        result = self.operator.run(data_json)

        # Record the types of answers generated
        answer_types = []
        if result.get("raw_answer"):
            answer_types.append("raw")
        if result.get("vector_only_answer"):
            answer_types.append("vector_only")
        if result.get("graph_only_answer"):
            answer_types.append("graph_only")
        if result.get("graph_vector_answer"):
            answer_types.append("graph_vector")

        log.info("Answer synthesis completed for types: %s", ", ".join(answer_types))

        # Print enabled answer types according to self.wk_input configuration
        wk_input_types = []
        if getattr(self.wk_input, "raw_answer", False):
            wk_input_types.append("raw")
        if getattr(self.wk_input, "vector_only_answer", False):
            wk_input_types.append("vector_only")
        if getattr(self.wk_input, "graph_only_answer", False):
            wk_input_types.append("graph_only")
        if getattr(self.wk_input, "graph_vector_answer", False):
            wk_input_types.append("graph_vector")
        log.info(
            "Enabled answer types according to wk_input config: %s",
            ", ".join(wk_input_types),
        )
        return result
