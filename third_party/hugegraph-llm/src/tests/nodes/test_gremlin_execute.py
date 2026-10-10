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

from types import SimpleNamespace
from unittest.mock import Mock, call

from hugegraph_llm.nodes.hugegraph_node.gremlin_execute import GremlinExecuteNode


def test_gremlin_execute_passes_request_connection_to_both_queries(monkeypatch):
    execute = Mock(side_effect=["template-result", "raw-result"])
    monkeypatch.setattr("hugegraph_llm.nodes.hugegraph_node.gremlin_execute.run_gremlin_query", execute)
    connection = {"url": "http://graph.example:8080", "graph": "target"}
    node = GremlinExecuteNode()
    node.wk_input = SimpleNamespace(
        requested_outputs=["template_execution_result", "raw_execution_result"],
        graph_client_config=connection,
    )

    result = node.operator_schedule({"result": "g.V()", "raw_result": "g.E()"})

    assert result["template_exec_res"] == "template-result"
    assert result["raw_exec_res"] == "raw-result"
    assert execute.call_args_list == [
        call(query="g.V().limit(100)", connection=connection),
        call(query="g.E().limit(100)", connection=connection),
    ]


def test_gremlin_execute_defaults_to_global_connection(monkeypatch):
    execute = Mock(return_value="result")
    monkeypatch.setattr("hugegraph_llm.nodes.hugegraph_node.gremlin_execute.run_gremlin_query", execute)
    node = GremlinExecuteNode()
    node.wk_input = SimpleNamespace(requested_outputs=["raw_execution_result"])

    result = node.operator_schedule({"raw_result": "g.V().limit(1)"})

    assert result["raw_exec_res"] == "result"
    execute.assert_called_once_with(query="g.V().limit(1)", connection=None)
