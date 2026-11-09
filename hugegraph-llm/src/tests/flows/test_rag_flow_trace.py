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

"""The /rag trace is only reachable if the flows hand their state back."""

from hugegraph_llm.flows.rag_flow_graph_only import RAGGraphOnlyFlow
from hugegraph_llm.flows.rag_flow_graph_vector import RAGGraphVectorFlow

ANSWERS = {
    "raw_answer": "raw",
    "vector_only_answer": "vector",
    "graph_only_answer": "graph",
    "graph_vector_answer": "graph+vector",
}

TRACE = {
    "keywords": ["alice"],
    "match_vids": ["1:alice"],
    "graph_result_flag": 1,
    "gremlin": "g.V().limit(1)",
    "graph_result": [{"id": "1:alice"}],
    "vertex_degree_list": [],
}


class _State:
    def __init__(self, payload):
        self._payload = payload

    def to_json(self):
        return self._payload


class _Pipeline:
    def __init__(self, payload):
        self._payload = payload

    def getGParamWithNoEmpty(self, _name):
        return _State(self._payload)


def test_graph_vector_post_deal_keeps_answer_contract_by_default():
    flow = RAGGraphVectorFlow()
    result = flow.post_deal(_Pipeline(dict(ANSWERS, **TRACE)))
    assert result == ANSWERS


def test_graph_vector_post_deal_returns_trace_when_requested():
    payload = dict(ANSWERS, **TRACE, is_graph_rag_recall=True)
    flow = RAGGraphVectorFlow()
    result = flow.post_deal(_Pipeline(payload))
    assert result == payload
    assert result["gremlin"] == TRACE["gremlin"]


def test_graph_only_post_deal_returns_trace_when_requested():
    payload = dict(ANSWERS, **TRACE, is_graph_rag_recall=True)
    flow = RAGGraphOnlyFlow()
    result = flow.post_deal(_Pipeline(payload))
    assert result == payload
    assert result["match_vids"] == TRACE["match_vids"]


def test_graph_only_post_deal_keeps_answer_contract_by_default():
    flow = RAGGraphOnlyFlow()
    result = flow.post_deal(_Pipeline(dict(ANSWERS, **TRACE)))
    assert result == ANSWERS
