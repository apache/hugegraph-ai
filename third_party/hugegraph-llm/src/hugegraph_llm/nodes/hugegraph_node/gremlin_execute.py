# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

from typing import Any, Dict

from pycgraph import CStatus

from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.utils.hugegraph_utils import run_gremlin_query


def _ensure_limit(query: str, default_limit: int = 100) -> str:
    if not query:
        return query
    q_lower = query.lower()
    if "limit(" in q_lower:
        return query
    if any(token in q_lower for token in ["g.v(", ".v(", "g.e(", ".e("]):
        return f"{query}.limit({default_limit})"
    return query


class GremlinExecuteNode(BaseNode):
    def node_init(self):
        return CStatus()

    def operator_schedule(self, data_json: Dict[str, Any]):
        # Read requested outputs from wk_input
        requested = getattr(self.wk_input, "requested_outputs", None) or []
        need_template = "template_execution_result" in requested
        need_raw = "raw_execution_result" in requested

        tmpl_q = data_json.get("result", "")
        raw_q = data_json.get("raw_result", "")
        graph_connection = getattr(self.wk_input, "graph_client_config", None)

        if need_template:
            try:
                safe_q = _ensure_limit(tmpl_q)
                data_json["template_exec_res"] = run_gremlin_query(
                    query=safe_q,
                    connection=graph_connection,
                )
            except Exception as exc:  # pylint: disable=broad-except
                data_json["template_exec_res"] = f"{exc}"
        else:
            data_json["template_exec_res"] = ""

        if need_raw:
            try:
                safe_q = _ensure_limit(raw_q)
                data_json["raw_exec_res"] = run_gremlin_query(
                    query=safe_q,
                    connection=graph_connection,
                )
            except Exception as exc:  # pylint: disable=broad-except
                data_json["raw_exec_res"] = f"{exc}"
        else:
            data_json["raw_exec_res"] = ""

        return data_json
