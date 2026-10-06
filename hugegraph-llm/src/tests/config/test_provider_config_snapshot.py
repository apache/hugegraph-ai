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

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import gradio as gr
import pytest

from hugegraph_llm.config import llm_settings, runtime_config_lock
from hugegraph_llm.config.models import base_config
from hugegraph_llm.demo.rag_demo import configs_block
from hugegraph_llm.models.embeddings import init_embedding
from hugegraph_llm.models.llms import init_llm
from hugegraph_llm.models.rerankers import init_reranker

pytestmark = pytest.mark.unit

PROVIDER_ENTRIES = [
    "chat_function",
    "extract_function",
    "text2gql_function",
    "embedding_function",
    "chat_factory",
    "extract_factory",
    "text2gql_factory",
    "embedding_factory",
    "reranker_factory",
]


def _config_values(suffix, provider="openai"):
    values = llm_settings.model_dump() | {
        "chat_llm_type": provider,
        "extract_llm_type": provider,
        "text2gql_llm_type": provider,
        "embedding_type": provider,
        "reranker_type": "cohere" if provider == "openai" else "siliconflow",
        "reranker_model": f"reranker-{suffix}",
        "reranker_api_key": f"reranker-key-{suffix}",
        "cohere_base_url": f"https://reranker-{suffix}.example/v1",
    }
    for prefix in ("openai", "litellm"):
        for role in ("chat", "extract", "text2gql", "embedding"):
            model_key = "model" if role == "embedding" else "language_model"
            values[f"{prefix}_{role}_{model_key}"] = f"{role}-{suffix}"
            values[f"{prefix}_{role}_api_key"] = f"{role}-key-{suffix}"
            values[f"{prefix}_{role}_api_base"] = f"https://{role}-{suffix}.example/v1"
            if role != "embedding":
                values[f"{prefix}_{role}_tokens"] = 256 if suffix == "old" else 512
    for role in ("chat", "extract", "text2gql", "embedding"):
        model_key = "model" if role == "embedding" else "language_model"
        values[f"ollama_{role}_{model_key}"] = f"{role}-{suffix}"
        values[f"ollama_{role}_host"] = f"host-{suffix}"
        values[f"ollama_{role}_port"] = 11434 if suffix == "old" else 11435
    return values


@pytest.fixture
def reload_config(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(base_config, "env_path", str(env_file))
    monkeypatch.setitem(llm_settings.model_config, "env_file", str(env_file))
    original = llm_settings.model_dump()
    with runtime_config_lock:
        configs_block._restore_config(llm_settings, _config_values("old"))
    with gr.Blocks() as ui:
        configs_block.create_configs_block(ui)
    refresh = next(fn.fn for fn in ui.fns.values() if fn.fn.__name__ == "refresh_llm_config")

    def reload(values):
        env_file.write_text(
            "".join(f"{key.upper()}={value if value is not None else ''}\n" for key, value in values.items()),
            encoding="utf-8",
        )
        return refresh(0)

    try:
        yield reload
    finally:
        with runtime_config_lock:
            configs_block._restore_config(llm_settings, original)


def _stub_providers(monkeypatch):
    def client(provider):
        def construct(**kwargs):
            return SimpleNamespace(provider=provider, kwargs=kwargs, get_text_embedding=lambda _: [0.0, 1.0])

        return construct

    for module, providers in (
        (init_llm, {"OpenAIClient": "openai", "LiteLLMClient": "litellm", "OllamaClient": "ollama/local"}),
        (
            init_embedding,
            {"OpenAIEmbedding": "openai", "LiteLLMEmbedding": "litellm", "OllamaEmbedding": "ollama/local"},
        ),
        (init_reranker, {"CohereReranker": "cohere", "SiliconReranker": "siliconflow"}),
    ):
        for name, provider in providers.items():
            monkeypatch.setattr(module, name, client(provider))


def _create_client(entry):
    role, kind = entry.split("_")
    if role == "reranker":
        return init_reranker.Rerankers().get_reranker()
    if role == "embedding":
        return (
            init_embedding.get_embedding(llm_settings)
            if kind == "function"
            else init_embedding.Embeddings().get_embedding()
        )
    getter = f"get_{role}_llm"
    return getattr(init_llm, getter)(llm_settings) if kind == "function" else getattr(init_llm.LLMs(), getter)()


def _assert_client(client, entry, suffix, provider):
    role = entry.split("_")[0]
    if role == "reranker":
        assert client.provider == ("cohere" if provider == "openai" else "siliconflow")
        assert client.kwargs["model"] == f"reranker-{suffix}"
        assert client.kwargs["api_key"] == f"reranker-key-{suffix}"
    elif provider == "ollama/local":
        assert client.provider == provider
        assert client.kwargs == {"model": f"{role}-{suffix}", "host": f"host-{suffix}", "port": 11435}
    else:
        assert client.provider == provider
        assert client.kwargs["model_name"] == f"{role}-{suffix}"
        assert client.kwargs["api_key"] == f"{role}-key-{suffix}"
        assert client.kwargs["api_base"] == f"https://{role}-{suffix}.example/v1"
        if role != "embedding":
            assert client.kwargs["max_tokens"] == (256 if suffix == "old" else 512)


@pytest.mark.parametrize("entry", PROVIDER_ENTRIES)
@pytest.mark.parametrize("provider", ["litellm", "ollama/local"])
def test_provider_reads_wait_for_complete_page_reload(reload_config, monkeypatch, entry, provider):
    _stub_providers(monkeypatch)
    halfway = threading.Event()
    resume = threading.Event()
    reader_started = threading.Event()
    reader_done = threading.Event()
    original_setattr = type(llm_settings).__setattr__

    def pause_reload(settings, name, value):
        original_setattr(settings, name, value)
        if settings is llm_settings and name == "reranker_type":
            # All provider types are new, while models, credentials and endpoints are still old.
            halfway.set()
            assert resume.wait(5), "Reload was not released"

    def read():
        reader_started.set()
        try:
            return _create_client(entry)
        finally:
            reader_done.set()

    monkeypatch.setattr(type(llm_settings), "__setattr__", pause_reload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(reload_config, _config_values("new", provider))
        try:
            assert halfway.wait(5), "Reload did not reach the partial update"
            reader = pool.submit(read)
            assert reader_started.wait(5)
            read_partial_config = reader_done.wait(0.2)
        finally:
            resume.set()
        assert writer.result(timeout=5)[-1] == 1
        client = reader.result(timeout=5)

    assert not read_partial_config, "Provider construction read partially updated settings"
    _assert_client(client, entry, "new", provider)


@pytest.mark.parametrize("role", ["chat", "extract", "text2gql", "embedding", "reranker"])
def test_factory_keeps_provider_and_parameters_from_one_snapshot(reload_config, monkeypatch, role):
    _stub_providers(monkeypatch)
    if role == "embedding":
        getter = init_embedding.Embeddings().get_embedding
    elif role == "reranker":
        getter = init_reranker.Rerankers().get_reranker
    else:
        getter = getattr(init_llm.LLMs(), f"get_{role}_llm")
    reload_config(_config_values("new", "litellm"))

    _assert_client(getter(), f"{role}_factory", "old", "openai")


def test_embedding_dimension_probe_does_not_mix_config_or_hold_lock(reload_config, monkeypatch):
    reload_config(_config_values("old", "litellm"))
    constructed = []

    def probe(_):
        # Simulate a concurrent refresh during the provider request.
        completed = threading.Event()

        def refresh():
            try:
                reload_config(_config_values("new", "litellm"))
            finally:
                completed.set()

        worker = threading.Thread(target=refresh, daemon=True)
        worker.start()
        assert completed.wait(5), "A provider request held the configuration lock"
        worker.join(timeout=5)
        return [0.0, 1.0]

    def embedding(**kwargs):
        constructed.append(kwargs)
        return SimpleNamespace(get_text_embedding=probe)

    monkeypatch.setattr(init_embedding, "LiteLLMEmbedding", embedding)
    init_embedding.Embeddings().get_embedding()

    assert len(constructed) == 2
    assert constructed[0]["model_name"] == constructed[1]["model_name"] == "embedding-old"
    assert constructed[0]["api_key"] == constructed[1]["api_key"] == "embedding-key-old"
    assert constructed[0]["api_base"] == constructed[1]["api_base"] == "https://embedding-old.example/v1"
    assert constructed[1]["embedding_dimension"] == 2


def test_litellm_embedding_function_constructs_real_client(reload_config):
    reload_config(_config_values("new", "litellm"))

    embedding = init_embedding.get_embedding(llm_settings)

    assert isinstance(embedding, init_embedding.LiteLLMEmbedding)
    assert embedding.model == "embedding-new"
    assert embedding.api_key == "embedding-key-new"
    assert embedding.api_base == "https://embedding-new.example/v1"
    assert embedding.get_embedding_dim() == 1536


def test_litellm_embedding_connection_check_constructs_real_client(monkeypatch):
    monkeypatch.setattr(init_embedding.LiteLLMEmbedding, "get_text_embedding", lambda self, _: [0.0, 1.0])

    assert configs_block.test_litellm_embedding("key", "https://embedding.example/v1", "openai/model") == 200
