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


"""Regression checks for atomic LLM updates and request snapshots."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock, current_thread
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from hugegraph_llm import config
from hugegraph_llm.api import rag_api
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.demo.rag_demo import configs_block

pytestmark = pytest.mark.unit


@pytest.fixture
def settings(monkeypatch):
    values = {
        "chat_llm_type": "openai",
        "extract_llm_type": "openai",
        "text2gql_llm_type": "openai",
        "openai_chat_api_key": "key-a",
        "openai_chat_api_base": "http://model-a.invalid/v1",
        "openai_chat_language_model": "model-a",
        "openai_chat_tokens": 37,
    }
    for role in ("extract", "text2gql"):
        for field in ("api_key", "api_base", "language_model", "tokens"):
            values[f"openai_{role}_{field}"] = getattr(config.llm_settings, f"openai_{role}_{field}")
    for field, value in values.items():
        monkeypatch.setattr(config.llm_settings, field, value)
    monkeypatch.setattr(LLMConfig, "update_env", lambda _self: None)
    monkeypatch.setattr(configs_block, "test_api_connection", lambda *_args, **_kwargs: 200)
    monkeypatch.setattr(configs_block.gr, "Info", lambda *_args: None)
    return config.llm_settings


def test_snapshot_is_detached_from_later_changes(settings):
    first = config.snapshot_llm_settings()
    configs_block.apply_llm_config("chat", "key-b", "http://model-b.invalid/v1", "model-b", 53)
    second = config.snapshot_llm_settings()

    assert first is not settings and second is not first
    assert (first.openai_chat_api_key, first.openai_chat_language_model) == ("key-a", "model-a")
    assert (second.openai_chat_api_key, second.openai_chat_language_model) == ("key-b", "model-b")
    first.openai_chat_language_model = "local-only"
    assert settings.openai_chat_language_model == "model-b"


class ObservedLock:
    """A real reentrant lock with an event just before the reader acquires it."""

    def __init__(self):
        self.lock = RLock()
        self.reader_attempt = Event()

    def __enter__(self):
        if current_thread().name.startswith("snapshot-reader"):
            self.reader_attempt.set()
        self.lock.acquire()
        return self

    def __exit__(self, *_args):
        self.lock.release()


@pytest.mark.parametrize("writer", ["ui", "http", "http-rollback"])
def test_snapshot_waits_for_complete_update_or_rollback(settings, monkeypatch, writer):
    lock = ObservedLock()
    for module in (config, configs_block, rag_api):
        monkeypatch.setattr(module, "runtime_config_lock", lock)
    first_write = Event()
    continue_write = Event()
    original_setattr = LLMConfig.__setattr__

    def paused_setattr(self, field, value):
        original_setattr(self, field, value)
        if self is settings and field == "openai_chat_api_key" and value == "key-b":
            first_write.set()
            assert continue_write.wait(timeout=10)

    monkeypatch.setattr(LLMConfig, "__setattr__", paused_setattr)
    if writer == "http-rollback":
        monkeypatch.setattr(configs_block, "test_api_connection", lambda *_args, **_kwargs: 500)

    def update():
        if writer == "ui":
            return configs_block.apply_llm_config("chat", "key-b", "http://model-b.invalid/v1", "model-b", 53)

        router = APIRouter()
        rag_api.rag_http_api(
            router, *(Mock() for _ in range(3)), configs_block.apply_llm_config, *(Mock() for _ in range(3))
        )
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            return client.post(
                "/config/llm",
                json={
                    "llm_type": "openai",
                    "api_key": "key-b",
                    "api_base": "http://model-b.invalid/v1",
                    "language_model": "model-b",
                    "max_tokens": "53",
                },
            ).status_code

    with (
        ThreadPoolExecutor(max_workers=1) as writers,
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="snapshot-reader") as readers,
    ):
        update_result = writers.submit(update)
        try:
            assert first_write.wait(timeout=10)
            acquired = lock.lock.acquire(blocking=False)
            if acquired:
                lock.lock.release()
            assert not acquired, "LLM updates must hold the shared snapshot lock"
            snapshot_result = readers.submit(config.snapshot_llm_settings)
            assert lock.reader_attempt.wait(timeout=10)
        finally:
            continue_write.set()
        result = snapshot_result.result(timeout=10)
        assert update_result.result(timeout=10) == {"ui": 200, "http": 201, "http-rollback": 500}[writer]

    suffix = "a" if writer == "http-rollback" else "b"
    assert result.openai_chat_api_key == f"key-{suffix}"
    assert result.openai_chat_api_base == f"http://model-{suffix}.invalid/v1"
    assert result.openai_chat_language_model == f"model-{suffix}"
    assert result.openai_chat_tokens == (37 if writer == "http-rollback" else 53)


@pytest.mark.parametrize("failure", ["tokens", "connection"])
def test_ui_failed_update_restores_complete_previous_config(settings, monkeypatch, failure):
    if failure == "connection":

        def reject_connection(*_args, **_kwargs):
            raise RuntimeError("connection failed")

        monkeypatch.setattr(configs_block, "test_api_connection", reject_connection)
    expected_error = ValueError if failure == "tokens" else RuntimeError
    with pytest.raises(expected_error):
        configs_block.apply_llm_config(
            "chat", "key-b", "http://model-b.invalid/v1", "model-b", "invalid" if failure == "tokens" else 53
        )
    snapshot = config.snapshot_llm_settings()
    assert snapshot.openai_chat_api_key == "key-a"
    assert snapshot.openai_chat_api_base == "http://model-a.invalid/v1"
    assert snapshot.openai_chat_language_model == "model-a"
    assert snapshot.openai_chat_tokens == 37
