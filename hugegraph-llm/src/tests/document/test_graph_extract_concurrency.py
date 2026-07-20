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
import re
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
        match = re.search(r"## Text:\s*(.*?)\s*## Graph schema", prompt, re.DOTALL)
        if not match:
            raise AssertionError(f"Could not identify chunk in prompt: {prompt}")
        return match.group(1).strip()


def test_property_graph_extract_respects_configured_concurrency_limit():
    class OverlapLLM:
        def __init__(self):
            self.active = 0
            self.max_active = 0
            self.calls = []
            self.lock = threading.Lock()
            self.two_workers_started = threading.Event()

        def generate(self, prompt):
            chunk = CountingLLM._chunk_from_prompt(prompt)
            with self.lock:
                self.calls.append(chunk)
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                if len(self.calls) == 2:
                    self.two_workers_started.set()

            try:
                if chunk in {"FIRST_CHUNK", "SECOND_CHUNK"}:
                    assert self.two_workers_started.wait(timeout=2)
                    time.sleep(0.02)

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

    llm = OverlapLLM()
    extractor = PropertyGraphExtract(llm, example_prompt="", max_workers=2)

    result = extractor.run({"schema": SCHEMA, "chunks": ["FIRST_CHUNK", "SECOND_CHUNK", "THIRD_CHUNK"]})

    assert llm.max_active == 2
    assert result["call_count"] == 3


def test_property_graph_extract_serial_mode_keeps_one_active_call():
    llm = CountingLLM()
    extractor = PropertyGraphExtract(llm, example_prompt="", max_workers=1)

    result = extractor.run({"schema": SCHEMA, "chunks": ["a", "b", "c"]})

    assert llm.max_active == 1
    assert result["call_count"] == 3


def test_property_graph_extract_preserves_chunk_merge_order_with_concurrency():
    class ReverseFinishLLM:
        def __init__(self):
            self.first_started = threading.Event()
            self.release_first = threading.Event()
            self.completion_order = []
            self.lock = threading.Lock()

        def generate(self, prompt):
            if "FIRST_CHUNK" in prompt:
                chunk_name = "FIRST_CHUNK"
                self.first_started.set()
                self.release_first.wait(timeout=2)
                time.sleep(0.05)
            elif "SECOND_CHUNK" in prompt:
                chunk_name = "SECOND_CHUNK"
                assert self.first_started.wait(timeout=2)
                self.release_first.set()
            else:
                raise AssertionError(f"Unexpected prompt: {prompt}")

            with self.lock:
                self.completion_order.append(chunk_name)

            return json.dumps(
                {
                    "vertices": [
                        {
                            "label": "person",
                            "type": "vertex",
                            "properties": {"name": chunk_name},
                        }
                    ],
                    "edges": [],
                }
            )

    llm = ReverseFinishLLM()
    extractor = PropertyGraphExtract(llm, example_prompt="", max_workers=2)

    result = extractor.run({"schema": SCHEMA, "chunks": ["FIRST_CHUNK", "SECOND_CHUNK"]})

    assert llm.completion_order == ["SECOND_CHUNK", "FIRST_CHUNK"]
    assert [vertex["properties"]["name"] for vertex in result["vertices"]] == [
        "FIRST_CHUNK",
        "SECOND_CHUNK",
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


def test_property_graph_extract_accepts_vertices_without_explicit_type():
    class UntypedVertexLLM:
        def generate(self, prompt):
            return json.dumps(
                {
                    "vertices": [
                        {
                            "label": "person",
                            "properties": {"name": "Ada"},
                        },
                        {
                            "label": "person",
                            "properties": {"name": "Bob"},
                        },
                    ],
                    "edges": [],
                }
            )

    extractor = PropertyGraphExtract(UntypedVertexLLM(), example_prompt="", max_workers=1)

    result = extractor.run({"schema": SCHEMA, "chunks": ["a"]})

    assert [vertex["label"] for vertex in result["vertices"]] == ["person", "person"]
    assert [vertex["type"] for vertex in result["vertices"]] == ["vertex", "vertex"]


def test_property_graph_extract_malformed_container_shape_reports_chunk_context():
    class MalformedContainerLLM:
        def generate(self, prompt):
            return json.dumps(
                {
                    "vertices": {},
                    "edges": [],
                }
            )

    extractor = PropertyGraphExtract(MalformedContainerLLM(), example_prompt="", max_workers=1)

    with pytest.raises(RuntimeError, match="chunk 1/1"):
        extractor.run({"schema": SCHEMA, "chunks": ["a"]})


def test_property_graph_extract_waits_for_in_flight_call_after_failure():
    class LifecycleLLM:
        def __init__(self):
            self.slow_started = threading.Event()
            self.fail_started = threading.Event()
            self.release_slow = threading.Event()
            self.slow_finished = threading.Event()
            self.calls = []
            self.lock = threading.Lock()

        def generate(self, prompt):
            with self.lock:
                if "LATER_CHUNK" in prompt:
                    self.calls.append("LATER_CHUNK")
                elif "SLOW_CHUNK" in prompt:
                    self.calls.append("SLOW_CHUNK")
                elif "FAIL_CHUNK" in prompt:
                    self.calls.append("FAIL_CHUNK")

            if "SLOW_CHUNK" in prompt:
                self.slow_started.set()
                self.release_slow.wait(timeout=2)
                self.slow_finished.set()
                return json.dumps({"vertices": [], "edges": []})

            if "FAIL_CHUNK" in prompt:
                assert self.slow_started.wait(timeout=2)
                self.fail_started.set()
                raise ValueError("fast failure")

            if "LATER_CHUNK" in prompt:
                return json.dumps({"vertices": [], "edges": []})

            raise AssertionError(f"Unexpected prompt: {prompt}")

    llm = LifecycleLLM()
    extractor = PropertyGraphExtract(llm, example_prompt="", max_workers=2)
    returned = threading.Event()
    errors = []

    def run_extractor():
        try:
            extractor.run({"schema": SCHEMA, "chunks": ["SLOW_CHUNK", "FAIL_CHUNK", "LATER_CHUNK"]})
        except Exception as exc:
            errors.append(exc)
        finally:
            returned.set()

    run_thread = threading.Thread(target=run_extractor)
    run_thread.start()

    try:
        assert llm.slow_started.wait(timeout=2)
        assert llm.fail_started.wait(timeout=2)
        time.sleep(0.05)
        assert not returned.is_set()
        assert not llm.slow_finished.is_set()
    finally:
        llm.release_slow.set()
        run_thread.join(timeout=2)

    assert returned.is_set()
    assert llm.slow_finished.is_set()
    assert errors
    assert "chunk 2/3" in str(errors[0])
    assert "LATER_CHUNK" not in llm.calls


def test_property_graph_extract_reports_lowest_in_flight_failure_index():
    class FailureOrderLLM:
        def __init__(self):
            self.first_started = threading.Event()
            self.second_failed = threading.Event()
            self.calls = []
            self.lock = threading.Lock()

        def generate(self, prompt):
            with self.lock:
                if "LATER_CHUNK" in prompt:
                    self.calls.append("LATER_CHUNK")
                elif "FIRST_FAIL_CHUNK" in prompt:
                    self.calls.append("FIRST_FAIL_CHUNK")
                elif "SECOND_FAIL_CHUNK" in prompt:
                    self.calls.append("SECOND_FAIL_CHUNK")

            if "FIRST_FAIL_CHUNK" in prompt:
                self.first_started.set()
                assert self.second_failed.wait(timeout=2)
                raise ValueError("first failure")

            if "SECOND_FAIL_CHUNK" in prompt:
                assert self.first_started.wait(timeout=2)
                self.second_failed.set()
                raise ValueError("second failure")

            if "LATER_CHUNK" in prompt:
                return json.dumps({"vertices": [], "edges": []})

            raise AssertionError(f"Unexpected prompt: {prompt}")

    llm = FailureOrderLLM()
    extractor = PropertyGraphExtract(llm, example_prompt="", max_workers=2)

    with pytest.raises(RuntimeError, match="chunk 1/3"):
        extractor.run({"schema": SCHEMA, "chunks": ["FIRST_FAIL_CHUNK", "SECOND_FAIL_CHUNK", "LATER_CHUNK"]})

    assert "LATER_CHUNK" not in llm.calls


def test_property_graph_extract_malformed_item_fields_report_chunk_context():
    class MalformedItemFieldsLLM:
        def generate(self, prompt):
            return json.dumps(
                {
                    "vertices": [
                        {
                            "label": "person",
                            "type": "vertex",
                            "properties": ["not", "a", "mapping"],
                        }
                    ],
                    "edges": [],
                }
            )

    extractor = PropertyGraphExtract(MalformedItemFieldsLLM(), example_prompt="", max_workers=1)

    with pytest.raises(RuntimeError, match="chunk 1/1"):
        extractor.run({"schema": SCHEMA, "chunks": ["a"]})
