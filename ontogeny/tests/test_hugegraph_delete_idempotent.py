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


@pytest.mark.parametrize("status", [200, 204, 404])
async def test_delete_accepts_success_and_not_found(status):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status))) as http:
        client = HugeGraphClient("http://hg.test", "hugegraph", api="1.7", http=http)
        client._label_ids["product"] = 1
        await client.delete_vertex("product", "missing")


async def test_delete_accepts_hugegraph_18_missing_vertex_response():
    body = {
        "exception": "class java.lang.IllegalArgumentException",
        "message": "No such vertex with id: '1:missing', org.apache.hugegraph.exception.NotFoundException: Vertex",
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(400, json=body))) as http:
        client = HugeGraphClient("http://hg.test", "hugegraph", api="1.7", http=http)
        client._label_ids["product"] = 1
        await client.delete_vertex("product", "missing")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"message": "Invalid vertex id"}),
        httpx.Response(400, json={"message": "Cannot delete: No such vertex with id: '1:x'"}),
        httpx.Response(400, json={"message": {"detail": "No such vertex with id:"}}),
        httpx.Response(400, text="No such vertex with id: '1:x'"),
        httpx.Response(500, text="backend failure"),
    ],
)
async def test_delete_does_not_hide_other_failures(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as http:
        client = HugeGraphClient("http://hg.test", "hugegraph", api="1.7", http=http)
        client._label_ids["product"] = 1
        with pytest.raises(StoreError, match="failed"):
            await client.delete_vertex("product", "missing")
