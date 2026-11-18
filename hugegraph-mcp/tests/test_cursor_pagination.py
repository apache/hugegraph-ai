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

from hugegraph_mcp.tools import query_graph_data


def test_byte_trimmed_page_tail_is_buffered_without_losing_items(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_MAX_RESULT_BYTES", "720")

    class _FakeManager:
        def get_vertex_by_page(self, *, label, page=None, limit=100, properties=None):
            if page is None:
                return (
                    [
                        {"id": 1, "label": label, "properties": {"bio": "a" * 80}},
                        {"id": "2", "label": label, "properties": {"bio": "b" * 80}},
                        {"id": 3, "label": label, "properties": {"bio": "c" * 80}},
                    ],
                    "backend-p2",
                )
            return ([{"id": 4, "label": label, "properties": {"bio": "d" * 80}}], None)

    monkeypatch.setattr(query_graph_data, "_graph_manager", lambda: _FakeManager())

    collected = []
    res1 = query_graph_data.query_graph_data(
        target="vertex", operation="page", label="person", limit=10, fields=["bio"]
    )
    assert res1["ok"] is True
    assert res1["data"]["truncated"] is True
    assert res1["data"]["has_more"] is True
    collected.extend(res1["data"]["items"])

    cursor = res1["data"]["next_cursor"]
    while cursor:
        nxt = query_graph_data.query_graph_data(
            target="vertex", operation="page", label="person", limit=10, fields=["bio"], cursor=cursor
        )
        assert nxt["ok"] is True
        collected.extend(nxt["data"]["items"])
        cursor = nxt["data"]["next_cursor"]

    assert [item["id"] for item in collected] == [1, "2", 3, 4]
    assert isinstance(collected[0]["id"], int)
    assert isinstance(collected[1]["id"], str)


def test_cursor_rejects_query_mismatch_and_target_change(monkeypatch):
    class _FakeManager:
        def get_vertex_by_page(self, *, label, page=None, limit=100, properties=None):
            return ([{"id": 1, "label": label, "properties": {"name": "a"}}], "p2")

    monkeypatch.setattr(query_graph_data, "_graph_manager", lambda: _FakeManager())
    res = query_graph_data.query_graph_data(target="vertex", operation="page", label="person", limit=1, fields=["name"])
    cursor = res["data"]["next_cursor"]

    mismatch = query_graph_data.query_graph_data(
        target="vertex", operation="page", label="software", limit=1, fields=["name"], cursor=cursor
    )
    assert mismatch["ok"] is False
    assert mismatch["error"]["details"]["reason_code"] == "CURSOR_QUERY_MISMATCH"
