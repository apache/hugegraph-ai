# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
from types import SimpleNamespace

import gradio as gr
import pytest

from hugegraph_llm.config.models import base_prompt_config
from hugegraph_llm.config.models.base_prompt_config import BasePromptConfig
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.graph_extract import GraphExtractFlow
from hugegraph_llm.operators.document_op.chunk_split import ChunkSplit
from hugegraph_llm.state.ai_state import WkFlowInput
from hugegraph_llm.utils import graph_index_utils


class DummyScheduler:
    def __init__(self):
        self.calls = []
        self.kwargs = []

    def schedule_flow(self, *args, **kwargs):
        self.calls.append(args)
        self.kwargs.append(kwargs)
        return "scheduled"


class DummyPipelineState:
    def to_json(self):
        return {
            "chunks": ["chunk one", "chunk two"],
            "vertices": [{"id": "person:alice"}],
            "edges": [],
        }


class DummyPipeline:
    def getGParamWithNoEmpty(self, name):
        assert name == "wkflow_state"
        return DummyPipelineState()


class CapturePipeline:
    def __init__(self):
        self.params = {}

    def createGParam(self, value, name):
        self.params[name] = value

    def registerGElement(self, *args):
        return None


def test_graph_extract_prepare_preserves_default_document_split_type():
    prepared_input = WkFlowInput()

    GraphExtractFlow().prepare(
        prepared_input,
        "{}",
        ["first document"],
        "extract prompt",
        "property_graph",
    )

    assert prepared_input.split_type == "document"


def test_graph_extract_prepare_accepts_non_default_split_type():
    prepared_input = WkFlowInput()

    GraphExtractFlow().prepare(
        prepared_input,
        "{}",
        ["first paragraph\n\nsecond paragraph"],
        "extract prompt",
        "property_graph",
        "paragraph",
    )

    assert prepared_input.split_type == "paragraph"


def test_graph_extract_prepare_rejects_invalid_split_type():
    prepared_input = WkFlowInput()

    with pytest.raises(ValueError, match="split_type must be document"):
        GraphExtractFlow().prepare(
            prepared_input,
            "{}",
            ["first document"],
            "extract prompt",
            "property_graph",
            "invalid",
        )


def test_graph_extract_build_flow_passes_non_default_split_type_to_workflow_input(
    monkeypatch,
):
    monkeypatch.setattr(
        "hugegraph_llm.flows.graph_extract.GPipeline",
        CapturePipeline,
    )

    pipeline = GraphExtractFlow().build_flow(
        "{}",
        ["first paragraph\n\nsecond paragraph"],
        "extract prompt",
        "property_graph",
        "paragraph",
    )

    assert pipeline.params["wkflow_input"].split_type == "paragraph"


def test_chunk_split_non_default_types_produce_multiple_chunks():
    paragraph_text = ("Alpha " * 120) + "\n\n" + ("Beta " * 120)
    sentence_text = "Alpha sentence. Beta sentence. Gamma sentence. Delta sentence. Epsilon sentence. Zeta sentence."

    paragraph_chunks = ChunkSplit(paragraph_text, "paragraph", "en").run(None)["chunks"]
    sentence_chunks = ChunkSplit(sentence_text, "sentence", "en").run(None)["chunks"]

    assert len(paragraph_chunks) > 1
    assert len(sentence_chunks) > 1


def test_extract_graph_helper_forwards_selected_split_type(monkeypatch):
    scheduler = DummyScheduler()
    monkeypatch.setattr(
        graph_index_utils,
        "read_documents",
        lambda input_file, input_text: ["graph extraction text"],
    )
    monkeypatch.setattr(
        graph_index_utils.SchedulerSingleton,
        "get_instance",
        lambda: scheduler,
    )

    result = graph_index_utils.extract_graph(
        [],
        "",
        "{}",
        "extract prompt",
        "sentence",
    )

    assert result == "scheduled"
    assert scheduler.calls == [
        (
            FlowName.GRAPH_EXTRACT,
            "{}",
            ["graph extraction text"],
            "extract prompt",
            "property_graph",
        )
    ]
    assert scheduler.kwargs == [{"split_type": "sentence"}]


def test_extract_graph_helper_rejects_invalid_split_type(monkeypatch):
    monkeypatch.setattr(
        graph_index_utils,
        "read_documents",
        lambda input_file, input_text: ["graph extraction text"],
    )
    monkeypatch.setattr(
        graph_index_utils.SchedulerSingleton,
        "get_instance",
        lambda: DummyScheduler(),
    )

    with pytest.raises(gr.Error, match="split_type must be document"):
        graph_index_utils.extract_graph(
            [],
            "",
            "{}",
            "extract prompt",
            "invalid",
        )


def test_graph_extract_post_deal_logs_chunk_count(monkeypatch):
    log_calls = []
    monkeypatch.setattr(
        "hugegraph_llm.flows.graph_extract.log.info",
        lambda message, *args: log_calls.append((message, args)),
    )

    result = GraphExtractFlow().post_deal(DummyPipeline())
    result_data = json.loads(result)

    assert result_data["vertices"] == [{"id": "person:alice"}]
    assert any(message == "Graph extraction chunk_count: %s" and args == (2,) for message, args in log_calls)


def test_sentence_split_returns_punctuation_delimited_sentences():
    chunks = ChunkSplit(
        "Alpha sentence one. Beta sentence two? Gamma sentence three!",
        "sentence",
        "en",
    ).run(None)["chunks"]

    assert chunks == [
        "Alpha sentence one.",
        "Beta sentence two?",
        "Gamma sentence three!",
    ]


def test_prompt_config_round_trips_graph_extract_split_type(monkeypatch, tmp_path):
    prompt_path = tmp_path / "config_prompt.yaml"
    monkeypatch.setattr(base_prompt_config, "yaml_file_path", str(prompt_path))

    config = BasePromptConfig()
    config.llm_settings = SimpleNamespace(language="en")
    config.graph_extract_split_type = "sentence"
    config.save_to_yaml()

    reloaded = BasePromptConfig()
    reloaded.llm_settings = SimpleNamespace(language="en")
    reloaded.ensure_yaml_file_exists()

    assert reloaded.graph_extract_split_type == "sentence"
