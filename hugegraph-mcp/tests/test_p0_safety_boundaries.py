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

"""P0 safety boundary tests: streaming response cap, deadline, retries, and actor admin gate."""

from __future__ import annotations

import time
from typing import Any

import pytest
import requests
from pyhugegraph.utils.exceptions import ResponseTooLargeError
from pyhugegraph.utils.huge_config import HGraphConfig
from pyhugegraph.utils.huge_requests import _REQUEST_RETRIES, HGraphSession

from hugegraph_mcp import server
from hugegraph_mcp.envelope import ErrorType
from hugegraph_mcp.error_mapping import classify_hugegraph_exception
from hugegraph_mcp.runtime import reset_current_actor, set_current_actor
from hugegraph_mcp.stores.base import Actor


class _FakeStreamResponse:
    def __init__(
        self,
        chunks: list[bytes],
        *,
        headers: dict[str, str] | None = None,
        status_code: int = 200,
        chunk_delay_s: float = 0.0,
    ) -> None:
        self._chunks = chunks
        self.headers = headers or {}
        self.status_code = status_code
        self._chunk_delay_s = chunk_delay_s
        self.closed = False
        self._content = b""
        self._content_consumed = False

    def iter_content(self, chunk_size: int = 16384):
        for chunk in self._chunks:
            if self._chunk_delay_s:
                time.sleep(self._chunk_delay_s)
            yield chunk

    def json(self) -> Any:
        import json

        return json.loads(self._content.decode("utf-8"))

    @property
    def text(self) -> str:
        return self._content.decode("utf-8")

    def close(self) -> None:
        self.closed = True


class _FakeSession:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def mount(self, prefix: str, adapter: Any) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> _FakeStreamResponse:
        self.calls.append({"url": url, "retries": _REQUEST_RETRIES.get(), **kwargs})
        return self._response


def _make_hg_session(fake_resp: _FakeStreamResponse) -> tuple[HGraphSession, _FakeSession]:
    cfg = HGraphConfig(
        url="http://127.0.0.1:18080",
        username="admin",
        password="admin",
        graph_name="hugegraph",
        graphspace="DEFAULT",
        timeout=(1.0, 5.0),
    )
    fake_http = _FakeSession(fake_resp)
    return HGraphSession(cfg, session=fake_http), fake_http  # type: ignore[arg-type]


def test_streaming_cap_rejects_oversized_content_length():
    resp = _FakeStreamResponse([b'{"ok": true}'], headers={"Content-Length": "2048"})
    sess, _ = _make_hg_session(resp)

    with (
        pytest.raises(ResponseTooLargeError) as exc_info,
        sess.request_guard(max_response_bytes=1024, retries=False),
    ):
        sess.request("/graphs/hugegraph", method="GET", validator=lambda r, **_kw: r.json())

    assert exc_info.value.max_bytes == 1024
    assert exc_info.value.actual_bytes == 2048
    assert resp.closed is True


def test_streaming_cap_aborts_chunked_response_without_content_length():
    resp = _FakeStreamResponse([b"a" * 600, b"b" * 600], headers={})
    sess, fake_http = _make_hg_session(resp)

    with (
        pytest.raises(ResponseTooLargeError) as exc_info,
        sess.request_guard(max_response_bytes=1000, retries=False),
    ):
        sess.request("/graphs/hugegraph", method="GET", validator=lambda r, **_kw: r.json())

    assert exc_info.value.max_bytes == 1000
    assert resp.closed is True
    assert fake_http.calls[0]["stream"] is True
    assert fake_http.calls[0]["retries"] is False


def test_streaming_cap_allows_within_budget_and_enforces_deadline():
    ok_resp = _FakeStreamResponse([b'{"status":', b'"ok"}'], headers={})
    sess_ok, _ = _make_hg_session(ok_resp)
    with sess_ok.request_guard(max_response_bytes=1024, deadline_seconds=5.0, retries=False):
        data = sess_ok.request("/graphs/hugegraph", method="GET", validator=lambda r, **_kw: r.json())
    assert data == {"status": "ok"}
    assert ok_resp.closed is True

    # Caller passing stream=False cannot bypass max_response_bytes
    forced_resp = _FakeStreamResponse([b"0123456789abcdef"], headers={})
    sess_forced, fake_http_forced = _make_hg_session(forced_resp)
    with (
        pytest.raises(ResponseTooLargeError),
        sess_forced.request_guard(max_response_bytes=8, deadline_seconds=5.0),
    ):
        sess_forced.request("/graphs/hugegraph", method="GET", validator=lambda r, **_kw: r.json(), stream=False)
    assert fake_http_forced.calls[0]["stream"] is True
    assert fake_http_forced.calls[0]["allow_redirects"] is False

    # Deadline-only guard (without max_response_bytes) still streams and enforces chunk deadline
    slow_resp = _FakeStreamResponse([b"x" * 10, b"y" * 10], chunk_delay_s=0.05)
    sess_slow, _ = _make_hg_session(slow_resp)
    with pytest.raises(requests.exceptions.ReadTimeout), sess_slow.request_guard(deadline_seconds=0.03):
        sess_slow.request("/graphs/hugegraph", method="GET", validator=lambda r, **_kw: r.json())
    assert slow_resp.closed is True


def test_pyhugegraph_client_exposes_session_property():
    from pyhugegraph.client import PyHugeClient

    client = PyHugeClient("http://127.0.0.1:8080", "hugegraph", "u", "p", graphspace="DEFAULT")
    assert client.session is client._session
    assert hasattr(client.session, "request_guard")


def test_error_mapping_classifies_byte_cap_timeout_and_connection():
    byte_cls = classify_hugegraph_exception(ResponseTooLargeError(1024, 2048))
    assert byte_cls.error_type is ErrorType.VALIDATION_ERROR
    assert byte_cls.reason == "response_bytes_exceeded"
    assert byte_cls.retryable is False

    timeout_cls = classify_hugegraph_exception(requests.exceptions.ReadTimeout("timed out"))
    assert timeout_cls.error_type is ErrorType.TIMEOUT
    assert timeout_cls.retryable is True

    conn_cls = classify_hugegraph_exception(requests.exceptions.ConnectionError("refused"))
    assert conn_cls.error_type is ErrorType.CONNECTION_FAILED
    assert conn_cls.retryable is True

    wrapped_timeout = requests.exceptions.ConnectionError(TimeoutError("read timed out"))
    wrapped_cls = classify_hugegraph_exception(wrapped_timeout)
    assert wrapped_cls.error_type is ErrorType.TIMEOUT
    assert wrapped_cls.retryable is True


def test_admin_gate_enforces_http_actor_scopes(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")

    # STDIO default actor passes
    assert server._admin_gate("list_tasks_tool") is None

    # HTTP actor without mcp:admin fails closed
    no_admin = Actor(issuer="bearer", tenant="t1", subject="u1", scopes=frozenset({"mcp:read", "mcp:write"}))
    tok = set_current_actor(no_admin)
    try:
        err = server._admin_gate("list_tasks_tool")
        assert err is not None
        assert err["error"]["type"] == ErrorType.AUTHORIZATION_FAILED.value
    finally:
        reset_current_actor(tok)

    # HTTP actor with mcp:admin passes admin read, but needs mcp:write for admin write
    admin_read = Actor(issuer="bearer", tenant="t1", subject="admin1", scopes=frozenset({"mcp:read", "mcp:admin"}))
    tok = set_current_actor(admin_read)
    try:
        assert server._admin_gate("list_tasks_tool", requires_write=False) is None
        err_w = server._admin_gate("execute_gremlin_write_tool", requires_write=True)
        assert err_w is not None
        assert err_w["error"]["type"] == ErrorType.AUTHORIZATION_FAILED.value
    finally:
        reset_current_actor(tok)

    # HTTP actor with mcp:admin + mcp:write passes admin write
    admin_write = Actor(
        issuer="bearer",
        tenant="t1",
        subject="admin1",
        scopes=frozenset({"mcp:read", "mcp:write", "mcp:admin"}),
    )
    tok = set_current_actor(admin_write)
    try:
        assert server._admin_gate("execute_gremlin_write_tool", requires_write=True) is None
    finally:
        reset_current_actor(tok)
