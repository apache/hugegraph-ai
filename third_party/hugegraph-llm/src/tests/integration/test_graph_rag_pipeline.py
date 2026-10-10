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

import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.integration]


def test_vector_only_rag_flow_builds_production_pipeline():
    from hugegraph_llm.flows.rag_flow_vector_only import RAGVectorOnlyFlow

    pipeline = RAGVectorOnlyFlow().build_flow(
        query="Who created lop?",
        topk_return_results=2,
        vector_dis_threshold=0.8,
    )
    prepared = pipeline.getGParamWithNoEmpty("wkflow_input")
    dot = pipeline.dump()

    assert prepared.query == "Who created lop?"
    assert prepared.vector_search is True
    assert prepared.graph_search is False
    assert prepared.topk_return_results == 2
    assert prepared.vector_dis_threshold == 0.8
    assert 'label="only_vector"' in dot
    assert 'label="merge_two"' in dot
    assert 'label="vector"' in dot


def test_vector_only_rag_flow_executes_deterministic_end_to_end_smoke(monkeypatch):
    from hugegraph_llm.flows.rag_flow_vector_only import RAGVectorOnlyFlow
    from hugegraph_llm.nodes.base_node import BaseNode
    from hugegraph_llm.nodes.common_node.merge_rerank_node import MergeRerankNode
    from hugegraph_llm.nodes.index_node.vector_query_node import VectorQueryNode
    from hugegraph_llm.nodes.llm_node.answer_synthesize_node import AnswerSynthesizeNode

    monkeypatch.setattr(VectorQueryNode, "node_init", BaseNode.node_init)
    monkeypatch.setattr(MergeRerankNode, "node_init", BaseNode.node_init)
    monkeypatch.setattr(AnswerSynthesizeNode, "node_init", BaseNode.node_init)

    def vector_query(_node, data_json):
        data_json["vector_result"] = ["lop is a software vertex"]
        return data_json

    def merge_rerank(_node, data_json):
        data_json["merged_result"] = data_json["vector_result"]
        return data_json

    def synthesize_answer(_node, data_json):
        assert data_json["query"] == "Who created lop?"
        assert data_json["merged_result"] == ["lop is a software vertex"]
        data_json["vector_only_answer"] = "lop was created by marko"
        return data_json

    monkeypatch.setattr(VectorQueryNode, "operator_schedule", vector_query)
    monkeypatch.setattr(MergeRerankNode, "operator_schedule", merge_rerank)
    monkeypatch.setattr(AnswerSynthesizeNode, "operator_schedule", synthesize_answer)

    flow = RAGVectorOnlyFlow()
    pipeline = flow.build_flow(query="Who created lop?")
    assert not pipeline.init().isErr()
    assert not pipeline.run().isErr()

    assert flow.post_deal(pipeline) == {
        "raw_answer": "",
        "vector_only_answer": "lop was created by marko",
        "graph_only_answer": "",
        "graph_vector_answer": "",
    }
