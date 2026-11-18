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

"""P1 unit tests for bounded graph traversal, task observability, and graph discovery."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from pyhugegraph.utils.exceptions import ResponseTooLargeError

from hugegraph_mcp import server
from hugegraph_mcp.envelope import ErrorType
from hugegraph_mcp.runtime import reset_current_actor, set_current_actor
from hugegraph_mcp.stores.base import Actor


class _FakeSessionGuard:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @contextmanager
    def request_guard(self, **kwargs: Any):
        self.calls.append(kwargs)
        yield


class _FakeTraverser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.raise_exc: Exception | None = None

    def k_neighbor(self, source_id, max_depth, **kwargs):
        self.calls.append(("k_neighbor", (source_id, max_depth), kwargs))
        if self.raise_exc:
            raise self.raise_exc
        return {"vertices": ["1:marko", "1:vadas"]}

    def k_out(self, source_id, max_depth, **kwargs):
        self.calls.append(("k_out", (source_id, max_depth), kwargs))
        return {"vertices": [2, 3]}

    def shortest_path(self, source_id, target_id, max_depth, **kwargs):
        self.calls.append(("shortest_path", (source_id, target_id, max_depth), kwargs))
        return {"path": ["1:marko", "1:josh", "1:ripple"]}

    def paths(self, source_id, target_id, max_depth, **kwargs):
        self.calls.append(("paths", (source_id, target_id, max_depth), kwargs))
        return {"paths": [{"objects": ["a", "b"]}, {"objects": ["a", "c", "b"]}]}


class _FakeTaskManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def get_task(self, task_id, *, with_result=True, **kwargs):
        self.calls.append(("get_task", (task_id,), {"with_result": with_result, **kwargs}))
        return {
            "id": task_id,
            "task_type": "gremlin",
            "task_name": "rebuild",
            "task_status": "failed",
            "task_progress": 50,
            "task_result": "HUGE_SECRET_OR_LARGE_PAYLOAD",
        }

    def list_tasks(self, status=None, limit=None, *, ids=None, page=None):
        self.calls.append(("list_tasks", (), {"status": status, "limit": limit, "ids": ids, "page": page}))
        return {
            "tasks": [
                {"id": 10, "task_status": "running", "task_progress": 25},
                {"id": 11, "task_status": "success", "task_progress": 100},
            ],
            "page": "cursor-2",
        }


class _FakeGraphsManager:
    def __init__(self, payload: str = '{"graphs": ["hugegraph", "huge_test", "other_g"]}') -> None:
        self._payload = payload

    def get_all_graphs(self) -> str:
        return self._payload


class _FakeClient:
    def __init__(self, *, traverser=None, task=None, graphs=None) -> None:
        self.session = _FakeSessionGuard()
        self._traverser = traverser or _FakeTraverser()
        self._task = task or _FakeTaskManager()
        self._graphs = graphs or _FakeGraphsManager()

    def traverser(self):
        return self._traverser

    def task(self):
        return self._task

    def graphs(self):
        return self._graphs


def test_traverse_graph_rejects_invalid_inputs_before_network(monkeypatch):
    called = False

    def fail_build(_cfg):
        nonlocal called
        called = True
        return _FakeClient()

    monkeypatch.setattr("hugegraph_mcp.tools.traverse_graph._build_client", fail_build)

    assert server.traverse_graph_tool(operation="rings", source_id="a")["error"]["type"] == "VALIDATION_ERROR"
    assert server.traverse_graph_tool(operation="neighbors", source_id=True)["error"]["type"] == "VALIDATION_ERROR"
    assert server.traverse_graph_tool(operation="shortest_path", source_id="a")["error"]["type"] == "VALIDATION_ERROR"
    assert (
        server.traverse_graph_tool(operation="neighbors", source_id="a", target_id="b")["error"]["type"]
        == "VALIDATION_ERROR"
    )
    assert (
        server.traverse_graph_tool(operation="k_out", source_id="a", max_depth=4)["error"]["type"] == "VALIDATION_ERROR"
    )
    assert (
        server.traverse_graph_tool(operation="k_out", source_id="a", max_degree=65)["error"]["type"]
        == "VALIDATION_ERROR"
    )
    assert (
        server.traverse_graph_tool(operation="k_out", source_id="a", capacity=5001)["error"]["type"]
        == "VALIDATION_ERROR"
    )
    assert (
        server.traverse_graph_tool(operation="shortest_path", source_id="a", target_id="b", limit=2)["error"]["type"]
        == "VALIDATION_ERROR"
    )
    # neighbors admission budget: 1 + 16 + 256 = 273 > capacity=200
    adm_err = server.traverse_graph_tool(
        operation="neighbors",
        source_id="a",
        max_depth=2,
        max_degree=16,
        capacity=200,
    )
    assert adm_err["error"]["type"] == "VALIDATION_ERROR"
    assert adm_err["error"]["details"]["reason"] == "admission_budget_exceeded"
    assert called is False


def test_traverse_graph_executes_four_modes_and_preserves_vid_types(monkeypatch):
    traverser = _FakeTraverser()
    client = _FakeClient(traverser=traverser)
    monkeypatch.setattr("hugegraph_mcp.tools.traverse_graph._build_client", lambda _cfg: client)

    res_n = server.traverse_graph_tool(operation="neighbors", source_id="1:marko", max_depth=2, max_degree=8)
    assert res_n["ok"] is True
    assert res_n["data"]["vertices"] == ["1:marko", "1:vadas"]
    assert traverser.calls[-1][1][0] == "1:marko"

    res_k = server.traverse_graph_tool(operation="k_out", source_id=42, max_depth=1, limit=5)
    assert res_k["ok"] is True
    assert res_k["data"]["vertices"] == [2, 3]
    assert traverser.calls[-1][1][0] == 42
    assert isinstance(traverser.calls[-1][1][0], int)

    res_sp = server.traverse_graph_tool(operation="shortest_path", source_id="1:marko", target_id="1:ripple")
    assert res_sp["ok"] is True
    assert res_sp["data"]["found"] is True
    assert traverser.calls[-1][2]["with_vertex"] is False
    assert traverser.calls[-1][2]["with_edge"] is False

    res_p = server.traverse_graph_tool(operation="paths", source_id="a", target_id="b", limit=2)
    assert res_p["ok"] is True
    assert res_p["data"]["paths"] == [["a", "b"], ["a", "c", "b"]]
    assert len(client.session.calls) == 4

    traverser.raise_exc = ResponseTooLargeError(1024, 2048)
    err = server.traverse_graph_tool(operation="neighbors", source_id="a", max_depth=1, max_degree=4)
    assert err["ok"] is False
    assert err["error"]["type"] == ErrorType.VALIDATION_ERROR.value
    assert err["error"]["details"]["reason"] == "response_bytes_exceeded"

    traverser.raise_exc = None
    traverser.k_neighbor = lambda *_a, **_k: "unexpected-string"
    bad_shape = server.traverse_graph_tool(operation="neighbors", source_id="a", max_depth=1, max_degree=4)
    assert bad_shape["ok"] is False
    assert bad_shape["error"]["type"] == ErrorType.SERVER_ERROR.value
    assert bad_shape["error"]["details"]["reason"] == "invalid_response_shape"


def test_task_tools_and_list_graphs_respect_admin_gate_and_sanitize(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "false")
    assert server.get_task_status_tool(1)["error"]["type"] == ErrorType.FEATURE_DISABLED.value
    assert server.list_tasks_tool()["error"]["type"] == ErrorType.FEATURE_DISABLED.value
    assert server.list_graphs_tool()["error"]["type"] == ErrorType.FEATURE_DISABLED.value

    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    client = _FakeClient()
    monkeypatch.setattr("hugegraph_mcp.tools.task_tools._build_client", lambda _cfg: client)
    monkeypatch.setattr("hugegraph_mcp.tools.graph_discovery._build_client", lambda _cfg: client)

    # HTTP actor without mcp:admin fails closed
    no_admin = Actor(issuer="bearer", tenant="t1", subject="u1", scopes=frozenset({"mcp:read"}))
    tok = set_current_actor(no_admin)
    try:
        assert server.get_task_status_tool(1)["error"]["type"] == ErrorType.AUTHORIZATION_FAILED.value
    finally:
        reset_current_actor(tok)

    # STDIO operator succeeds; failed task still returns ok=True with real status and no task_result
    task_res = server.get_task_status_tool(99)
    assert task_res["ok"] is True
    assert task_res["data"]["status"] == "failed"
    assert "task_result" not in task_res["data"]
    assert client._task.calls[0][2]["with_result"] is False

    list_res = server.list_tasks_tool(status="RUNNING", limit=10)
    assert list_res["ok"] is True
    assert list_res["data"]["count"] == 2
    assert list_res["data"]["page"] == "cursor-2"

    graphs_res = server.list_graphs_tool(prefix="huge", limit=1)
    assert graphs_res["ok"] is True
    assert graphs_res["data"]["graphs"] == ["hugegraph"]
    assert graphs_res["data"]["total_matched"] == 2
    assert graphs_res["data"]["truncated"] is True

    bad_client = _FakeClient(graphs=_FakeGraphsManager('{"graphs": [123]}'))
    monkeypatch.setattr("hugegraph_mcp.tools.graph_discovery._build_client", lambda _cfg: bad_client)
    assert server.list_graphs_tool()["error"]["type"] == ErrorType.SERVER_ERROR.value
