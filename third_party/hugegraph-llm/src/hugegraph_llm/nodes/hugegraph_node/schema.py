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

from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.common_op.check_schema import CheckSchema
from hugegraph_llm.operators.hugegraph_op.schema_manager import SchemaManager
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState
from hugegraph_llm.utils.log import log


class SchemaNode(BaseNode):
    schema_manager: SchemaManager
    check_schema: CheckSchema
    context: WkFlowState = None
    wk_input: WkFlowInput = None

    schema = None

    def _import_schema(
        self,
        from_hugegraph=None,
        from_extraction=None,
        from_user_defined=None,
    ):
        if from_hugegraph:
            return SchemaManager(from_hugegraph, connection=self.wk_input.graph_client_config)
        if from_user_defined:
            return CheckSchema(from_user_defined)
        if from_extraction:
            raise NotImplementedError("Not implemented yet")
        raise ValueError("No input data / invalid schema type")

    def node_init(self):
        if self.wk_input.schema is None:
            return CStatus(-1, "Schema message is required in SchemaNode")
        self.schema = self.wk_input.schema.strip()
        if self.schema.startswith("{"):
            try:
                schema = json.loads(self.schema)
                self.check_schema = self._import_schema(from_user_defined=schema)
            except json.JSONDecodeError as exc:
                log.error("Invalid JSON format in schema. Please check it again.")
                return CStatus(-1, f"Invalid JSON format in schema. {exc}")
        else:
            log.info("Get schema '%s' from graphdb.", self.schema)
            self.schema_manager = self._import_schema(from_hugegraph=self.schema)
        return super().node_init()

    def operator_schedule(self, data_json):
        log.debug("SchemaNode input state: %s", data_json)
        if self.schema.startswith("{"):
            return self.check_schema.run(data_json)
        log.info("Get schema '%s' from graphdb.", self.schema)
        return self.schema_manager.run(data_json)
