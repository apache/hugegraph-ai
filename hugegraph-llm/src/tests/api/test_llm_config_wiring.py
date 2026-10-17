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

"""Exercise the production route and callback together, replacing external I/O only."""

from unittest.mock import Mock

import pytest
import requests
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from hugegraph_llm.api.rag_api import rag_http_api
from hugegraph_llm.config import llm_settings
from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.demo.rag_demo import configs_block

pytestmark = pytest.mark.contract
ROLES = ("chat", "extract", "text2gql")
PROVIDERS = ("openai", "litellm", "ollama/local")


@pytest.fixture
def config_io(monkeypatch):
    # Preserve every field the real callback can update, with distinct role
    # tokens to detect accidental replacement when the optional field is absent.
    for role_index, role in enumerate(ROLES):
        monkeypatch.setattr(llm_settings, f"{role}_llm_type", PROVIDERS[role_index])
        for provider in ("openai", "litellm"):
            for suffix, value in {
                "api_key": f"old-{role}-key",
                "api_base": f"http://old-{role}.invalid/v1",
                "language_model": f"old-{role}-model",
                "tokens": (role_index + 1) * 100,
            }.items():
                monkeypatch.setattr(llm_settings, f"{provider}_{role}_{suffix}", value)
        for suffix, value in {
            "host": f"old-{role}.invalid",
            "port": 11000 + role_index,
            "language_model": f"old-{role}-model",
        }.items():
            monkeypatch.setattr(llm_settings, f"ollama_{role}_{suffix}", value)
    persisted = []
    persist = Mock(side_effect=lambda: persisted.append(llm_settings.model_dump()))
    monkeypatch.setattr(LLMConfig, "update_env", lambda _self: persist())
    monkeypatch.setattr(configs_block.gr, "Info", Mock())
    http = Mock(return_value=Mock(status_code=200, text="ok"))
    monkeypatch.setattr(configs_block.requests, "post", http)
    monkeypatch.setattr(configs_block.requests, "get", http)
    generate = Mock(return_value="ok")
    monkeypatch.setattr(configs_block.LiteLLMClient, "generate", generate)
    return {"http": http, "generate": generate, "persist": persist, "persisted": persisted}


@pytest.fixture
def client():
    router = APIRouter()
    # This is exactly the callback registered by demo/rag_demo/app.py, without
    # an adapter that could hide a missing role argument at the call boundary.
    rag_http_api(router, *(Mock() for _ in range(3)), configs_block.apply_llm_config, *(Mock() for _ in range(3)))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def payload(provider, *, tokens=True):
    result = {
        "llm_type": provider,
        "api_key": "new-key",
        "api_base": "http://new-model.invalid/v1",
        "language_model": "new-model",
        "host": "new-ollama.invalid",
        "port": "12000",
    }
    if tokens:
        result["max_tokens"] = "777"
    return result


def assert_model_fields(config, provider, role):
    prefix = "ollama" if provider == "ollama/local" else provider
    assert config[f"{role}_llm_type"] == provider
    assert config[f"{prefix}_{role}_language_model"] == "new-model"
    if provider == "ollama/local":
        assert config[f"ollama_{role}_host"] == "new-ollama.invalid"
        assert config[f"ollama_{role}_port"] == 12000
    else:
        assert config[f"{provider}_{role}_api_key"] == "new-key"
        assert config[f"{provider}_{role}_api_base"] == "http://new-model.invalid/v1"


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("tokens", [True, False])
def test_real_callback_updates_all_roles_once_and_preserves_omitted_tokens(client, config_io, provider, tokens):
    before = llm_settings.model_dump()
    response = client.post("/config/llm", json=payload(provider, tokens=tokens))

    assert response.status_code == 201
    assert response.json() == {"message": "Connection successful. Configured finished."}
    current = llm_settings.model_dump()
    for role in ROLES:
        assert_model_fields(current, provider, role)
        for token_provider in ("openai", "litellm"):
            key = f"{token_provider}_{role}_tokens"
            expected = 777 if tokens and token_provider == provider else before[key]
            assert current[key] == expected
    probe = config_io["generate" if provider == "litellm" else "http"]
    probe.assert_called_once()
    config_io["http" if provider == "litellm" else "generate"].assert_not_called()
    config_io["persist"].assert_called_once()
    assert config_io["persisted"] == [current]


@pytest.mark.parametrize("provider", ["openai", "ollama/local"])
def test_failed_http_probe_rolls_back_all_roles_without_persisting(client, config_io, provider):
    before = llm_settings.model_dump()
    config_io["http"].return_value = Mock(status_code=503, text="unavailable")

    response = client.post("/config/llm", json=payload(provider))

    assert response.status_code == 503
    assert llm_settings.model_dump() == before
    config_io["http"].assert_called_once()
    config_io["persist"].assert_not_called()


@pytest.mark.parametrize("provider", PROVIDERS)
def test_probe_exception_rolls_back_all_roles_without_persisting(client, config_io, provider):
    before = llm_settings.model_dump()
    if provider == "litellm":
        config_io["generate"].side_effect = RuntimeError("model unavailable")
    else:
        config_io["http"].side_effect = requests.exceptions.ConnectionError("model unavailable")

    response = client.post("/config/llm", json=payload(provider))

    assert response.status_code == (500 if provider == "litellm" else 400)
    assert llm_settings.model_dump() == before
    config_io["generate" if provider == "litellm" else "http"].assert_called_once()
    config_io["persist"].assert_not_called()


@pytest.mark.parametrize("provider", ["openai", "litellm"])
def test_invalid_token_conversion_does_not_probe_or_persist(client, config_io, provider):
    before = llm_settings.model_dump()
    body = payload(provider)
    body["max_tokens"] = "invalid"

    response = client.post("/config/llm", json=body)

    assert response.status_code == 500
    assert llm_settings.model_dump() == before
    for name in ("http", "generate", "persist"):
        config_io[name].assert_not_called()


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("role", ROLES)
def test_ui_callback_changes_only_selected_role(config_io, monkeypatch, provider, role):
    monkeypatch.setattr(llm_settings, f"{role}_llm_type", provider)
    before = llm_settings.model_dump()
    request = payload(provider)
    arg1 = request["host"] if provider == "ollama/local" else request["api_key"]
    arg2 = request["port"] if provider == "ollama/local" else request["api_base"]

    result = configs_block.apply_llm_config(role, arg1, arg2, request["language_model"], request["max_tokens"])

    assert result == 200
    current = llm_settings.model_dump()
    assert_model_fields(current, provider, role)
    prefixes = tuple(f"{p}_{role}_" for p in ("openai", "ollama", "litellm"))
    assert {k: v for k, v in current.items() if not k.startswith(prefixes)} == {
        k: v for k, v in before.items() if not k.startswith(prefixes)
    }
    config_io["generate" if provider == "litellm" else "http"].assert_called_once()
    config_io["persist"].assert_called_once()
