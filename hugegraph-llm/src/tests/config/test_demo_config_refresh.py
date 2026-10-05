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
from gradio.state_holder import SessionState

from hugegraph_llm.config import llm_settings
from hugegraph_llm.config.models import base_config
from hugegraph_llm.demo.rag_demo import configs_block

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "provider,reranker", [("openai", "cohere"), ("litellm", "siliconflow"), ("ollama/local", None)]
)
def test_page_load_reloads_provider_settings_and_renders_fields(tmp_path, monkeypatch, provider, reranker):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(base_config, "env_path", str(env_file))
    monkeypatch.setitem(llm_settings.model_config, "env_file", str(env_file))
    original = llm_settings.model_dump()

    async def load_page(ui):
        state = SessionState(ui)
        values = {block_id: getattr(block, "value", None) for block_id, block in ui.blocks.items()}
        for fn in ui.fns.values():
            if fn.renderable is None and any(event == "load" for _, event in fn.targets):
                result = await ui.process_api(fn, [values[block._id] for block in fn.inputs], state=state)
                for block, value in zip(fn.outputs, result["data"]):
                    values[block._id] = value.get("value") if isinstance(value, dict) else value
        for fn in ui.fns.values():
            if fn.renderable is not None:
                if fn.renderable.fn.__name__ != "vector_engine_settings":
                    revision = fn.inputs[1]
                    assert (revision._id, "change") in fn.targets
                    assert all(event != "load" for _, event in fn.targets)
                await ui.process_api(fn, [values[block._id] for block in fn.inputs], state=state)
        return state

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
