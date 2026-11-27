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

"""The /rag trace must travel from the request through the flow state."""

from hugegraph_llm.flows.rag_flow_graph_only import RAGGraphOnlyFlow
from hugegraph_llm.flows.rag_flow_graph_vector import RAGGraphVectorFlow
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState

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


def _prepare(flow, **kwargs):
    prepared_input = WkFlowInput()
    flow.prepare(prepared_input, query="q", **kwargs)
    return prepared_input


def test_prepare_puts_include_trace_in_the_state_json():
    # The data_json keys are copied into WkFlowState; missing this key was why
    # the trace stayed empty even though post_deal looked correct.
    for flow in (RAGGraphOnlyFlow(), RAGGraphVectorFlow()):
        prepared_input = _prepare(flow, include_trace=True)
        assert prepared_input.include_trace is True
        assert prepared_input.data_json["include_trace"] is True

        state = WkFlowState()
        state.assign_from_json(prepared_input.data_json)
        assert state.to_json()["include_trace"] is True


def test_prepare_defaults_to_no_trace():
    for flow in (RAGGraphOnlyFlow(), RAGGraphVectorFlow()):
        prepared_input = _prepare(flow)
        assert prepared_input.data_json["include_trace"] is False


def test_graph_vector_post_deal_keeps_answer_contract_by_default():
    flow = RAGGraphVectorFlow()
    assert flow.post_deal(_Pipeline(dict(ANSWERS, **TRACE))) == ANSWERS


def test_graph_vector_post_deal_returns_trace_when_requested():
    payload = dict(ANSWERS, **TRACE, include_trace=True)
    assert RAGGraphVectorFlow().post_deal(_Pipeline(payload)) == payload


def test_graph_only_post_deal_returns_trace_when_requested():
    payload = dict(ANSWERS, **TRACE, include_trace=True)
    assert RAGGraphOnlyFlow().post_deal(_Pipeline(payload)) == payload


def test_graph_only_post_deal_keeps_answer_contract_by_default():
    flow = RAGGraphOnlyFlow()
    assert flow.post_deal(_Pipeline(dict(ANSWERS, **TRACE))) == ANSWERS


def test_graph_only_recall_only_mode_still_returns_the_state():
    # Existing behaviour used by the text2gremlin recall path must survive.
    payload = dict(ANSWERS, **TRACE, is_graph_rag_recall=True)
    assert RAGGraphOnlyFlow().post_deal(_Pipeline(payload)) == payload
