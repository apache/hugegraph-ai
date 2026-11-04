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

"""Exercise LiteLLM diagnostics below the real client and configuration helpers."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from litellm.exceptions import APIError, BudgetExceededError, RateLimitError

from hugegraph_llm.models.llms import litellm as litellm_module

pytestmark = pytest.mark.contract
MODES = ("generate", "agenerate", "generate_streaming", "agenerate_streaming")
ROLES = ("chat", "extract", "text2gql")
PRIVATE_KEY = "synthetic-private-litellm-key"
PRIVATE_URL = "https://user:synthetic-private-password@service.invalid/v1?token=synthetic-private-query"
PRIVATE_RESPONSE = "synthetic-private-provider-response"
MODEL = "openai/synthetic-model"


@pytest.fixture
def captured_logs(caplog, tmp_path):
    logger = litellm_module.log
    path = tmp_path / "litellm.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(caplog.handler)
    logger.addHandler(handler)
    try:
        with caplog.at_level(logging.DEBUG, logger=logger.name):
            yield caplog, path
    finally:
        logger.removeHandler(caplog.handler)
        logger.removeHandler(handler)
        handler.close()


def assert_private_values_absent(captured_logs, *other_output):
    captured, path = captured_logs
    output = "\n".join((captured.text, path.read_text(encoding="utf-8"), *other_output))
    for value in (PRIVATE_KEY, PRIVATE_URL, "synthetic-private-password", "synthetic-private-query", PRIVATE_RESPONSE):
        assert value not in output


def provider_error(error_type):
    message = f"Provider echoed {PRIVATE_KEY} at {PRIVATE_URL}: {PRIVATE_RESPONSE}"
    if error_type is BudgetExceededError:
        return error_type(current_cost=2.0, max_budget=1.0, message=message)
    fields = {"message": message, "llm_provider": "openai", "model": MODEL}
    if error_type is APIError:
        fields["status_code"] = 502
    return error_type(**fields)


def invoke(client, mode, callback=None):
    if mode == "agenerate":
        return asyncio.run(client.agenerate(prompt="hello"))
    if mode == "agenerate_streaming":

        async def collect():
            return "".join(
                [part async for part in client.agenerate_streaming(prompt="hello", on_token_callback=callback)]
            )

        return asyncio.run(collect())
    if mode == "generate_streaming":
        return client.generate_streaming(prompt="hello", on_token_callback=callback)
    return client.generate(prompt="hello")


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("error_type", [APIError, RateLimitError, BudgetExceededError])
def test_litellm_failure_logs_category_preserves_exception_and_retry_contract(
    monkeypatch, captured_logs, mode, error_type
):
    error = provider_error(error_type)
    sdk_call = AsyncMock(side_effect=error) if mode.startswith("a") else Mock(side_effect=error)
    monkeypatch.setattr(litellm_module, "acompletion" if mode.startswith("a") else "completion", sdk_call)
    client = litellm_module.LiteLLMClient(api_key=PRIVATE_KEY, api_base=PRIVATE_URL, model_name=MODEL)

    with pytest.raises(error_type) as caught:
        invoke(client, mode)

    assert caught.value is error
    attempts = 1 if "streaming" in mode or error_type is BudgetExceededError else 2
    assert sdk_call.call_count == attempts
    for call in sdk_call.call_args_list:
        assert call.kwargs["api_key"] == PRIVATE_KEY
        assert call.kwargs["base_url"] == PRIVATE_URL
    assert error_type.__name__ in captured_logs[0].text
    assert_private_values_absent(captured_logs)


@pytest.mark.parametrize("mode", ["generate_streaming", "agenerate_streaming"])
def test_litellm_stream_consumption_error_keeps_prefix_and_original_exception(monkeypatch, captured_logs, mode):
    error = provider_error(APIError)
    prefix = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="prefix"), finish_reason=None)])

    def stream():
        yield prefix
        raise error

    async def astream():
        for chunk in stream():
            yield chunk

    sdk_call = AsyncMock(return_value=astream()) if mode.startswith("a") else Mock(return_value=stream())
    monkeypatch.setattr(litellm_module, "acompletion" if mode.startswith("a") else "completion", sdk_call)
    client = litellm_module.LiteLLMClient(api_key=PRIVATE_KEY, api_base=PRIVATE_URL, model_name=MODEL)
    seen = []
    with pytest.raises(APIError) as caught:
        invoke(client, mode, callback=seen.append)
    assert caught.value is error
    assert seen == [prefix]
    sdk_call.assert_called_once()
    assert_private_values_absent(captured_logs)


@pytest.mark.parametrize("mode", MODES)
def test_litellm_success_keeps_content_callbacks_and_transport_without_raw_chunk_logs(monkeypatch, captured_logs, mode):
    chunks = [
        SimpleNamespace(choices=[], provider_details=PRIVATE_RESPONSE),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"), finish_reason=None)]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=" world"), finish_reason="stop")]),
    ]
    response = SimpleNamespace(
        usage={"prompt_tokens": 1},
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello world"), finish_reason="stop")],
    )

    async def astream():
        for chunk in chunks:
            yield chunk

    if "streaming" in mode:
        response = astream() if mode.startswith("a") else iter(chunks)
    sdk_call = AsyncMock(return_value=response) if mode.startswith("a") else Mock(return_value=response)
    monkeypatch.setattr(litellm_module, "acompletion" if mode.startswith("a") else "completion", sdk_call)
    client = litellm_module.LiteLLMClient(api_key=PRIVATE_KEY, api_base=PRIVATE_URL, model_name=MODEL, max_tokens=37)
    seen = []
    assert invoke(client, mode, callback=seen.append) == "hello world"
    assert seen == (chunks[1:] if "streaming" in mode else [])
    expected = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.01,
        "max_tokens": 37,
        "api_key": PRIVATE_KEY,
        "base_url": PRIVATE_URL,
    }
    if "streaming" in mode:
        expected["stream"] = True
    sdk_call.assert_called_once_with(**expected)
    assert_private_values_absent(captured_logs)
