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

from unittest.mock import Mock, patch

from hugegraph_llm.nodes.llm_node.extract_info import ExtractNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


def test_extract_node_uses_extract_llm_config_for_property_graph():
    llm = Mock()
    node = ExtractNode()
    node.wk_input = WkFlowInput()
    node.wk_input.example_prompt = "extract prompt"
    node.wk_input.extract_type = "property_graph"
    node.wk_input.max_parallel_chunks = 2
    node.context = WkFlowState()

    with patch("hugegraph_llm.nodes.llm_node.extract_info.get_extract_llm", return_value=llm) as get_extract_llm:
        status = node.node_init()

    assert not status.isErr()
    get_extract_llm.assert_called_once()
    assert node.property_graph_extract.llm is llm
