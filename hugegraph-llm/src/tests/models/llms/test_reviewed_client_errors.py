# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Reviewed clients reject provider failures while ordinary callers stay compatible."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import ollama
import pytest
from openai import AuthenticationError, BadRequestError

from hugegraph_llm.models.llms import ollama as ollama_module
from hugegraph_llm.models.llms import openai as openai_module
from hugegraph_llm.models.llms.base import LLMOutputTruncatedError
from tests.models.llms.test_output_limits import async_chunks, invoke

pytestmark = pytest.mark.contract
MODES = ["generate", "agenerate", "generate_streaming", "agenerate_streaming"]


@pytest.fixture
def sdk_calls(monkeypatch):
    sync_call, async_call = Mock(), AsyncMock()
    sync_sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=sync_call)))
    async_sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=async_call)))
    monkeypatch.setattr(openai_module, "OpenAI", lambda **_: sync_sdk)
    monkeypatch.setattr(openai_module, "AsyncOpenAI", lambda **_: async_sdk)
    monkeypatch.setattr(ollama_module.ollama, "Client", lambda **_: SimpleNamespace(chat=sync_call))
    monkeypatch.setattr(ollama_module.ollama, "AsyncClient", lambda **_: SimpleNamespace(chat=async_call))
    return sync_call, async_call


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("error_type", [BadRequestError, AuthenticationError])
@pytest.mark.parametrize("reviewed", [False, True])
def test_openai_nonretryable_error_policy(sdk_calls, mode, error_type, reviewed):
    sync_call, async_call = sdk_calls
    error = error_type(
        "provider rejected request",
        response=httpx.Response(400, request=httpx.Request("POST", "https://model.invalid")),
        body=None,
    )
    sdk_call = async_call if mode.startswith("a") else sync_call
    sdk_call.side_effect = error
    client = openai_module.OpenAIClient(**({"raise_on_truncation": True} if reviewed else {}))

    if reviewed:
        with pytest.raises(error_type) as caught:
            invoke(client, mode)
        assert caught.value is error
    else:
        expected = "Error: provider rejected request"
        if error_type is AuthenticationError:
            provider = "" if mode == "generate_streaming" else "OpenAI "
            expected = f"Error: The provided {provider}API key is invalid"
        assert invoke(client, mode) == expected
    sdk_call.assert_called_once()  # Bad credentials and bad requests must not be retried.


@pytest.mark.parametrize("mode", ["generate_streaming", "agenerate_streaming"])
@pytest.mark.parametrize("error_type", [BadRequestError, AuthenticationError])
def test_openai_stream_consumption_preserves_provider_exception(sdk_calls, mode, error_type):
    sync_call, async_call = sdk_calls
    error = error_type(
        "provider rejected request",
        response=httpx.Response(400, request=httpx.Request("POST", "https://model.invalid")),
        body=None,
    )
    prefix = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="prefix"), finish_reason=None)])

    def stream():
        yield prefix
        raise error

    async def astream():
        for chunk in stream():
            yield chunk

    sync_call.return_value = stream()
    async_call.return_value = astream()
    client = openai_module.OpenAIClient(raise_on_truncation=True)
    seen = []
    with pytest.raises(error_type) as caught:
        invoke(client, mode, callback=seen.append)
    assert caught.value is error
    assert seen == ["prefix"]
    (async_call if mode.startswith("a") else sync_call).assert_called_once()


def configure_ollama(sdk_calls, mode, done_reason):
    sync_call, async_call = sdk_calls
    response = ollama.ChatResponse(
        model="test-model",
        message={"role": "assistant", "content": '{"decision":"pass","issues":[]}'},
        done=True,
        done_reason=done_reason,
        prompt_eval_count=10,
        eval_count=10,
    )
    if "streaming" in mode:
        prefix = ollama.ChatResponse(model="test-model", message={"role": "assistant", "content": "prefix"})
        sync_call.return_value = iter([prefix, response])
        async_call.return_value = async_chunks([prefix, response])
    else:
        sync_call.return_value = response
        async_call.return_value = response


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("reviewed", [False, True])
def test_ollama_truncation_policy_and_unchanged_request(sdk_calls, mode, reviewed):
    configure_ollama(sdk_calls, mode, "length")
    client = ollama_module.OllamaClient(model="test-model", **({"raise_on_truncation": True} if reviewed else {}))
    seen = []
    if reviewed:
        with pytest.raises(LLMOutputTruncatedError, match=r"\(done_reason=length\)") as caught:
            invoke(client, mode, callback=seen.append)
        assert caught.value.reason == "done_reason=length"
        assert seen == (["prefix"] if "streaming" in mode else [])
    else:
        expected = '{"decision":"pass","issues":[]}'
        assert invoke(client, mode, callback=seen.append) == ("prefix" + expected if "streaming" in mode else expected)
    sdk_call = sdk_calls[1] if mode.startswith("a") else sdk_calls[0]
    sdk_call.assert_called_once()
    assert set(sdk_call.call_args.kwargs) == (
        {"model", "messages", "stream"} if "streaming" in mode else {"model", "messages"}
    )


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("done_reason", [None, "stop"])
def test_ollama_reviewed_client_accepts_untruncated_output(sdk_calls, mode, done_reason):
    configure_ollama(sdk_calls, mode, done_reason)
    client = ollama_module.OllamaClient(model="test-model", raise_on_truncation=True)
    expected = '{"decision":"pass","issues":[]}'
    assert invoke(client, mode) == ("prefix" + expected if "streaming" in mode else expected)


@pytest.mark.parametrize("mode", ["generate_streaming", "agenerate_streaming"])
def test_ollama_detects_truncation_in_empty_terminal_message(sdk_calls, mode):
    terminal = {"done": True, "done_reason": "length", "message": None}
    sdk_calls[0].return_value = iter([terminal])
    sdk_calls[1].return_value = async_chunks([terminal])
    with pytest.raises(LLMOutputTruncatedError, match="done_reason=length"):
        invoke(ollama_module.OllamaClient(model="test-model", raise_on_truncation=True), mode)
