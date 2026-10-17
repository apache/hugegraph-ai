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
from unittest.mock import Mock

import pytest

from hugegraph_llm.models.llms import init_llm

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("provider", "class_name"), [("openai", "OpenAIClient"), ("litellm", "LiteLLMClient")])
def test_chat_factory_omits_limit_only_when_requested(monkeypatch, provider, class_name):
    constructor = Mock()
    monkeypatch.setattr(init_llm, class_name, constructor)
    settings = SimpleNamespace(
        chat_llm_type=provider,
        **{
            f"{provider}_chat_api_key": "test-key",
            f"{provider}_chat_api_base": "http://model.invalid/v1",
            f"{provider}_chat_language_model": "test-model",
            f"{provider}_chat_tokens": 37,
        },
    )
    init_llm.get_chat_llm(settings)
    assert constructor.call_args.kwargs["max_tokens"] == 37
    assert constructor.call_args.kwargs["raise_on_truncation"] is False
    init_llm.get_chat_llm(settings, limit_output=True)
    assert constructor.call_args.kwargs["max_tokens"] == 37
    init_llm.get_chat_llm(settings, limit_output=False)
    assert constructor.call_args.kwargs == {
        "api_key": "test-key",
        "api_base": "http://model.invalid/v1",
        "model_name": "test-model",
        "max_tokens": None,
        "raise_on_truncation": False,
    }
    for limit_output in (False, True):
        init_llm.get_chat_llm(settings, limit_output=limit_output, raise_on_truncation=True)
        assert constructor.call_args.kwargs["max_tokens"] == (37 if limit_output else None)
        assert constructor.call_args.kwargs["raise_on_truncation"] is True


@pytest.mark.parametrize("raise_on_truncation", [False, True])
def test_chat_factory_passes_ollama_policy_without_output_options(monkeypatch, raise_on_truncation):
    constructor = Mock()
    monkeypatch.setattr(init_llm, "OllamaClient", constructor)
    settings = SimpleNamespace(
        chat_llm_type="ollama/local",
        ollama_chat_language_model="test-model",
        ollama_chat_host="localhost",
        ollama_chat_port=11434,
    )
    init_llm.get_chat_llm(settings, limit_output=False, raise_on_truncation=raise_on_truncation)
    constructor.assert_called_once_with(
        model="test-model", host="localhost", port=11434, raise_on_truncation=raise_on_truncation
    )
