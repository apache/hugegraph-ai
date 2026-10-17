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


"""Cross-config races with real dotenv persistence and deterministic interleavings."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock
from unittest.mock import Mock

import pytest
import requests
from dotenv import dotenv_values
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from hugegraph_llm import config
from hugegraph_llm.api import rag_api
from hugegraph_llm.config.hugegraph_config import HugeGraphConfig
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.config.models import base_config
from hugegraph_llm.demo.rag_demo import configs_block

pytestmark = pytest.mark.contract
ROLES = ("chat", "extract", "text2gql")


class ObservedLock:
    """Keep real locking semantics and notify only when a caller must wait."""

    def __init__(self, competing_progress):
        self.lock = RLock()
        self.competing_progress = competing_progress
        self.waited = Event()

    def __enter__(self):
        if not self.lock.acquire(blocking=False):
            self.waited.set()
            self.competing_progress.set()
            self.lock.acquire()
        return self

    def __exit__(self, *_args):
        self.lock.release()


@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    # model_construct avoids BaseConfig initialization and its environment-file
    # side effects. Only this test-owned object and file receive mutations.
    settings = LLMConfig.model_construct()
    for field in settings.model_dump():
        if field.endswith("api_key"):
            setattr(settings, field, "synthetic-old-key")
    for role in ROLES:
        setattr(settings, f"{role}_llm_type", "openai")
        for provider in ("openai", "litellm"):
            setattr(settings, f"{provider}_{role}_api_base", "http://old.invalid/v1")
            setattr(settings, f"{provider}_{role}_language_model", "old-model")
        setattr(settings, f"ollama_{role}_language_model", "old-model")
    settings.embedding_type = "openai"
    settings.openai_embedding_api_base = "http://old-embedding.invalid/v1"
    settings.openai_embedding_model = "old-embedding"
    settings.reranker_type = "cohere"
    settings.reranker_model = "old-reranker"
    settings.cohere_base_url = "http://old-reranker.invalid/v1/rerank"
    for module in (config, rag_api, configs_block):
        monkeypatch.setattr(module, "llm_settings", settings)
    env_file = tmp_path / ".env"
    monkeypatch.setattr(base_config, "env_path", str(env_file))
    monkeypatch.setattr(configs_block.gr, "Info", lambda *_args: None)
    return settings, env_file


def seed_file(settings, env_file, *other_settings):
    values = settings.model_dump()
    for other in other_settings:
        values.update(other.model_dump())
    env_file.write_text(
        "".join(f"{key.upper()}={value if value is not None else ''}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def make_client():
    router = APIRouter()
    rag_api.rag_http_api(
        router,
        Mock(),
        Mock(),
        Mock(),
        configs_block.apply_llm_config,
        configs_block.apply_embedding_config,
        configs_block.apply_reranker_config,
        Mock(),
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def fail_llm(client, entry):
    if entry == "http":
        return client.post(
            "/config/llm",
            json={
                "llm_type": "openai",
                "api_key": "synthetic-rejected-key",
                "api_base": "http://rejected.invalid/v1",
                "language_model": "rejected-model",
            },
        ).status_code
    with pytest.raises(configs_block.gr.Error):
        configs_block.apply_llm_config(
            "chat",
            "synthetic-rejected-key",
            "http://rejected.invalid/v1",
            "rejected-model",
            None,
        )
    return "ui-error"


def configure_other(client, kind, entry):
    if kind == "embedding":
        if entry == "http":
            return client.post(
                "/config/embedding",
                json={
                    "llm_type": "openai",
                    "api_key": "synthetic-embedding-key",
                    "api_base": "http://embedding.invalid/v1",
                    "language_model": "accepted-embedding",
                },
            ).status_code
        return configs_block.apply_embedding_config(
            "synthetic-embedding-key",
            "http://embedding.invalid/v1",
            "accepted-embedding",
        )
    if entry == "http":
        return client.post(
            "/config/rerank",
            json={
                "reranker_type": "cohere",
                "api_key": "synthetic-reranker-key",
                "reranker_model": "accepted-reranker",
                "cohere_base_url": "http://reranker.invalid/v1/rerank",
            },
        ).status_code
    return configs_block.apply_reranker_config(
        "synthetic-reranker-key",
        "accepted-reranker",
        "http://reranker.invalid/v1/rerank",
    )


def save_other_config(client, kind, entry, competing_progress):
    try:
        result = configure_other(client, kind, entry)
        assert result == (201 if entry == "http" else 200)
        return result
    finally:
        # Old unprotected writers finish their actual save before releasing the
        # failed LLM. Fixed writers instead signal while blocked in ObservedLock.
        competing_progress.set()


def install_lock(monkeypatch, competing_progress):
    lock = ObservedLock(competing_progress)
    for module in (config, rag_api, configs_block):
        monkeypatch.setattr(module, "runtime_config_lock", lock)
    return lock


def assert_disk_and_memory(settings, env_file, before, kind):
    disk = dotenv_values(env_file)
    llm_fields = rag_api._LLM_CONFIG_FIELDS
    for field in llm_fields:
        assert getattr(settings, field) == before[field]
        expected = before[field]
        assert disk[field.upper()] == (str(expected) if expected is not None else ""), field
    other_field = "openai_embedding_model" if kind == "embedding" else "reranker_model"
    assert getattr(settings, other_field) == f"accepted-{kind}"
    assert disk[other_field.upper()] == f"accepted-{kind}"


@pytest.mark.parametrize("kind", ["embedding", "reranker"])
@pytest.mark.parametrize("save_entry", ["http", "ui"])
@pytest.mark.parametrize("fail_entry", ["http", "ui"])
@pytest.mark.parametrize("failure", ["status", "exception"])
def test_other_config_save_cannot_persist_rejected_llm(
    isolated_settings,
    monkeypatch,
    kind,
    save_entry,
    fail_entry,
    failure,
):
    settings, env_file = isolated_settings
    if fail_entry == "http":
        for role in ROLES:
            setattr(settings, f"{role}_llm_type", "ollama/local")
    seed_file(settings, env_file)
    before = settings.model_dump()
    probe_entered, release_probe, competing_progress = Event(), Event(), Event()
    install_lock(monkeypatch, competing_progress)

    def probe(url, **_kwargs):
        if url.endswith("/chat/completions"):
            probe_entered.set()
            assert release_probe.wait(timeout=10)
            if failure == "exception":
                raise requests.exceptions.ConnectionError("synthetic rejected connection")
            return Mock(status_code=503, text="synthetic rejected response")
        assert url.endswith("/embeddings") or url.endswith("/check-api-key")
        return Mock(status_code=200, text="ok")

    monkeypatch.setattr(configs_block.requests, "post", probe)
    monkeypatch.setattr(configs_block.requests, "get", probe)
    with make_client() as client, ThreadPoolExecutor(max_workers=2) as pool:
        failed = pool.submit(fail_llm, client, fail_entry)
        try:
            assert probe_entered.wait(timeout=10)
            saved = pool.submit(save_other_config, client, kind, save_entry, competing_progress)
            assert competing_progress.wait(timeout=10)
        finally:
            release_probe.set()
        expected = (503 if failure == "status" else 400) if fail_entry == "http" else "ui-error"
        assert failed.result(timeout=10) == expected
        assert saved.result(timeout=10) == (201 if save_entry == "http" else 200)
    assert_disk_and_memory(settings, env_file, before, kind)


@pytest.mark.parametrize("kind", ["embedding", "reranker"])
@pytest.mark.parametrize("save_entry", ["http", "ui"])
def test_other_save_waits_through_outer_api_provider_rollback(isolated_settings, monkeypatch, kind, save_entry):
    settings, env_file = isolated_settings
    for role in ROLES:
        setattr(settings, f"{role}_llm_type", "ollama/local")
    seed_file(settings, env_file)
    before = settings.model_dump()
    rollback_entered, release_rollback, competing_progress = Event(), Event(), Event()
    install_lock(monkeypatch, competing_progress)
    original_setattr = LLMConfig.__setattr__

    def pause_provider_rollback(self, field, value):
        if self is settings and field == "chat_llm_type" and value == "ollama/local":
            rollback_entered.set()
            assert release_rollback.wait(timeout=10)
        original_setattr(self, field, value)

    monkeypatch.setattr(LLMConfig, "__setattr__", pause_provider_rollback)

    def probe(url, **_kwargs):
        if url.endswith("/chat/completions"):
            return Mock(status_code=503, text="synthetic rejected response")
        assert url.endswith("/embeddings") or url.endswith("/check-api-key")
        return Mock(status_code=200, text="ok")

    monkeypatch.setattr(configs_block.requests, "post", probe)
    monkeypatch.setattr(configs_block.requests, "get", probe)
    with make_client() as client, ThreadPoolExecutor(max_workers=2) as pool:
        failed = pool.submit(fail_llm, client, "http")
        try:
            assert rollback_entered.wait(timeout=10)
            saved = pool.submit(save_other_config, client, kind, save_entry, competing_progress)
            assert competing_progress.wait(timeout=10)
        finally:
            release_rollback.set()
        assert failed.result(timeout=10) == 503
        assert saved.result(timeout=10) == (201 if save_entry == "http" else 200)
    assert_disk_and_memory(settings, env_file, before, kind)


@pytest.mark.parametrize("kind", ["embedding", "reranker"])
@pytest.mark.parametrize("entry", ["http", "ui"])
@pytest.mark.parametrize("failure", ["status", "exception"])
def test_other_config_failure_restores_memory_and_real_file(isolated_settings, monkeypatch, kind, entry, failure):
    settings, env_file = isolated_settings
    if entry == "http":
        if kind == "embedding":
            settings.embedding_type = "ollama/local"
        else:
            settings.reranker_type = "siliconflow"
    seed_file(settings, env_file)
    before = settings.model_dump()
    file_before = env_file.read_bytes()

    def probe(url, **_kwargs):
        assert url.endswith("/embeddings") or url.endswith("/check-api-key")
        if failure == "exception":
            raise requests.exceptions.ConnectionError("synthetic rejected connection")
        return Mock(status_code=503, text="synthetic rejected response")

    monkeypatch.setattr(configs_block.requests, "post", probe)
    monkeypatch.setattr(configs_block.requests, "get", probe)
    with make_client() as client:
        if entry == "http":
            assert configure_other(client, kind, entry) == (503 if failure == "status" else 400)
        else:
            with pytest.raises(configs_block.gr.Error):
                configure_other(client, kind, entry)
    assert settings.model_dump() == before
    assert env_file.read_bytes() == file_before


@pytest.mark.parametrize("graph_status", [200, 503])
@pytest.mark.parametrize("contender", ["llm-update", "review-snapshot"])
def test_graph_config_transaction_serializes_llm_update_and_review_snapshot(
    isolated_settings,
    monkeypatch,
    graph_status,
    contender,
):
    settings, env_file = isolated_settings
    graph_settings = HugeGraphConfig.model_construct(
        graph_url="http://old-graph.invalid",
        graph_name="old-graph",
        graph_user="synthetic-user",
        graph_pwd="synthetic-password",
        graph_space=None,
    )
    monkeypatch.setattr(configs_block, "huge_settings", graph_settings)
    seed_file(settings, env_file, graph_settings)
    probe_entered, release_probe, competing_progress = Event(), Event(), Event()
    lock = install_lock(monkeypatch, competing_progress)

    def graph_probe(url, **_kwargs):
        assert url == "http://new-graph.invalid/graphs/new-graph/schema"
        probe_entered.set()
        assert release_probe.wait(timeout=10)
        return Mock(status_code=graph_status, text="synthetic graph response")

    def llm_probe(url, **_kwargs):
        assert url == "http://accepted.invalid/v1/chat/completions"
        return Mock(status_code=200, text="ok")

    monkeypatch.setattr(configs_block.requests, "get", graph_probe)
    monkeypatch.setattr(configs_block.requests, "post", llm_probe)

    def compete():
        try:
            if contender == "review-snapshot":
                return config.snapshot_llm_settings()
            return configs_block.apply_llm_config(
                "chat",
                "synthetic-accepted-key",
                "http://accepted.invalid/v1",
                "accepted-model",
                None,
            )
        finally:
            competing_progress.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        graph_update = pool.submit(
            configs_block.apply_graph_config,
            "new-graph.invalid",
            "new-graph",
            "new-user",
            "new-password",
            None,
            origin_call="http",
        )
        try:
            assert probe_entered.wait(timeout=10)
            waiting = pool.submit(compete)
            assert competing_progress.wait(timeout=10)
            assert lock.waited.is_set(), "LLM update/snapshot bypassed the graph transaction lock"
        finally:
            release_probe.set()
        assert graph_update.result(timeout=10) == graph_status
        result = waiting.result(timeout=10)
    if contender == "review-snapshot":
        assert result is not settings
        assert result.model_dump() == settings.model_dump()
    else:
        assert result == 200
        assert settings.openai_chat_language_model == "accepted-model"
        assert dotenv_values(env_file)["OPENAI_CHAT_LANGUAGE_MODEL"] == "accepted-model"
    expected_graph = "new-graph" if graph_status == 200 else "old-graph"
    assert graph_settings.graph_name == expected_graph
    assert dotenv_values(env_file)["GRAPH_NAME"] == expected_graph
