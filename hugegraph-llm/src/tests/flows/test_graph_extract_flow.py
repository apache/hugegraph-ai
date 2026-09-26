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

from hugegraph_llm.flows.graph_extract import GraphExtractFlow
from hugegraph_llm.nodes.document_node.chunk_split import ChunkSplitNode
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState

SCHEMA = '{"vertices": [], "edges": []}'
TEXTS = ["Alice knows Bob."]
EXAMPLE_PROMPT = ""
EXTRACT_TYPE = "property_graph"


def test_prepare_writes_requested_split_type():
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()

    flow.prepare(
        prepared_input,
        SCHEMA,
        TEXTS,
        EXAMPLE_PROMPT,
        EXTRACT_TYPE,
        split_type="paragraph",
    )

    assert prepared_input.split_type == "paragraph"


def test_prepare_writes_content_type_and_parallel_chunks():
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()

    flow.prepare(
        prepared_input,
        SCHEMA,
        ["chunk-a", "chunk-b"],
        EXAMPLE_PROMPT,
        EXTRACT_TYPE,
        content_type="chunks",
        max_parallel_chunks=4,
    )

    assert prepared_input.texts == ["chunk-a", "chunk-b"]
    assert prepared_input.content_type == "chunks"
    assert prepared_input.max_parallel_chunks == 4


def test_prepare_rejects_chunks_with_non_document_split_type():
    flow = GraphExtractFlow()

    try:
        flow.prepare(
            WkFlowInput(),
            SCHEMA,
            ["chunk-a"],
            EXAMPLE_PROMPT,
            EXTRACT_TYPE,
            split_type="paragraph",
            content_type="chunks",
        )
    except ValueError as exc:
        assert "split_type must be document when content_type is chunks" in str(exc)
    else:
        raise AssertionError("chunks content must reject non-document split_type")


def test_chunk_split_node_uses_pre_split_chunks_without_splitting():
    node = ChunkSplitNode()
    node.wk_input = WkFlowInput()
    node.wk_input.texts = ["chunk-a\n\nchunk-b", "chunk-c"]
    node.wk_input.language = "en"
    node.wk_input.split_type = "document"
    node.wk_input.content_type = "chunks"
    node.context = WkFlowState()

    status = node.node_init()
    result = node.operator_schedule({})

    assert not status.isErr()
    assert node.chunk_split_op is None
    assert result["chunks"] == ["chunk-a\n\nchunk-b", "chunk-c"]


def test_build_flow_writes_requested_split_type_to_workflow_input():
    flow = GraphExtractFlow()

    pipeline = flow.build_flow(
        SCHEMA,
        TEXTS,
        EXAMPLE_PROMPT,
        EXTRACT_TYPE,
        split_type="paragraph",
    )

    wkflow_input = pipeline.getGParamWithNoEmpty("wkflow_input")
    assert wkflow_input.split_type == "paragraph"


def test_build_flow_defaults_to_document_split_type_for_existing_callers():
    flow = GraphExtractFlow()

    pipeline = flow.build_flow(SCHEMA, TEXTS, EXAMPLE_PROMPT, EXTRACT_TYPE)

    wkflow_input = pipeline.getGParamWithNoEmpty("wkflow_input")
    assert wkflow_input.split_type == "document"


def test_workflow_state_setup_clears_graph_extract_result_fields():
    state = WkFlowState()
    state.vertices = [{"id": "old"}]
    state.edges = [{"id": "old-edge"}]
    state.triples = [("old", "rel", "value")]
    state.chunks = ["old chunk"]
    state.call_count = 10
    state.max_parallel_chunks = 2

    status = state.setup()

    assert not status.isErr()
    assert state.vertices is None
    assert state.edges is None
    assert state.triples is None
    assert state.chunks is None
    assert state.call_count is None
    assert state.max_parallel_chunks is None
