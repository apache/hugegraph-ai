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


"""Exercise deployment configuration through the real settings sources and files."""

import os
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from hugegraph_llm import config
from hugegraph_llm.api import rag_api
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.config.models import base_config
from hugegraph_llm.demo.rag_demo import configs_block


@pytest.fixture
def saved_config(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.upper().startswith(
            (
                "OPENAI_",
                "OLLAMA_",
                "LITELLM_",
                "CHAT_",
                "EXTRACT_",
                "TEXT2GQL_",
                "EMBEDDING_",
                "RERANKER_",
                "COHERE_",
                "CO_API_",
                "HUGEGRAPH_LLM_",
            )
        ):
            monkeypatch.delenv(name)
    env = tmp_path / ".env"
    monkeypatch.setattr(base_config, "env_path", str(env))
    settings = LLMConfig()
    monkeypatch.setattr(config, "llm_settings", settings)
    monkeypatch.setattr(configs_block, "llm_settings", settings)
    monkeypatch.setattr(configs_block.gr, "Info", lambda *_: None)
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
    with TestClient(app) as client:
        yield settings, env, client


def save_chat(client, **overrides):
    payload = {
        "llm_type": "openai",
        "api_key": "synthetic-user-key",
        "api_base": "http://saved.invalid/v1",
        "language_model": "saved-model",
        "max_tokens": 100,
    }
    payload.update(overrides)
    return client.post("/config/llm", json=payload)
