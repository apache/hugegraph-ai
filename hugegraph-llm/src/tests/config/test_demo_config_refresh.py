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

import asyncio
import os
from unittest.mock import patch

import gradio as gr
import pytest
from dotenv import dotenv_values
from gradio.state_holder import SessionState

from hugegraph_llm.config import llm_settings
from hugegraph_llm.config.models import base_config
from hugegraph_llm.demo.rag_demo import configs_block

pytestmark = pytest.mark.unit


async def load_page(ui):
    state = SessionState(ui)
    values = {block_id: getattr(block, "value", None) for block_id, block in ui.blocks.items()}
    changed = set()
    for fn in list(ui.fns.values()):
        if fn.renderable is None and any(event == "load" for _, event in fn.targets):
            result = await ui.process_api(fn, [values[block._id] for block in fn.inputs], state=state)
            changed.update(result["changed_state_ids"])
            for block, value in zip(fn.outputs, result["data"]):
                values[block._id] = value.get("value") if isinstance(value, dict) else value
    for fn in list(ui.fns.values()):
        if fn.renderable is not None and any(
            event == "load" or (event == "change" and block_id in changed) for block_id, event in fn.targets
        ):
            await ui.process_api(fn, [values[block._id] for block in fn.inputs], state=state)
    return state


@pytest.mark.parametrize(
    "provider,reranker", [("openai", "cohere"), ("litellm", "siliconflow"), ("ollama/local", None)]
)
def test_page_load_reloads_provider_settings_and_renders_fields(tmp_path, monkeypatch, provider, reranker):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(base_config, "env_path", str(env_file))
    monkeypatch.setitem(llm_settings.model_config, "env_file", str(env_file))
    original = llm_settings.model_dump()

    try:
        with patch.dict(os.environ):
            llm_settings.chat_llm_type = "openai"
            llm_settings.extract_llm_type = "openai"
            llm_settings.text2gql_llm_type = "openai"
            llm_settings.embedding_type = "openai"
            llm_settings.reranker_type = "cohere"
            with gr.Blocks() as ui:
                configs_block.create_configs_block(ui)

            # Refresh twice without rebuilding Blocks, including unchanged provider types.
            for suffix in ("first", "second"):
                config = original | {
                    "chat_llm_type": provider,
                    "extract_llm_type": provider,
                    "text2gql_llm_type": provider,
                    "embedding_type": provider,
                    "reranker_type": reranker,
                    "reranker_model": f"reranker-{suffix}",
                    "reranker_api_key": f"reranker-key-{suffix}",
                }
                prefix = "ollama" if provider == "ollama/local" else provider
                for role in ("chat", "extract", "text2gql"):
                    config[f"{prefix}_{role}_language_model"] = f"{role}-{suffix}"
                config[f"{prefix}_embedding_model"] = f"embedding-{suffix}"
                env_file.write_text(
                    "".join(f"{key.upper()}={value if value is not None else ''}\n" for key, value in config.items())
                )

                state = asyncio.run(load_page(ui))

                assert llm_settings.chat_llm_type == provider
                assert llm_settings.extract_llm_type == provider
                assert llm_settings.text2gql_llm_type == provider
                assert llm_settings.embedding_type == provider
                assert llm_settings.reranker_type == reranker
                textboxes = [block for block in state.blocks_config.blocks.values() if isinstance(block, gr.Textbox)]
                for model in (f"chat-{suffix}", f"extract-{suffix}", f"text2gql-{suffix}", f"embedding-{suffix}"):
                    assert any(block.value == model for block in textboxes)
                if reranker:
                    assert any(block.value == f"reranker-{suffix}" for block in textboxes)
                    assert any(block.value == f"reranker-key-{suffix}" for block in textboxes)
    finally:
        configs_block._restore_config(llm_settings, original)


@pytest.fixture
def reload_demo(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(base_config, "env_path", str(env_file))
    monkeypatch.setattr(configs_block, "env_path", str(env_file))
    monkeypatch.setitem(llm_settings.model_config, "env_file", str(env_file))
    original = llm_settings.model_dump()
    try:
        with patch.dict(os.environ):
            for field in type(llm_settings).model_fields:
                os.environ.pop(field.upper(), None)
            env_file.write_text(
                "CHAT_LLM_TYPE=openai\nEXTRACT_LLM_TYPE=openai\nTEXT2GQL_LLM_TYPE=openai\n"
                "EMBEDDING_TYPE=openai\nRERANKER_TYPE=cohere\n"
                "OPENAI_CHAT_LANGUAGE_MODEL=old-chat\nOPENAI_EXTRACT_LANGUAGE_MODEL=old-extract\n"
                "OPENAI_TEXT2GQL_LANGUAGE_MODEL=old-text2gql\nOPENAI_EMBEDDING_MODEL=old-embedding\n"
                "RERANKER_MODEL=old-reranker\nRERANKER_API_KEY=old-key\n",
                encoding="utf-8",
            )
            llm_settings.__init__()
            with gr.Blocks() as ui:
                configs_block.create_configs_block(ui)
            yield ui, env_file
    finally:
        configs_block._restore_config(llm_settings, original)


@pytest.mark.parametrize(
    "invalid", ["CHAT_LLM_TYPE=ollama", "OPENAI_CHAT_TOKENS=not-an-integer", "OLLAMA_CHAT_PORT=bad-port"]
)
def test_invalid_reload_keeps_provider_forms_and_can_recover(reload_demo, invalid):
    ui, env_file = reload_demo
    original = llm_settings.model_dump()
    valid_text = env_file.read_text(encoding="utf-8")
    invalid_text = valid_text + invalid + "\n"
    env_file.write_text(invalid_text, encoding="utf-8")

    with patch.object(gr, "Warning") as warning:
        state = asyncio.run(load_page(ui))

    warning.assert_called_once()
    assert llm_settings.model_dump() == original
    assert env_file.read_text(encoding="utf-8") == invalid_text
    textboxes = [block.value for block in state.blocks_config.blocks.values() if isinstance(block, gr.Textbox)]
    for model in ("old-chat", "old-extract", "old-text2gql", "old-embedding", "old-reranker"):
        assert model in textboxes
    buttons = [
        block
        for block in state.blocks_config.blocks.values()
        if isinstance(block, gr.Button)
        and block.rendered_in is not None
        and block.rendered_in.fn.__name__ != "vector_engine_settings"
    ]
    assert len(buttons) == 5
    assert all(block.value.lower() == "apply configuration" for block in buttons)

    env_file.write_text(valid_text.replace("old-chat", "recovered-chat"), encoding="utf-8")
    state = asyncio.run(load_page(ui))
    assert llm_settings.openai_chat_language_model == "recovered-chat"
    assert any(
        isinstance(block, gr.Textbox) and block.value == "recovered-chat"
        for block in state.blocks_config.blocks.values()
    )


def test_reload_file_error_keeps_previous_settings(reload_demo):
    ui, env_file = reload_demo
    original = llm_settings.model_dump()
    env_file.write_text("OPENAI_CHAT_LANGUAGE_MODEL=new-chat\n", encoding="utf-8")

    with patch.object(base_config, "set_key", side_effect=OSError("Cannot write configuration")):
        with patch.object(gr, "Warning") as warning:
            state = asyncio.run(load_page(ui))

    warning.assert_called_once()
    assert llm_settings.model_dump() == original
    assert any(
        isinstance(block, gr.Textbox) and block.value == "old-chat" for block in state.blocks_config.blocks.values()
    )


@pytest.mark.parametrize("field", ["openai_chat_language_model", "reranker_api_key", "reranker_type"])
@pytest.mark.parametrize("from_environment", [False, True])
def test_removed_key_does_not_restore_previous_file_value(reload_demo, monkeypatch, field, from_environment):
    ui, env_file = reload_demo
    env_key = field.upper()
    expected = type(llm_settings).model_fields[field].default
    if from_environment:
        expected = "siliconflow" if field == "reranker_type" else "from-process-environment"
        monkeypatch.setenv(env_key, expected)
    asyncio.run(load_page(ui))
    previous = getattr(llm_settings, field)
    assert previous != expected
    text = env_file.read_text(encoding="utf-8")
    env_file.write_text(
        "".join(line for line in text.splitlines(keepends=True) if not line.startswith(f"{env_key}=")),
        encoding="utf-8",
    )

    state = asyncio.run(load_page(ui))

    assert getattr(llm_settings, field) == expected
    assert dotenv_values(env_file)[env_key] == (expected or "")
    assert not any(
        isinstance(block, gr.Textbox) and block.value == previous for block in state.blocks_config.blocks.values()
    )
    if from_environment:
        assert os.environ[env_key] == expected
    else:
        assert env_key not in os.environ
