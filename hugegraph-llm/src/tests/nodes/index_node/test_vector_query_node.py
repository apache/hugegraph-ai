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

from hugegraph_llm.nodes.index_node.vector_query_node import VectorQueryNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


@patch("hugegraph_llm.nodes.index_node.vector_query_node.VectorIndexQuery")
@patch("hugegraph_llm.nodes.index_node.vector_query_node.Embeddings")
@patch("hugegraph_llm.utils.vector_index_utils.get_vector_index_class")
def test_node_init_passes_topk_and_threshold_to_operator(mock_get_vector_index_class, mock_embeddings, mock_query_cls):
    """Flow input (max_items, vector_dis_threshold) reaches the operator instead of being hard-coded."""
    node = VectorQueryNode()
    node.wk_input = WkFlowInput()
    node.wk_input.max_items = 5
    node.wk_input.vector_dis_threshold = 1.2
    node.context = WkFlowState()

    status = node.node_init()

    assert not status.isErr()
    _, kwargs = mock_query_cls.call_args
    assert kwargs["topk"] == 5
    assert kwargs["vector_dis_threshold"] == 1.2


@patch("hugegraph_llm.nodes.index_node.vector_query_node.VectorIndexQuery")
@patch("hugegraph_llm.nodes.index_node.vector_query_node.Embeddings")
@patch("hugegraph_llm.utils.vector_index_utils.get_vector_index_class")
def test_node_init_forwards_unset_threshold(mock_get_vector_index_class, mock_embeddings, mock_query_cls):
    """An unset flow threshold is forwarded as None so the operator resolves the settings default."""
    node = VectorQueryNode()
    node.wk_input = WkFlowInput()
    node.context = WkFlowState()

    status = node.node_init()

    assert not status.isErr()
    _, kwargs = mock_query_cls.call_args
    assert kwargs["vector_dis_threshold"] is None
