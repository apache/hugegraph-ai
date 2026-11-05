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
import json

import httpx
import pytest
from hugegraph_llm_sdk.providers.openai import OpenAIClient as SDKOpenAIClient

from hugegraph_llm.models.llms.openai import OpenAIClient

pytestmark = pytest.mark.contract


@pytest.mark.parametrize("mode", ["sync", "async", "stream", "async_stream"])
@pytest.mark.parametrize("temperature", [None, 0.4])
def test_openai_compatible_temperature_on_actual_http_body(mode, temperature):
    requests = []

    def endpoint(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("stream"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    'data: {"id":"test","object":"chat.completion.chunk","model":"test",'
                    '"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
                    'data: [DONE]\n\n'
                ),
            )
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "model": "test",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            },
        )

    client = OpenAIClient(api_key="synthetic", api_base="https://example.invalid/v1", temperature=temperature)
    client.client._client = httpx.Client(transport=httpx.MockTransport(endpoint))
    client.aclient._client = httpx.AsyncClient(transport=httpx.MockTransport(endpoint))

    async def async_result():
        if mode == "async":
            return await client.agenerate(prompt="hello")
        return "".join([part async for part in client.agenerate_streaming(prompt="hello")])

    try:
        if mode == "sync":
            result = client.generate(prompt="hello")
        elif mode == "stream":
            result = "".join(client.generate_streaming(prompt="hello"))
        else:
            result = asyncio.run(async_result())
        assert result == "ok"
        assert len(requests) == 1
        if temperature is None:
            assert "temperature" not in requests[0]
        else:
            assert requests[0]["temperature"] == temperature
    finally:
        client.client.close()
        asyncio.run(client.aclient.close())


def test_standalone_sdk_temperature_default_remains_unchanged():
    client = SDKOpenAIClient(api_key="synthetic", api_base="https://example.invalid/v1")
    assert client.temperature == 0.01
    client.client.close()
    asyncio.run(client.aclient.close())
