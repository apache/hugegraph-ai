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

from unittest.mock import patch

from hugegraph_llm.nodes.index_node.build_gremlin_example_index import BuildGremlinExampleIndexNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


@patch("hugegraph_llm.nodes.index_node.build_gremlin_example_index.Embeddings")
@patch("hugegraph_llm.utils.vector_index_utils.get_vector_index_class")
def test_node_init_rejects_empty_examples(mock_get_vector_index_class, mock_embeddings):
    node = BuildGremlinExampleIndexNode()
    node.wk_input = WkFlowInput()
    node.wk_input.examples = []
    node.context = WkFlowState()

    status = node.node_init()

    assert status.isErr()
    mock_get_vector_index_class.assert_not_called()
    mock_embeddings.assert_not_called()
    assert not hasattr(node, "build_gremlin_example_index_op")
