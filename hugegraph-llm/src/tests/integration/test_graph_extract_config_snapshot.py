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


"""Keep the actual HTTP/scheduler/client chain while interleaving a UI config write."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from openai.resources.chat.completions import Completions
from openai.types.chat import ChatCompletion

from hugegraph_llm.api.graph_extract_api import graph_extract_http_api
from hugegraph_llm.config import llm_settings
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.demo.rag_demo import configs_block
from hugegraph_llm.flows.scheduler import Scheduler, SchedulerSingleton

pytestmark = pytest.mark.contract
SCHEMA = {
    "vertexlabels": [
        {
            "id": 1,
            "name": "person",
            "id_strategy": "PRIMARY_KEY",
            "properties": ["name"],
            "primary_keys": ["name"],
            "nullable_keys": [],
        }
    ],
    "edgelabels": [],
    "propertykeys": [{"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"}],
}
GRAPH = {"vertices": [{"id": "1:Alice", "label": "person", "properties": {"name": "Alice"}}], "edges": []}
PASS = {"decision": "pass", "issues": []}


@pytest.mark.parametrize("max_workers", [1, 2])
def test_reviewed_http_uses_one_configuration_across_chunks_and_refreshes_next_request(monkeypatch, max_workers):
    for field, value in {
        "chat_llm_type": "openai",
        "openai_chat_api_key": "key-a",
        "openai_chat_api_base": "http://model-a.invalid/v1",
        "openai_chat_language_model": "model-a",
        "openai_chat_tokens": 37,
    }.items():
        monkeypatch.setattr(llm_settings, field, value)
    monkeypatch.setattr(LLMConfig, "update_env", lambda _self: None)
    monkeypatch.setattr(configs_block.gr, "Info", lambda *_args: None)
    monkeypatch.setattr(configs_block, "test_api_connection", lambda *_args, **_kwargs: 200)
    monkeypatch.setattr(SchedulerSingleton, "_instance", Scheduler())
    first_call = Event()
    config_updated = Event()
    calls = []
    counts = {}
    clients = []
    lock = Lock()

    def completion(self, **kwargs):
        with lock:
            clients.append(self)
            calls.append((kwargs["model"], self._client.api_key, str(self._client.base_url)))
            count = counts.get(id(self), 0)
            counts[id(self)] = count + 1
            is_first_call = len(calls) == 1
        if is_first_call:
            first_call.set()
            # This would deadlock if inference retained the configuration lock.
            assert config_updated.wait(timeout=10)
        content = GRAPH if count == 0 else PASS
        return ChatCompletion(
            id="snapshot-test",
            created=1,
            model=kwargs["model"],
            object="chat.completion",
            choices=[
                {"index": 0, "message": {"role": "assistant", "content": json.dumps(content)}, "finish_reason": "stop"}
            ],
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )

    monkeypatch.setattr(Completions, "create", completion)
    router = APIRouter()
    graph_extract_http_api(router)
    app = FastAPI()
    app.include_router(router)
    payload = {
        "texts": ["Alice is a person.", "Alice is named Alice."],
        "schema": SCHEMA,
        "review_options": {"max_workers": max_workers},
    }
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        response = pool.submit(client.post, "/graph/extract", json=payload)
        try:
            assert first_call.wait(timeout=10)
            configs_block.apply_llm_config("chat", "key-b", "http://model-b.invalid/v1", "model-b", 53)
        finally:
            config_updated.set()
        data = response.result(timeout=10)
        assert data.status_code == 200
        assert data.json()["status"] == "succeeded"
        assert calls == [("model-a", "key-a", "http://model-a.invalid/v1/")] * 4
        calls.clear()
        counts.clear()
        later = client.post("/graph/extract", json=payload)
        assert later.status_code == 200
        assert later.json()["status"] == "succeeded"
        assert calls == [("model-b", "key-b", "http://model-b.invalid/v1/")] * 4
