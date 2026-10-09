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

from pycgraph import CStatus

from hugegraph_llm.config import llm_settings
from hugegraph_llm.models.llms.init_llm import get_chat_llm
from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.llm_op.schema_build import SchemaBuilder
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState
from hugegraph_llm.utils.log import log


class SchemaBuildNode(BaseNode):
    schema_builder: SchemaBuilder
    context: WkFlowState = None
    wk_input: WkFlowInput = None

    def node_init(self):
        llm = get_chat_llm(llm_settings)
        self.schema_builder = SchemaBuilder(llm)

        # texts -> raw_texts
        raw_texts = []
        if self.wk_input.texts:
            if isinstance(self.wk_input.texts, list):
                raw_texts = [t for t in self.wk_input.texts if isinstance(t, str)]
            elif isinstance(self.wk_input.texts, str):
                raw_texts = [self.wk_input.texts]

        # query_examples: already parsed list[dict] or raw JSON string
        query_examples = []
        qe_src = self.wk_input.query_examples if self.wk_input.query_examples else None
        if qe_src:
            try:
                parsed_examples = json.loads(qe_src)
                # Validate and retain the description and gremlin fields
                query_examples = [
                    {
                        "description": ex.get("description", ""),
                        "gremlin": ex.get("gremlin", ""),
                    }
                    for ex in parsed_examples
                    if isinstance(ex, dict) and "description" in ex and "gremlin" in ex
                ]
            except json.JSONDecodeError as e:
                return CStatus(-1, f"Query Examples is not in a valid JSON format: {e}")

        # few_shot_schema: already parsed dict or raw JSON string
        few_shot_schema = {}
        fss_src = self.wk_input.few_shot_schema if self.wk_input.few_shot_schema else None
        if fss_src:
            try:
                few_shot_schema = json.loads(fss_src)
            except json.JSONDecodeError as e:
                return CStatus(-1, f"Few Shot Schema is not in a valid JSON format: {e}")

        _context_payload = {
            "raw_texts": raw_texts,
            "query_examples": query_examples,
            "few_shot_schema": few_shot_schema,
        }
        self.context.assign_from_json(_context_payload)

        return super().node_init()

    def operator_schedule(self, data_json):
        try:
            schema_result = self.schema_builder.run(data_json)
            return {"schema": schema_result}
        except (ValueError, RuntimeError) as e:
            log.error("Failed to generate schema: %s", e)
            raise ValueError(f"Failed to generate schema: {e}") from e
