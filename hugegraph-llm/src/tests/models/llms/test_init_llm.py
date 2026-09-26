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

from types import SimpleNamespace
from unittest.mock import patch

from hugegraph_llm.models.llms.init_llm import get_extract_llm


def _openai_config(**overrides):
    config = {
        "chat_llm_type": "openai",
        "extract_llm_type": "openai",
        "openai_chat_api_key": "chat-key",
        "openai_chat_api_base": "https://chat.example/v1",
        "openai_chat_language_model": "chat-model",
        "openai_chat_tokens": 4096,
        "openai_extract_api_key": None,
        "openai_extract_api_base": "https://api.openai.com/v1",
        "openai_extract_language_model": "gpt-4.1-mini",
        "openai_extract_tokens": 256,
    }
    config.update(overrides)
    return SimpleNamespace(**config)


def _litellm_config(**overrides):
    config = {
        "chat_llm_type": "litellm",
        "extract_llm_type": "litellm",
        "litellm_chat_api_key": "chat-key",
        "litellm_chat_api_base": "https://chat.example/v1",
        "litellm_chat_language_model": "chat-model",
        "litellm_chat_tokens": 4096,
        "litellm_extract_api_key": None,
        "litellm_extract_api_base": None,
        "litellm_extract_language_model": "openai/gpt-4.1-mini",
        "litellm_extract_tokens": 256,
    }
    config.update(overrides)
    return SimpleNamespace(**config)


def _ollama_config(**overrides):
    config = {
        "chat_llm_type": "ollama/local",
        "extract_llm_type": "ollama/local",
        "ollama_chat_host": "chat-host",
        "ollama_chat_port": 11435,
        "ollama_chat_language_model": "chat-model",
        "ollama_extract_host": "127.0.0.1",
        "ollama_extract_port": 11434,
        "ollama_extract_language_model": None,
    }
    config.update(overrides)
    return SimpleNamespace(**config)


def test_get_extract_llm_falls_back_to_openai_chat_config_when_extract_key_is_missing():
    config = _openai_config()

    with patch("hugegraph_llm.models.llms.init_llm.OpenAIClient") as openai_client:
        get_extract_llm(config)

    openai_client.assert_called_once_with(
        api_key="chat-key",
        api_base="https://chat.example/v1",
        model_name="chat-model",
        max_tokens=4096,
    )


def test_get_extract_llm_falls_back_to_openai_chat_config_when_only_generic_key_exists():
    config = _openai_config(
        openai_chat_api_key="shared-key",
        openai_extract_api_key="shared-key",
    )

    with patch("hugegraph_llm.models.llms.init_llm.OpenAIClient") as openai_client:
        get_extract_llm(config)

    openai_client.assert_called_once_with(
        api_key="shared-key",
        api_base="https://chat.example/v1",
        model_name="chat-model",
        max_tokens=4096,
    )


def test_get_extract_llm_prefers_explicit_openai_extract_config():
    config = _openai_config(
        openai_extract_api_key="extract-key",
        openai_extract_api_base="https://extract.example/v1",
        openai_extract_language_model="extract-model",
        openai_extract_tokens=8192,
    )

    with patch("hugegraph_llm.models.llms.init_llm.OpenAIClient") as openai_client:
        get_extract_llm(config)

    openai_client.assert_called_once_with(
        api_key="extract-key",
        api_base="https://extract.example/v1",
        model_name="extract-model",
        max_tokens=8192,
    )


def test_get_extract_llm_falls_back_to_litellm_chat_config_when_extract_key_is_missing():
    config = _litellm_config()

    with patch("hugegraph_llm.models.llms.init_llm.LiteLLMClient") as litellm_client:
        get_extract_llm(config)

    litellm_client.assert_called_once_with(
        api_key="chat-key",
        api_base="https://chat.example/v1",
        model_name="chat-model",
        max_tokens=4096,
    )


def test_get_extract_llm_falls_back_to_litellm_chat_config_without_proxy_key():
    config = _litellm_config(litellm_chat_api_key=None)

    with patch("hugegraph_llm.models.llms.init_llm.LiteLLMClient") as litellm_client:
        get_extract_llm(config)

    litellm_client.assert_called_once_with(
        api_key=None,
        api_base="https://chat.example/v1",
        model_name="chat-model",
        max_tokens=4096,
    )


def test_get_extract_llm_prefers_explicit_litellm_extract_config():
    config = _litellm_config(
        litellm_extract_api_key="extract-key",
        litellm_extract_api_base="https://extract.example/v1",
        litellm_extract_language_model="extract-model",
        litellm_extract_tokens=8192,
    )

    with patch("hugegraph_llm.models.llms.init_llm.LiteLLMClient") as litellm_client:
        get_extract_llm(config)

    litellm_client.assert_called_once_with(
        api_key="extract-key",
        api_base="https://extract.example/v1",
        model_name="extract-model",
        max_tokens=8192,
    )


def test_get_extract_llm_falls_back_to_ollama_chat_config_when_extract_model_is_missing():
    config = _ollama_config()

    with patch("hugegraph_llm.models.llms.init_llm.OllamaClient") as ollama_client:
        get_extract_llm(config)

    ollama_client.assert_called_once_with(model="chat-model", host="chat-host", port=11435)


def test_get_extract_llm_prefers_explicit_ollama_extract_config():
    config = _ollama_config(
        ollama_extract_host="extract-host",
        ollama_extract_port=11436,
        ollama_extract_language_model="extract-model",
    )

    with patch("hugegraph_llm.models.llms.init_llm.OllamaClient") as ollama_client:
        get_extract_llm(config)

    ollama_client.assert_called_once_with(model="extract-model", host="extract-host", port=11436)
