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

"""API request models must defer the vector distance threshold to configuration.

The request field is scoped to keyword-to-vertex matching; chunk retrieval
always prunes at CHUNK_DIS_THRESHOLD. The chain tests below drive the real
flow/node/operator hop down to the chunk store search to keep that scope.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hugegraph_llm.api.models.rag_requests import GraphRAGRequest, RAGRequest
from hugegraph_llm.config import huge_settings
from hugegraph_llm.flows.rag_flow_vector_only import RAGVectorOnlyFlow
from hugegraph_llm.nodes.index_node.semantic_id_query_node import SemanticIdQueryNode
from hugegraph_llm.nodes.index_node.vector_query_node import VectorQueryNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState

pytestmark = pytest.mark.contract


def test_rag_request_vector_threshold_defaults_to_unset():
    """Omitting vector_dis_threshold keeps it unset so CHUNK_DIS_THRESHOLD applies to chunk retrieval."""
    assert RAGRequest(query="q").vector_dis_threshold is None


def test_graph_rag_request_vector_threshold_defaults_to_unset():
    """Omitting vector_dis_threshold keeps it unset so each consumer resolves its own configured default."""
    assert GraphRAGRequest(query="q").vector_dis_threshold is None


def test_requests_accept_explicit_vector_threshold():
    """An explicit threshold (including 0) is accepted verbatim; its scope is decided per consumer."""
    assert RAGRequest(query="q", vector_dis_threshold=0).vector_dis_threshold == 0
    assert GraphRAGRequest(query="q", vector_dis_threshold=1.5).vector_dis_threshold == 1.5


def _chunk_search_dis_threshold(monkeypatch, request_threshold):
    """Drive request -> flow prepare -> VectorQueryNode -> chunk store search; return the store's dis_threshold."""
    req = RAGRequest(query="q", vector_dis_threshold=request_threshold)
    wk_input = WkFlowInput()
    RAGVectorOnlyFlow().prepare(wk_input, query=req.query, vector_dis_threshold=req.vector_dis_threshold)

    store = MagicMock()
    store.search.return_value = []
    store_class = MagicMock()
    store_class.from_name.return_value = store
    monkeypatch.setattr("hugegraph_llm.utils.vector_index_utils.get_vector_index_class", lambda name: store_class)
    monkeypatch.setattr(
        "hugegraph_llm.nodes.index_node.vector_query_node.Embeddings",
        lambda: SimpleNamespace(
            get_embedding=lambda: SimpleNamespace(
                get_embedding_dim=lambda: 2,
                get_texts_embeddings=lambda texts: [[1.0, 0.0]],
            )
        ),
    )

    node = VectorQueryNode()
    node.wk_input = wk_input
    node.context = WkFlowState()
    assert not node.node_init().isErr()
    node.operator_schedule({"query": req.query})
    return store.search.call_args.kwargs["dis_threshold"]


def test_omitted_request_threshold_keeps_chunk_retrieval_at_configured_default(monkeypatch):
    """A request without vector_dis_threshold searches chunks at CHUNK_DIS_THRESHOLD."""
    monkeypatch.setattr(huge_settings, "chunk_dis_threshold", 1.3)

    assert _chunk_search_dis_threshold(monkeypatch, None) == 1.3


def test_explicit_request_threshold_does_not_change_chunk_retrieval(monkeypatch):
    """An explicit request threshold is scoped to keyword matching and never overrides CHUNK_DIS_THRESHOLD."""
    monkeypatch.setattr(huge_settings, "chunk_dis_threshold", 1.3)

    assert _chunk_search_dis_threshold(monkeypatch, 0.9) == 1.3


def test_explicit_request_threshold_still_scopes_keyword_matching(monkeypatch):
    """The request value reaches SemanticIdQuery, which is where the API threshold is scoped."""
    req = RAGRequest(query="q", vector_dis_threshold=0.9)
    wk_input = WkFlowInput()
    RAGVectorOnlyFlow().prepare(wk_input, query=req.query, vector_dis_threshold=req.vector_dis_threshold)

    ctor_kwargs = {}
    monkeypatch.setattr(
        "hugegraph_llm.nodes.index_node.semantic_id_query_node.SemanticIdQuery",
        lambda **kwargs: ctor_kwargs.update(kwargs) or MagicMock(),
    )
    monkeypatch.setattr("hugegraph_llm.utils.vector_index_utils.get_vector_index_class", lambda name: MagicMock())
    monkeypatch.setattr(
        "hugegraph_llm.nodes.index_node.semantic_id_query_node.Embeddings",
        lambda: SimpleNamespace(get_embedding=lambda: MagicMock()),
    )

    node = SemanticIdQueryNode()
    node.wk_input = wk_input
    node.context = WkFlowState()
    assert not node.node_init().isErr()
    assert ctor_kwargs["vector_dis_threshold"] == 0.9
