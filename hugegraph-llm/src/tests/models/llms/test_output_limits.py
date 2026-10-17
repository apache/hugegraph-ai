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

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from litellm.exceptions import APIError
from openai import APIConnectionError, OpenAI
from tenacity import wait_none

from hugegraph_llm.models.llms import litellm as litellm_module
from hugegraph_llm.models.llms import openai as openai_module
from hugegraph_llm.models.llms.base import LLMOutputTruncatedError

pytestmark = pytest.mark.contract


@pytest.fixture(params=["openai", "litellm"])
def client_factory(request, monkeypatch):
    """Replace only the SDK call boundary, keeping the real wrapper and retries."""
    sync_call, async_call = Mock(), AsyncMock()
    if request.param == "openai":
        monkeypatch.setattr(
            openai_module,
            "OpenAI",
            lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=sync_call))),
        )
        monkeypatch.setattr(
            openai_module,
            "AsyncOpenAI",
            lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=async_call))),
        )
        cls = openai_module.OpenAIClient
    else:
        monkeypatch.setattr(litellm_module, "completion", sync_call)
        monkeypatch.setattr(litellm_module, "acompletion", async_call)
        cls = litellm_module.LiteLLMClient
    return cls, sync_call, async_call


def completion(content="complete", finish_reason="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish_reason)],
        usage=None,
    )


def chunk(content=None, finish_reason=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish_reason)]
    )


async def async_chunks(chunks):
    for item in chunks:
        yield item


def configure_calls(sync_call, async_call, mode, *, content="complete", finish_reason="stop", prefix=""):
    if "streaming" in mode:
        chunks = [
            SimpleNamespace(choices=[]),
            chunk(prefix),
            chunk(content, finish_reason),
            SimpleNamespace(choices=[]),
        ]
        sync_call.return_value = iter(chunks)
        async_call.return_value = async_chunks(chunks)
    else:
        sync_call.return_value = completion(content, finish_reason)
        async_call.return_value = completion(content, finish_reason)


def invoke(client, mode, callback=None):
    kwargs = {"prompt": "user content must not enter truncation errors"}
    if "streaming" in mode:
        kwargs["on_token_callback"] = callback
    if mode == "agenerate":
        return asyncio.run(client.agenerate(**kwargs))
    if mode == "agenerate_streaming":

        async def collect():
            return "".join([token async for token in client.agenerate_streaming(**kwargs)])

        return asyncio.run(collect())
    result = getattr(client, mode)(**kwargs)
    return result if isinstance(result, str) else "".join(result)


@pytest.mark.parametrize("mode", ["generate", "agenerate", "generate_streaming", "agenerate_streaming"])
@pytest.mark.parametrize("limit", [None, 237])
def test_request_omits_none_and_preserves_explicit_token_limit(client_factory, mode, limit):
    cls, sync_call, async_call = client_factory
    client = cls(api_key="test-key", max_tokens=limit)
    configure_calls(sync_call, async_call, mode)

    assert invoke(client, mode) == "complete"

    sdk_call = async_call if mode.startswith("a") else sync_call
    sdk_call.assert_called_once()
    if limit is None:
        assert "max_tokens" not in sdk_call.call_args.kwargs
    else:
        assert sdk_call.call_args.kwargs["max_tokens"] == limit
    assert sdk_call.call_args.kwargs["messages"] == [
        {"role": "user", "content": "user content must not enter truncation errors"}
    ]


def test_omitted_constructor_limit_keeps_existing_default(client_factory):
    cls, sync_call, async_call = client_factory
    client = cls(api_key="test-key")
    configure_calls(sync_call, async_call, "generate")
    assert invoke(client, "generate") == "complete"
    expected = 8092 if cls is openai_module.OpenAIClient else 8192
    assert sync_call.call_args.kwargs["max_tokens"] == expected


@pytest.mark.parametrize("mode", ["generate", "agenerate"])
@pytest.mark.parametrize("limit", [None, 237])
@pytest.mark.parametrize(
    "content", [None, "", '{"decision":', '{"decision":"pass","issues":[]}', "private-model-content"]
)
def test_length_is_reported_before_content_is_returned_and_never_retried(client_factory, mode, limit, content):
    cls, sync_call, async_call = client_factory
    client = cls(api_key="private-api-key", max_tokens=limit, raise_on_truncation=True)
    configure_calls(sync_call, async_call, mode, content=content, finish_reason="length")

    with pytest.raises(LLMOutputTruncatedError) as error:
        invoke(client, mode)

    assert str(error.value) == "LLM output was truncated (finish_reason=length)."
    assert "private" not in str(error.value)
    (async_call if mode.startswith("a") else sync_call).assert_called_once()


@pytest.mark.parametrize("mode", ["generate_streaming", "agenerate_streaming"])
@pytest.mark.parametrize("limit", [None, 237])
@pytest.mark.parametrize("terminal_content", [None, "", '{"decision":"pass","issues":[]}'])
def test_streaming_checks_terminal_reason_before_delivering_terminal_chunk(
    client_factory, mode, limit, terminal_content
):
    cls, sync_call, async_call = client_factory
    client = cls(api_key="test-key", max_tokens=limit, raise_on_truncation=True)
    configure_calls(
        sync_call, async_call, mode, content=terminal_content, finish_reason="length", prefix="partial-prefix"
    )
    seen = []

    with pytest.raises(LLMOutputTruncatedError, match="finish_reason=length"):
        invoke(client, mode, callback=seen.append)

    # Previously delivered streaming content is preserved, but the length chunk is never delivered.
    assert len(seen) == 1
    if cls is openai_module.OpenAIClient:
        assert seen == ["partial-prefix"]
    else:
        assert seen[0].choices[0].delta.content == "partial-prefix"
    (async_call if mode.startswith("a") else sync_call).assert_called_once()


@pytest.mark.parametrize("mode", ["generate", "agenerate", "generate_streaming", "agenerate_streaming"])
@pytest.mark.parametrize("limit", [None, 237])
def test_default_truncation_policy_returns_content_even_without_a_token_cap(client_factory, mode, limit):
    cls, sync_call, async_call = client_factory
    client = cls(api_key="test-key", max_tokens=limit)
    configure_calls(sync_call, async_call, mode, content="partial", finish_reason="length", prefix="prefix-")
    seen = []

    expected = "prefix-partial" if "streaming" in mode else "partial"
    assert invoke(client, mode, callback=seen.append) == expected
    (async_call if mode.startswith("a") else sync_call).assert_called_once()
    if "streaming" in mode:
        delivered = seen if cls is openai_module.OpenAIClient else [part.choices[0].delta.content for part in seen]
        assert delivered == ["prefix-", "partial"]


@pytest.mark.parametrize("mode", ["generate_streaming", "agenerate_streaming"])
def test_stop_stream_preserves_content_and_callback_semantics(client_factory, mode):
    cls, sync_call, async_call = client_factory
    client = cls(api_key="test-key")
    configure_calls(sync_call, async_call, mode, content="-complete", finish_reason="stop", prefix="prefix")
    seen = []
    assert invoke(client, mode, callback=seen.append) == "prefix-complete"
    if cls is openai_module.OpenAIClient:
        assert seen == ["prefix", "-complete"]
    else:
        assert [part.choices[0].delta.content for part in seen] == ["prefix", "-complete"]


@pytest.mark.parametrize("mode", ["generate", "agenerate"])
def test_stop_accepts_complete_json_without_false_truncation(client_factory, mode):
    cls, sync_call, async_call = client_factory
    client = cls(api_key="test-key", max_tokens=None)
    text = '{"decision":"pass","issues":[]}'
    configure_calls(sync_call, async_call, mode, content=text)
    assert invoke(client, mode) == text


@pytest.mark.parametrize("mode", ["generate", "agenerate"])
def test_network_retry_remains_enabled(client_factory, mode, monkeypatch):
    cls, sync_call, async_call = client_factory
    client = cls(api_key="test-key", max_tokens=None)
    sdk_call = async_call if mode.startswith("a") else sync_call
    error = (
        APIConnectionError(request=httpx.Request("POST", "https://unit.test"))
        if cls is openai_module.OpenAIClient
        else APIError(status_code=500, message="upstream failed", llm_provider="openai", model="test-model")
    )
    sdk_call.side_effect = [error, completion()]
    monkeypatch.setattr(getattr(client, mode).retry, "wait", wait_none())
    assert invoke(client, mode) == "complete"
    assert sdk_call.call_count == 2


@pytest.mark.parametrize("limit", [None, 237])
def test_openai_sdk_serializes_optional_limit_as_an_absent_field(monkeypatch, limit):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "unit-completion",
                "object": "chat.completion",
                "created": 1,
                "model": "unit-model",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "complete"}, "finish_reason": "stop"}
                ],
            },
        )

    sdk = OpenAI(
        api_key="unit-key",
        base_url="https://unit.test",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    monkeypatch.setattr(openai_module, "OpenAI", lambda **_: sdk)
    monkeypatch.setattr(openai_module, "AsyncOpenAI", Mock())
    try:
        client = openai_module.OpenAIClient(max_tokens=limit)
        assert client.generate(prompt="hello") == "complete"
    finally:
        sdk.close()
    assert len(requests) == 1
    if limit is None:
        assert "max_tokens" not in requests[0]
    else:
        assert requests[0]["max_tokens"] == limit
