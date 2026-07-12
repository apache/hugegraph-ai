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
import threading
import time

import gradio as gr
import pytest
from pydantic import ValidationError

from hugegraph_llm.flows.graph_extract import GraphExtractFlow
from hugegraph_llm.operators.llm_op.property_graph_extract import PropertyGraphExtract
from hugegraph_llm.state.ai_state import WkFlowInput
from hugegraph_llm.utils import graph_index_utils
from hugegraph_llm.utils.graph_extract_config import validate_graph_extract_max_workers

SCHEMA = {
    "vertexlabels": [
        {
            "id": 1,
            "name": "person",
            "id_strategy": "PRIMARY_KEY",
            "primary_keys": ["name"],
            "nullable_keys": [],
            "properties": ["name"],
        }
    ],
    "edgelabels": [],
}


class CountingLLM:
    def __init__(self, delay=0.02, fail_on=None, malformed_on=None):
        self.delay = delay
        self.fail_on = fail_on
        self.malformed_on = malformed_on
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.calls = []

    def generate(self, prompt):
        chunk = self._chunk_from_prompt(prompt)
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.calls.append(chunk)
            if chunk == self.fail_on:
                raise RuntimeError("boom")
            if chunk == self.malformed_on:
                return "this is not json"
            time.sleep(self.delay)
            return json.dumps(
                {
                    "vertices": [
                        {
                            "label": "person",
                            "type": "vertex",
                            "properties": {"name": chunk},
                        }
                    ],
                    "edges": [],
                }
            )
        finally:
            with self.lock:
                self.active -= 1

    @staticmethod
    def _chunk_from_prompt(prompt):
        for marker in (
            "first",
            "second",
            "third",
            "later",
            "bad",
            "ok",
            "a",
            "b",
            "c",
            "d",
        ):
            if marker in prompt:
                return marker
        raise AssertionError(f"Could not identify chunk in prompt: {prompt}")


def test_property_graph_extract_respects_configured_concurrency_limit():
    llm = CountingLLM()
    extractor = PropertyGraphExtract(llm, example_prompt="", max_workers=2)

    result = extractor.run({"schema": SCHEMA, "chunks": ["a", "b", "c", "d"]})

    assert llm.max_active <= 2
    assert llm.max_active > 1
    assert result["call_count"] == 4


def test_property_graph_extract_serial_mode_keeps_one_active_call():
    llm = CountingLLM()
    extractor = PropertyGraphExtract(llm, example_prompt="", max_workers=1)

    result = extractor.run({"schema": SCHEMA, "chunks": ["a", "b", "c"]})

    assert llm.max_active == 1
    assert result["call_count"] == 3


def test_property_graph_extract_preserves_chunk_merge_order_with_concurrency():
    llm = CountingLLM()
    extractor = PropertyGraphExtract(llm, example_prompt="", max_workers=3)

    result = extractor.run({"schema": SCHEMA, "chunks": ["first", "second", "third"]})

    assert [item["properties"]["name"] for item in result["vertices"]] == [
        "first",
        "second",
        "third",
    ]


def test_property_graph_extract_failed_chunk_reports_chunk_context():
    llm = CountingLLM(fail_on="bad")
    extractor = PropertyGraphExtract(llm, example_prompt="", max_workers=2)

    with pytest.raises(RuntimeError, match="chunk 2/3"):
        extractor.run({"schema": SCHEMA, "chunks": ["ok", "bad", "later"]})


def test_graph_extract_flow_prepare_stores_positive_concurrency():
    flow = GraphExtractFlow()
    prepared_input = WkFlowInput()

    flow.prepare(
        prepared_input,
        "{}",
        ["doc"],
        "prompt",
        "property_graph",
        graph_extract_max_workers=3,
    )

    assert prepared_input.graph_extract_max_workers == 3


def test_graph_extract_flow_prepare_rejects_invalid_concurrency():
    flow = GraphExtractFlow()

    with pytest.raises(ValueError, match="between 1 and 8"):
        flow.prepare(
            WkFlowInput(),
            "{}",
            ["doc"],
            "prompt",
            "property_graph",
            graph_extract_max_workers=0,
        )


def test_extract_graph_helper_forwards_concurrency(monkeypatch):
    calls = {}

    class DummyScheduler:
        def schedule_flow(self, flow_name, *args, **kwargs):
            calls["flow_name"] = flow_name
            calls["kwargs"] = kwargs
            return "ok"

    monkeypatch.setattr(
        graph_index_utils,
        "read_documents",
        lambda input_file, input_text: ["doc"],
    )
    monkeypatch.setattr(
        graph_index_utils.SchedulerSingleton,
        "get_instance",
        lambda: DummyScheduler(),
    )

    result = graph_index_utils.extract_graph([], "", "{}", "prompt", "document", 4)

    assert result == "ok"
    assert calls["kwargs"]["graph_extract_max_workers"] == 4


def test_extract_graph_helper_rejects_invalid_concurrency(monkeypatch):
    monkeypatch.setattr(
        graph_index_utils,
        "read_documents",
        lambda input_file, input_text: ["doc"],
    )

    with pytest.raises(gr.Error, match="between 1 and 8"):
        graph_index_utils.extract_graph([], "", "{}", "prompt", "document", 0)


def test_property_graph_extract_malformed_chunk_reports_chunk_context():
    llm = CountingLLM(malformed_on="bad")
    extractor = PropertyGraphExtract(llm, example_prompt="", max_workers=2)

    with pytest.raises(RuntimeError, match="chunk 2/3"):
        extractor.run({"schema": SCHEMA, "chunks": ["ok", "bad", "later"]})


def test_graph_extract_flow_prepare_rejects_concurrency_above_backend_cap():
    flow = GraphExtractFlow()

    with pytest.raises(ValueError, match="between 1 and 8"):
        flow.prepare(
            WkFlowInput(),
            "{}",
            ["doc"],
            "prompt",
            "property_graph",
            graph_extract_max_workers=9,
        )


def test_extract_graph_helper_rejects_concurrency_above_backend_cap(monkeypatch):
    monkeypatch.setattr(
        graph_index_utils,
        "read_documents",
        lambda input_file, input_text: ["doc"],
    )

    with pytest.raises(gr.Error, match="between 1 and 8"):
        graph_index_utils.extract_graph(
            [],
            "",
            "{}",
            "prompt",
            "document",
            9,
        )


def test_rest_graph_extract_request_accepts_and_validates_concurrency():
    from hugegraph_llm.api.models.graph_extract_requests import GraphExtractRequest

    request = GraphExtractRequest(
        texts="doc",
        schema=SCHEMA,
        graph_extract_max_workers=4,
    )

    assert request.graph_extract_max_workers == 4

    with pytest.raises(ValidationError):
        GraphExtractRequest(
            texts="doc",
            schema=SCHEMA,
            graph_extract_max_workers=9,
        )


class BlockingLLM:
    def __init__(self):
        self.started = []
        self.release = threading.Event()
        self.lock = threading.Lock()

    def generate(self, prompt):
        chunk = CountingLLM._chunk_from_prompt(prompt)
        with self.lock:
            self.started.append(chunk)

        if chunk == "bad":
            raise RuntimeError("boom")
        if chunk == "slow":
            self.release.wait(timeout=1)

        return json.dumps(
            {
                "vertices": [
                    {
                        "label": "person",
                        "type": "vertex",
                        "properties": {"name": chunk},
                    }
                ],
                "edges": [],
            }
        )


def test_property_graph_extract_cancels_queued_chunks_after_failure():
    llm = BlockingLLM()
    extractor = PropertyGraphExtract(llm, example_prompt="", max_workers=2)

    with pytest.raises(RuntimeError, match="chunk 2/4"):
        extractor.run({"schema": SCHEMA, "chunks": ["slow", "bad", "later", "d"]})

    llm.release.set()
    time.sleep(0.05)

    assert "later" not in llm.started
    assert "d" not in llm.started


def test_property_graph_extract_parses_successful_chunk_response_once(monkeypatch):
    llm = CountingLLM()
    extractor = PropertyGraphExtract(llm, example_prompt="", max_workers=1)
    parse_count = 0
    original_parser = extractor._extract_property_graph_json

    def counting_parser(text):
        nonlocal parse_count
        parse_count += 1
        return original_parser(text)

    monkeypatch.setattr(extractor, "_extract_property_graph_json", counting_parser)

    extractor.run({"schema": SCHEMA, "chunks": ["a", "b"]})

    assert parse_count == 2


def test_graph_extract_worker_validator_rejects_fractional_and_bool_values():
    assert validate_graph_extract_max_workers(1.0) == 1
    assert validate_graph_extract_max_workers("8") == 8

    for invalid_value in (True, False, 1.9, 8.9, "1.9"):
        with pytest.raises(ValueError, match="between 1 and 8"):
            validate_graph_extract_max_workers(invalid_value)
