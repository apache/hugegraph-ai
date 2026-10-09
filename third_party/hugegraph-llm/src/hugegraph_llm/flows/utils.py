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

from hugegraph_llm.state.ai_state import WkFlowInput
from hugegraph_llm.utils.log import log


def prepare_schema(prepared_input: WkFlowInput, schema: str) -> None:
    schema = schema.strip()
    if schema.startswith("{"):
        try:
            schema = json.loads(schema)
            prepared_input.schema = schema
        except json.JSONDecodeError as exc:
            log.error("Invalid JSON format in schema. Please check it again.")
            raise ValueError("Invalid JSON format in schema.") from exc
    else:
        log.info("Get schema '%s' from graphdb.", schema)
        prepared_input.graph_name = schema
