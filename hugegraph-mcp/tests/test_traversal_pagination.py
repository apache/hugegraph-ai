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

from hugegraph_mcp.tools import traverse_graph


def test_traverse_snapshot_pagination_does_not_reinvoke_backend(monkeypatch):
    calls = []

    class _FakeTraverser:
        def k_neighbor(self, source_id, max_depth, **kwargs):
            calls.append((source_id, max_depth))
            return {"vertices": [f"v-{i}" for i in range(5)]}

    class _FakeClient:
        def traverser(self):
            return _FakeTraverser()

    monkeypatch.setattr(traverse_graph, "_build_client", lambda cfg: _FakeClient())

    page1 = traverse_graph.traverse_graph(operation="neighbors", source_id="v-0", max_depth=1, limit=10, page_size=2)
    assert page1["ok"] is True
    assert page1["data"]["vertices"] == ["v-0", "v-1"]
    assert page1["data"]["continuation_scope"] == "snapshot"
    assert page1["data"]["has_more"] is True

    page2 = traverse_graph.traverse_graph(
        operation="neighbors",
        source_id="v-0",
        max_depth=1,
        limit=10,
        page_size=2,
        cursor=page1["data"]["next_cursor"],
    )
    assert page2["ok"] is True
    assert page2["data"]["vertices"] == ["v-2", "v-3"]
    assert page2["data"]["has_more"] is True

    page3 = traverse_graph.traverse_graph(
        operation="neighbors",
        source_id="v-0",
        max_depth=1,
        limit=10,
        page_size=2,
        cursor=page2["data"]["next_cursor"],
    )
    assert page3["ok"] is True
    assert page3["data"]["vertices"] == ["v-4"]
    assert page3["data"]["has_more"] is False
    assert page3["data"]["capture_exhausted"] is True
    assert len(calls) == 1
