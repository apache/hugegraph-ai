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

import httpx
import pytest
from ontogeny_ext_hugegraph import HugeGraphClient

from ontogeny.errors import StoreError


async def test_standalone_graphspace_listing_is_used_instead_of_admin_listing():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/graphspaces":
            return httpx.Response(400, text="standalone mode")
        return httpx.Response(200, json={"graphs": ["hugegraph"]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HugeGraphClient("http://hg.test", "hugegraph", http=http)
        assert await client.dialect() == "1.7"
        assert await client.dialect() == "1.7"
        assert calls == ["/graphspaces/DEFAULT/graphs"]


@pytest.mark.parametrize("missing_status", [404, 405])
async def test_legacy_requires_a_successful_legacy_graph_listing(missing_status):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.startswith("/graphspaces/"):
            return httpx.Response(missing_status)
        return httpx.Response(200, json={"graphs": ["hugegraph"]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HugeGraphClient("http://hg.test", "hugegraph", http=http)
        assert await client.dialect() == "1.5"
        assert calls == ["/graphspaces/DEFAULT/graphs", "/graphs"]


@pytest.mark.parametrize("status", [400, 401, 403, 500, 503])
async def test_probe_error_never_falls_back_or_caches_a_dialect(status):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(status, text="probe failed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HugeGraphClient("http://hg.test", "hugegraph", http=http)
        with pytest.raises(StoreError, match=str(status)):
            await client.dialect()
        assert calls == ["/graphspaces/DEFAULT/graphs"]
        assert client._dialect is None
        assert client.auth_rejected is (status in (401, 403))


@pytest.mark.parametrize("legacy_status", [401, 403, 404, 500])
async def test_legacy_probe_failure_is_an_error(legacy_status):
    def handler(request):
        if request.url.path.startswith("/graphspaces/"):
            return httpx.Response(404)
        return httpx.Response(legacy_status, text="probe failed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HugeGraphClient("http://hg.test", "hugegraph", http=http)
        with pytest.raises(StoreError, match=str(legacy_status)):
            await client.dialect()
        assert client._dialect is None


async def test_network_error_is_reported_and_next_probe_can_retry():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, json={"graphs": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HugeGraphClient("http://hg.test", "hugegraph", http=http)
        with pytest.raises(StoreError, match="ConnectError"):
            await client.dialect()
        assert client._dialect is None
        assert await client.dialect() == "1.7"


@pytest.mark.parametrize("body", [{}, {"graphs": "not a list"}, ["hugegraph"]])
async def test_invalid_graph_listing_is_not_accepted(body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as http:
        client = HugeGraphClient("http://hg.test", "hugegraph", http=http)
        with pytest.raises(StoreError, match="invalid graph list"):
            await client.dialect()
        assert client._dialect is None
