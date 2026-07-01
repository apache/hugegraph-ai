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

from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


class RuntimeFailingNode(BaseNode):
    def operator_schedule(self, data_json):
        raise RuntimeError("llm provider timeout")


def test_base_node_converts_unexpected_operator_exception_to_error_status():
    node = RuntimeFailingNode()
    node.wk_input = WkFlowInput()
    node.context = WkFlowState()

    status = node.run()

    assert status.isErr()
    assert "llm provider timeout" in status.getInfo()
    assert "RuntimeFailingNode" in status.getInfo()
    assert "Traceback" not in status.getInfo()
