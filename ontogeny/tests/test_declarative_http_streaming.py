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

"""Declarative HTTP responses enforce the byte cap while reading the stream."""

from __future__ import annotations

import gzip
import json

import httpx
import pytest
from test_declarative_http_references import function, invoke

from ontogeny.errors import SandboxError

LIMIT = 256 * 1024


class CountingStream(httpx.AsyncByteStream):
    def __init__(self, chunks, *, fail=False):
        self.chunks = chunks
        self.read_chunks = 0
        self.closed = False
        self.fail = fail

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read_chunks += 1
            yield chunk
        if self.fail:
            raise httpx.ReadError("interrupted response")

    async def aclose(self):
        self.closed = True


async def run_response(client, stream, *, status=200, content_type="text/plain; charset=utf-8", headers=None):
    _, sc = client
    response = httpx.Response(status, headers={"content-type": content_type, **(headers or {})}, stream=stream)
    return await invoke(sc, function("https://hooks.test/result"), {}, [], response=response)


async def test_oversized_response_stops_reading_and_closes_early(client):
    stream = CountingStream([b"x" * 32768] * 100)
    with pytest.raises(SandboxError, match=r"response.*limit"):
        await run_response(client, stream)
    assert stream.closed
    assert stream.read_chunks == 9  # stop on the first chunk beyond 256 KiB
    assert stream.read_chunks < len(stream.chunks)


async def test_exact_byte_boundary_is_accepted_including_split_multibyte_text(client):
    text = "€" * (LIMIT // 3) + "x"
    payload = text.encode()
    assert len(payload) == LIMIT
    stream = CountingStream([payload[:1], payload[1:65537], payload[65537:]])
    result = await run_response(client, stream)
    assert result == {"status": 200, "text": text}
    assert stream.closed


async def test_limit_counts_bytes_rather_than_unicode_characters(client):
    text = "€" * (LIMIT // 3 + 1)
    assert len(text) < LIMIT < len(text.encode())
    stream = CountingStream([text.encode()])
    with pytest.raises(SandboxError, match=r"response.*limit"):
        await run_response(client, stream)
    assert stream.closed


@pytest.mark.parametrize("status", [200, 422, 503])
async def test_json_and_http_error_status_are_preserved(client, status):
    payload = json.dumps({"message": "保留 JSON", "status": status}, ensure_ascii=False).encode()
    stream = CountingStream([payload[:14], payload[14:15], payload[15:]])
    result = await run_response(client, stream, status=status, content_type="application/json")
    assert result == {"status": status, "json": {"message": "保留 JSON", "status": status}}
    assert stream.closed


async def test_text_uses_declared_response_charset(client):
    text = "café"
    stream = CountingStream([text.encode("iso-8859-1")])
    assert await run_response(client, stream, content_type="text/plain; charset=iso-8859-1") == {
        "status": 200,
        "text": text,
    }
    assert stream.closed


async def test_invalid_utf8_keeps_httpx_replacement_semantics(client):
    stream = CountingStream([b"invalid: \xff"])
    assert await run_response(client, stream) == {"status": 200, "text": "invalid: �"}
    assert stream.closed


async def test_compressed_response_cap_counts_decoded_bytes(client):
    stream = CountingStream([gzip.compress(b"x" * (LIMIT + 1))])
    with pytest.raises(SandboxError, match=r"response.*limit"):
        await run_response(client, stream, headers={"content-encoding": "gzip"})
    assert stream.closed


async def test_read_failure_closes_response_stream(client):
    stream = CountingStream([b"part"], fail=True)
    with pytest.raises(httpx.ReadError, match="interrupted response"):
        await run_response(client, stream)
    assert stream.closed
