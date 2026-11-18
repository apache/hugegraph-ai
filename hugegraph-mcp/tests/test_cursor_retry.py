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

import threading

import pytest

from hugegraph_mcp.cursor_store import CursorError, InMemoryCursorStore
from hugegraph_mcp.tools import query_graph_data


def test_transient_backend_failure_preserves_cursor_for_retry(monkeypatch):
    attempts = {"p2": 0}

    class _FlakyManager:
        def get_vertex_by_page(self, *, label, page=None, limit=100, properties=None):
            if page is None:
                return ([{"id": "v1", "label": label, "properties": {"name": "a"}}], "p2")
            attempts["p2"] += 1
            if attempts["p2"] == 1:
                raise TimeoutError("transient backend timeout")
            return ([{"id": "v2", "label": label, "properties": {"name": "b"}}], None)

    monkeypatch.setattr(query_graph_data, "_graph_manager", lambda: _FlakyManager())

    first = query_graph_data.query_graph_data(
        target="vertex", operation="page", label="person", limit=1, fields=["name"]
    )
    assert first["ok"] is True
    cursor = first["data"]["next_cursor"]
    assert cursor

    failed = query_graph_data.query_graph_data(
        target="vertex", operation="page", label="person", limit=1, fields=["name"], cursor=cursor
    )
    assert failed["ok"] is False
    assert failed["error"]["retryable"] is True

    retried = query_graph_data.query_graph_data(
        target="vertex", operation="page", label="person", limit=1, fields=["name"], cursor=cursor
    )
    assert retried["ok"] is True
    assert [item["id"] for item in retried["data"]["items"]] == ["v2"]
    assert retried["data"]["next_cursor"] is None

    reused = query_graph_data.query_graph_data(
        target="vertex", operation="page", label="person", limit=1, fields=["name"], cursor=cursor
    )
    assert reused["ok"] is False
    assert reused["error"]["details"]["reason_code"] == "CURSOR_EXPIRED_OR_UNKNOWN"


def test_concurrent_readers_cannot_multiply_same_cursor(monkeypatch):
    entered = threading.Event()
    proceed = threading.Event()
    backend_calls = {"p2": 0}

    class _BlockingManager:
        def get_vertex_by_page(self, *, label, page=None, limit=100, properties=None):
            if page is None:
                return ([{"id": "v1", "label": label, "properties": {"name": "a"}}], "p2")
            backend_calls["p2"] += 1
            entered.set()
            proceed.wait(timeout=5.0)
            return ([{"id": "v2", "label": label, "properties": {"name": "b"}}], "p3")

    monkeypatch.setattr(query_graph_data, "_graph_manager", lambda: _BlockingManager())

    first = query_graph_data.query_graph_data(
        target="vertex", operation="page", label="person", limit=1, fields=["name"]
    )
    cursor = first["data"]["next_cursor"]
    assert cursor

    results: dict[str, dict] = {}

    def _run_reader(name: str) -> None:
        results[name] = query_graph_data.query_graph_data(
            target="vertex", operation="page", label="person", limit=1, fields=["name"], cursor=cursor
        )

    t1 = threading.Thread(target=_run_reader, args=("first",))
    t1.start()
    assert entered.wait(timeout=5.0)

    t2 = threading.Thread(target=_run_reader, args=("second",))
    t2.start()
    t2.join(timeout=5.0)

    proceed.set()
    t1.join(timeout=5.0)

    assert backend_calls["p2"] == 1
    assert results["second"]["ok"] is False
    assert results["second"]["error"]["details"]["reason_code"] == "CURSOR_IN_FLIGHT"
    assert results["second"]["error"]["retryable"] is True
    assert results["first"]["ok"] is True
    assert results["first"]["data"]["next_cursor"] is not None
    assert results["first"]["data"]["next_cursor"] != cursor


def test_cursor_store_acquire_release_and_complete_lifecycle():
    store = InMemoryCursorStore(ttl_seconds=60.0, max_entries=4)
    target = ("default", "DEFAULT", "hugegraph", "http://localhost:8080")
    cursor = store.issue(
        actor_key="actor:1",
        target=target,
        query_hash="q1",
        fields=("name",),
        continuation_scope="backend",
        buffered_items=[],
        backend_next_page="p2",
    )

    rec = store.acquire(cursor, actor_key="actor:1", target=target, query_hash="q1", fields=("name",))
    assert rec.backend_next_page == "p2"

    with pytest.raises(CursorError) as exc_info:
        store.acquire(cursor, actor_key="actor:1", target=target, query_hash="q1", fields=("name",))
    assert exc_info.value.reason_code == "CURSOR_IN_FLIGHT"

    store.release(cursor)
    rec_retry = store.acquire(cursor, actor_key="actor:1", target=target, query_hash="q1", fields=("name",))
    assert rec_retry.cursor_id == cursor

    next_cursor = store.complete(
        cursor,
        actor_key="actor:1",
        target=target,
        query_hash="q1",
        fields=("name",),
        continuation_scope="backend",
        buffered_items=[],
        backend_next_page="p3",
    )
    assert next_cursor != cursor

    with pytest.raises(CursorError) as gone_info:
        store.acquire(cursor, actor_key="actor:1", target=target, query_hash="q1", fields=("name",))
    assert gone_info.value.reason_code == "CURSOR_EXPIRED_OR_UNKNOWN"
