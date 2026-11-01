# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Exercise resource calls through real requests preparation and response parsing."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from pyhugegraph.api.graph import GraphManager
from pyhugegraph.api.olap import OlapManager
from pyhugegraph.api.rest import RestManager
from pyhugegraph.api.task import TaskManager
from pyhugegraph.client import PyHugeClient
from pyhugegraph.utils.exceptions import (
    ResponseParseError,
    TaskCancelledError,
    TaskFailedError,
    TaskTimeoutError,
    UnsupportedOperationError,
)
from pyhugegraph.utils.huge_requests import HGraphSession

pytestmark = pytest.mark.contract

ALGORITHM_NAMES = (
    "count_vertex",
    "count_edge",
    "degree_centrality",
    "stress_centrality",
    "betweenness_centrality",
    "closeness_centrality",
    "eigenvector_centrality",
    "triangle_count",
    "cluster_coefficient",
    "lpa",
    "louvain",
    "weak_connected_component",
    "fusiform_similarity",
    "rings",
    "k_core",
    "page_rank",
    "subgraph_stat",
)


class RecordingHTTP(requests.Session):
    def __init__(self, responses=()):
        super().__init__()
        self.responses = list(responses)
        self.calls = []
        self.close_count = 0

    def send(self, request, **kwargs):
        self.calls.append((request, kwargs))
        body = self.responses.pop(0) if self.responses else {}
        response = requests.Response()
        response.status_code = 200
        response.request = request
        response._content = json.dumps(body).encode()
        response.headers["Content-Type"] = "application/json"
        return response

    def close(self):
        self.close_count += 1
        super().close()


def transport(responses=(), *, graphspace="DEFAULT", url="https://example.test/proxy"):
    http = RecordingHTTP(responses)
    cfg = SimpleNamespace(
        url=url,
        graph_name="g",
        graphspace=graphspace,
        gs_supported=graphspace is not None,
        username="admin",
        password="private-password",
        timeout=(0.5, 15),
    )
    return HGraphSession(cfg, session=http), http


def query(request):
    return parse_qs(urlsplit(request.url).query, keep_blank_values=True)


@pytest.mark.parametrize("name", ALGORITHM_NAMES)
def test_named_olap_submission_uses_native_job_protocol(name):
    session, http = transport([{"task_id": 42}])
    parameters = {"direction": "OUT", "nested": {"key": "value"}}
    receipt = getattr(OlapManager(session), name)(parameters)
    request = http.calls[0][0]
    assert receipt == {"task_id": 42}
    assert request.method == "POST"
    assert request.url == f"https://example.test/proxy/graphspaces/DEFAULT/graphs/g/jobs/algorithm/{name}"
    assert json.loads(request.body) == parameters


def test_custom_algorithm_names_are_not_blocked_by_client_catalog():
    session, http = transport([{"task_id": 0}])
    assert OlapManager(session).submit("custom_algorithm") == {"task_id": 0}
    assert json.loads(http.calls[0][0].body) == {}


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr("pyhugegraph.api.task.time.monotonic", clock.monotonic)
    monkeypatch.setattr("pyhugegraph.api.task.time.sleep", clock.sleep)
    return clock


def test_wait_loads_result_once_after_success(clock):
    session, http = transport(
        [
            {"id": 7, "task_status": "running"},
            {"id": 7, "task_status": "success"},
            {"id": 7, "task_status": "success", "task_result": '{"count": 3}'},
        ]
    )
    tasks = TaskManager(session)
    task = tasks.wait(7, timeout=5, poll_interval=0.2)
    assert tasks.result(task) == {"count": 3}
    assert [query(req)["with_result"] for req, _ in http.calls] == [["false"], ["false"], ["true"]]
    assert all(max(options["timeout"]) <= 5 for _, options in http.calls)


@pytest.mark.parametrize("status, error", [("failed", TaskFailedError), ("cancelled", TaskCancelledError)])
def test_wait_preserves_failure_context(clock, status, error):
    task = {"id": 8, "task_status": status, "task_result": "server reason"}
    session, _ = transport([task, task])
    with pytest.raises(error) as exc:
        TaskManager(session).wait(8)
    assert exc.value.task == task
    assert exc.value.task_id == 8


def test_wait_timeout_never_cancels_or_deletes_remote_job(clock):
    session, http = transport([{"id": 7, "task_status": "hanging"}] * 3)
    with pytest.raises(TaskTimeoutError) as exc:
        TaskManager(session).wait(7, timeout=0.3, poll_interval=0.1)
    assert exc.value.task_id == 7
    assert all(request.method == "GET" for request, _ in http.calls)


def test_wait_rejects_malformed_task_state(clock):
    session, _ = transport([{}])
    with pytest.raises(ResponseParseError, match="task_status"):
        TaskManager(session).wait(7)


def test_run_returns_decoded_result(clock):
    session, http = transport(
        [
            {"task_id": 5},
            {"id": 5, "task_status": "success"},
            {"id": 5, "task_status": "success", "task_result": "3"},
        ]
    )
    assert OlapManager(session).run("count_vertex") == 3
    assert len(http.calls) == 3


@pytest.mark.parametrize("timeout, interval", [(0, 1), (1, 0), (float("inf"), 1), (1, float("nan"))])
def test_invalid_wait_options_do_not_submit_remote_jobs(timeout, interval):
    session, http = transport()
    with pytest.raises(ValueError):
        OlapManager(session).run("count_vertex", timeout=timeout, poll_interval=interval)
    assert http.calls == []


def test_complete_query_parameters_preserve_false_zero_and_empty_page():
    session, http = transport()
    rest = RestManager(session)
    rest.kout.get(source="123", max_depth=3, nearest=False, count_only=True, capacity=-1, limit=0)
    assert query(http.calls[0][0]) == {
        "source": ['"123"'],
        "max_depth": ["3"],
        "nearest": ["false"],
        "count_only": ["true"],
        "capacity": ["-1"],
        "limit": ["0"],
    }
    rest.task.list(ids=[0, 2], limit=0)
    assert query(http.calls[1][0]) == {"ids": ["0", "2"], "limit": ["0"]}
    rest.vertices.scan(start="a/b", end="z?x=1", page="", page_limit=20)
    assert query(http.calls[2][0])["page"] == [""]


def test_raw_nested_body_and_graph_batch_are_not_truncated():
    session, http = transport()
    rest = RestManager(session)
    body = {"source": "alice", "steps": {"direction": "OUT"}, "max_depth": 2}
    rest.kout.post(body=body)
    assert json.loads(http.calls[0][0].body) == body
    GraphManager(session).update_vertices([{"id": 1, "properties": {"score": 2}}], {"score": "SUM"})
    assert json.loads(http.calls[1][0].body) == {
        "vertices": [{"id": 1, "properties": {"score": 2}}],
        "update_strategies": {"score": "SUM"},
        "create_if_not_exist": True,
    }


def test_snake_case_edge_properties_preserve_server_wire_keys():
    session, _ = transport([{"id": "edge", "outV": 123, "inV": "123", "outVLabel": "a", "inVLabel": "b"}])
    edge = GraphManager(session).get_edge_by_id("edge")
    assert edge.out_v == 123
    assert edge.in_v == "123"
    assert edge.out_v_label == "a"
    assert edge.in_v_label == "b"
    assert edge.to_dict()["outV"] == 123
    assert edge.to_dict()["inV"] == "123"


def test_bearer_header_is_not_overwritten_by_basic_authentication():
    session, http = transport()
    RestManager(session).login.verify_token(authorization="Bearer private-token")
    assert http.calls[0][0].headers["Authorization"] == "Bearer private-token"


def test_gremlin_get_forwards_uri_parameters_missing_from_openapi():
    session, http = transport()
    RestManager(session).gremlin.get(gremlin="x + y", query={"bindings.x": "1", "bindings.y": "2"})
    assert query(http.calls[0][0]) == {"gremlin": ["x + y"], "bindings.x": ["1"], "bindings.y": ["2"]}


def test_text_graph_creation_uses_text_content_type():
    session, http = transport()
    RestManager(session).graphs.create_by_text("new graph", body="backend=rocksdb\nstore=test")
    request = http.calls[0][0]
    assert request.headers["Content-Type"] == "text/plain"
    assert request.body == "backend=rocksdb\nstore=test"
    assert request.url.endswith("/graphs/new%20graph")


@pytest.mark.parametrize("space", [None, "DEFAULT"])
def test_scope_adapter_preserves_server_proxy_prefix_and_global_groups(space):
    session, http = transport(graphspace=space)
    rest = RestManager(session)
    rest.user.list(name="alice")
    rest.group.list()
    prefix = "/graphspaces/DEFAULT" if space else ""
    assert urlsplit(http.calls[0][0].url).path == "/proxy" + prefix + "/auth/users"
    assert urlsplit(http.calls[1][0].url).path == "/proxy/auth/groups"


def test_legacy_profile_rejects_graphspace_only_operations():
    session, http = transport(graphspace=None)
    with pytest.raises(UnsupportedOperationError):
        RestManager(session).graph_space.list()
    assert http.calls == []


def test_client_owns_one_session_and_closes_it_once(monkeypatch):
    session, http = transport()
    monkeypatch.setattr("pyhugegraph.client.HGraphSession", lambda cfg: session)
    with PyHugeClient("http://localhost", "g", "admin", "private-password", graphspace="DEFAULT") as client:
        assert client.graph().session is client.olap().session is client.task().session
        assert client.rest() is client.rest()
        assert "private-password" not in repr(client)
    client.close()
    assert http.close_count == 1
    with pytest.raises(RuntimeError, match="closed"):
        client.task().get_task(1)
