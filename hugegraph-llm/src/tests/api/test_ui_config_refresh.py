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


"""A refreshed UI shows the persisted model/index settings, never the startup snapshot."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from hugegraph_llm.config.hugegraph_config import HugeGraphConfig
from hugegraph_llm.config.index_config import IndexConfig
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.demo.rag_demo import app, configs_block

pytestmark = pytest.mark.contract


# Out-of-band edits: a second config instance persists to the shared files while
# the UI singletons keep their startup snapshot, like editing settings.yaml.


def _chat_ollama():
    other = LLMConfig()
    other.chat_llm_type = "ollama/local"
    other.ollama_chat_host = "10.9.8.7"
    other.ollama_chat_port = 23456
    other.ollama_chat_language_model = "fresh-model"
    other.update_env(connection_group="chat")


def _chat_openai():
    other = LLMConfig()
    other.chat_llm_type = "openai"
    other.openai_chat_api_base = "http://fresh.invalid/v1"
    other.openai_chat_language_model = "fresh-openai"
    other.openai_chat_tokens = 4321
    other.openai_chat_api_key = "synthetic-secret-key"
    other.update_env(connection_group="chat")


def _extract_ollama():
    other = LLMConfig()
    other.extract_use_chat = False
    other.extract_llm_type = "ollama/local"
    other.ollama_extract_host = "10.1.2.3"
    other.ollama_extract_port = 12345
    other.ollama_extract_language_model = "fresh-extract"
    other.update_env(connection_group="extract")


def _embedding_openai():
    other = LLMConfig()
    other.openai_embedding_api_base = "http://fresh-embed.invalid/v1"
    other.openai_embedding_model = "fresh-embed"
    other.openai_embedding_api_key = "synthetic-secret-key"
    other.update_env(connection_group="embedding")


def _reranker_cohere():
    other = LLMConfig()
    other.reranker_type = "cohere"
    other.reranker_model = "fresh-rerank"
    other.cohere_base_url = "http://fresh-rerank.invalid/v1"
    other.reranker_api_key = "synthetic-secret-key"
    other.update_env(connection_group="reranker")


def _reranker_siliconflow():
    other = LLMConfig()
    other.reranker_type = "siliconflow"
    other.reranker_model = "fresh-rerank"
    other.update_env(connection_group="reranker")


def _vector_milvus():
    other = IndexConfig()
    other.cur_vector_index = "Milvus"
    other.milvus_host = "10.2.2.2"
    other.milvus_port = 19531
    other.milvus_user = "fresh-user"
    other.update_env(connection_group="milvus")


def _vector_engine():
    other = IndexConfig()
    other.cur_vector_index = "Milvus"
    other.update_env()


def _rendered_values(monkeypatch, render_name, provider):
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "false")
    monkeypatch.setattr(app.prompt, "update_yaml_file", Mock())
    monkeypatch.setattr(app.admin_settings, "enable_login", "false")
    ui = app.init_rag_ui()
    render = next(
        function
        for function in ui.fns.values()
        if getattr(getattr(getattr(function.fn, "__self__", None), "fn", None), "__name__", None) == render_name
    )
    monkeypatch.setattr(app, "init_rag_ui", lambda: ui)
    client = TestClient(app.create_app())
    try:
        response = client.post(
            f"/gradio_api/run/{render.api_name}",
            json={"data": [provider], "session_hash": f"refresh-{render_name}"},
        )
        assert response.status_code == 200, response.text
        components = response.json()["render_config"]["components"]
    finally:
        client.close()
        ui.close()
    return {
        component["props"].get("label"): component["props"].get("value")
        for component in components
        if component["type"] in ("textbox", "checkbox")
    }


@pytest.mark.parametrize(
    ("render_name", "provider", "edit", "expected", "secret"),
    [
        pytest.param(
            "chat_llm_settings",
            "ollama/local",
            _chat_ollama,
            {"host": "10.9.8.7", "port": "23456", "model": "fresh-model"},
            None,
            id="llm-ollama",
        ),
        pytest.param(
            "chat_llm_settings",
            "openai",
            _chat_openai,
            {"API key": "", "API base": "http://fresh.invalid/v1", "model": "fresh-openai", "max tokens": "4321"},
            "synthetic-secret-key",
            id="llm-openai",
        ),
        pytest.param(
            "extract_llm_settings",
            "ollama/local",
            _extract_ollama,
            {"host": "10.1.2.3", "port": "12345", "model": "fresh-extract"},
            None,
            id="extract-ollama",
        ),
        pytest.param(
            "embedding_settings",
            "openai",
            _embedding_openai,
            {"API key": "", "API base": "http://fresh-embed.invalid/v1", "model": "fresh-embed"},
            "synthetic-secret-key",
            id="embedding-openai",
        ),
        pytest.param(
            "reranker_settings",
            "cohere",
            _reranker_cohere,
            {"API key": "", "model": "fresh-rerank", "API base": "http://fresh-rerank.invalid/v1"},
            "synthetic-secret-key",
            id="reranker-cohere",
        ),
        pytest.param(
            "vector_engine_settings",
            "Milvus",
            _vector_milvus,
            {"host": "10.2.2.2", "port": "19531", "user": "fresh-user"},
            None,
            id="vector-milvus",
        ),
    ],
)
def test_rendered_forms_show_saved_values_not_the_startup_snapshot(
    saved_config, monkeypatch, render_name, provider, edit, expected, secret
):
    edit()
    values = _rendered_values(monkeypatch, render_name, provider)
    for label, value in expected.items():
        assert values.get(label) == value, f"{label} must show the saved value after refresh"
    if secret is not None:
        assert all(secret not in str(value) for value in values.values())


def test_ui_control_values_follow_out_of_band_edits(saved_config):
    _chat_ollama()
    _extract_ollama()
    _reranker_siliconflow()
    _vector_engine()

    # Without the reload the controls would keep showing the startup snapshot.
    assert configs_block.ui_control_values() == (
        "openai",
        True,
        "openai",
        True,
        "openai",
        "openai",
        "None",
        "Faiss",
    )

    configs_block.refresh_settings_snapshot()

    assert configs_block.ui_control_values() == (
        "ollama/local",
        False,
        "ollama/local",
        True,
        "openai",
        "openai",
        "siliconflow",
        "Milvus",
    )


def test_ui_load_handler_refreshes_model_controls(saved_config, monkeypatch):
    _chat_ollama()
    _extract_ollama()
    _reranker_siliconflow()
    _vector_engine()
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "false")
    monkeypatch.setattr(app.admin_settings, "enable_login", "false")
    monkeypatch.setattr(app, "huge_settings", HugeGraphConfig())
    monkeypatch.setattr(
        app,
        "prompt",
        SimpleNamespace(
            llm_settings=SimpleNamespace(language="EN"),
            ensure_yaml_file_exists=lambda: None,
            doc_input_text="",
            graph_schema="",
            extract_graph_prompt="",
            default_question="",
            answer_prompt="",
            keywords_extract_prompt="",
            custom_rerank_info="",
            gremlin_generate_prompt="",
        ),
    )
    ui = app.init_rag_ui()
    try:
        load = next(
            function
            for function in ui.fns.values()
            if getattr(function.fn, "__name__", None) == "refresh_ui_config_prompt"
        )
        result = load.fn()
        assert len(result) == len(load.outputs)
        assert result[-8:] == (
            "ollama/local",
            False,
            "ollama/local",
            True,
            "openai",
            "openai",
            "siliconflow",
            "Milvus",
        )
    finally:
        ui.close()
