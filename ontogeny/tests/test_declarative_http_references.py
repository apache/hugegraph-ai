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
# specific language governing permissions and
# limitations under the License.

"""HTTP templates use the real ServiceContext deployment resolver."""

from __future__ import annotations

import httpx
import pytest
from test_declarative_functions import _fn

from ontogeny.core.models import Capability, FunctionStep, ParamDef
from ontogeny.errors import SandboxError


def function(url, *, steps=None, params=None, capabilities=None):
    return _fn(
        runtime="declarative",
        parameters=params or {"order_id": ParamDef(type="string")},
        steps=[*(steps or []), FunctionStep(id="send", kind="http", url=url)],
        capabilities=[Capability(**{"http": {"allow": ["hooks.test"]}}), *(capabilities or [])],
        returns_step="send",
    )


async def invoke(sc, fn, params, calls, *, response=None):
    def handler(request):
        calls.append(request)
        return response or httpx.Response(200, json={"ok": True})

    # Keep the ServiceContext-created runtime and its Settings.resolve_env_ref.
    # Replacing only the HTTP transport avoids bypassing the production wiring.
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        sc.functions.declarative._http = http
        async with sc.sessionmaker() as session:
            return await sc.functions.run(session, fn, params)


@pytest.mark.parametrize("conflicting_env", [False, True])
async def test_url_parameter_is_not_a_deployment_reference(client, monkeypatch, conflicting_env):
    _, sc = client
    monkeypatch.delenv("order_id", raising=False)
    if conflicting_env:
        monkeypatch.setitem(sc.settings.env, "order_id", "wrong-environment-value")
    calls = []
    await invoke(sc, function("https://hooks.test/orders/${order_id}"), {"order_id": "PO-42"}, calls)
    assert str(calls[0].url) == "https://hooks.test/orders/PO-42"


async def test_upper_snake_deployment_reference_and_parameter_can_share_one_url(client, monkeypatch):
    _, sc = client
    monkeypatch.setitem(sc.settings.env, "API_BASE", "https://hooks.test")
    monkeypatch.setitem(sc.settings.env, "order_id", "must-not-override-call")
    calls = []
    await invoke(sc, function("${API_BASE}/orders/${order_id}"), {"order_id": "PO-42"}, calls)
    assert str(calls[0].url) == "https://hooks.test/orders/PO-42"


async def test_prior_step_reference_is_left_for_template_interpolation(client, monkeypatch):
    _, sc = client
    monkeypatch.setitem(sc.settings.env, "lookup", "must-not-override-step")

    class Gateway:
        async def chat(self, messages):
            return {"content": "PO-42"}

    sc.functions.declarative.llm = Gateway()
    fn = function(
        "https://hooks.test/orders/${lookup}",
        steps=[FunctionStep(id="lookup", kind="llm", prompt="choose an order")],
        capabilities=[Capability(llm=True)],
    )
    calls = []
    await invoke(sc, fn, {}, calls)
    assert str(calls[0].url) == "https://hooks.test/orders/PO-42"


@pytest.mark.parametrize(
    "url_value, expected_error",
    [
        ("https://evil.test/orders", "not in the http allowlist"),
        ("${API_BASE}", "url still contains"),
    ],
)
async def test_rendered_url_still_passes_allowlist_and_reference_injection_guards(
    client, monkeypatch, url_value, expected_error
):
    _, sc = client
    monkeypatch.delenv("url", raising=False)
    monkeypatch.setitem(sc.settings.env, "API_BASE", "https://hooks.test")
    calls = []
    fn = function("${url}", params={"url": ParamDef(type="string")})
    with pytest.raises(SandboxError, match=expected_error):
        await invoke(sc, fn, {"url": url_value}, calls)
    assert calls == []


async def test_parameterized_request_does_not_follow_redirects_off_allowlist(client):
    _, sc = client
    calls = []
    result = await invoke(
        sc,
        function("https://hooks.test/orders/${order_id}"),
        {"order_id": "PO-42"},
        calls,
        response=httpx.Response(302, headers={"location": "https://evil.test/private"}),
    )
    assert result["status"] == 302
    assert [request.url.host for request in calls] == ["hooks.test"]
