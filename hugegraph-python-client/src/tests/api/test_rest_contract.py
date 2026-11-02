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

"""Exercise resource calls through real requests preparation and response parsing."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from pyhugegraph.api.auth import AuthManager
from pyhugegraph.api.graph import GraphManager
from pyhugegraph.api.graphs import GraphsManager
from pyhugegraph.api.gremlin import GremlinManager
from pyhugegraph.api.olap import OlapManager
from pyhugegraph.api.rest import RestManager
from pyhugegraph.api.schema import SchemaManager
from pyhugegraph.api.task import TaskManager
from pyhugegraph.client import PyHugeClient
from pyhugegraph.structure.rank_data import NeighborRankStep
from pyhugegraph.utils.exceptions import (
    ResponseParseError,
    ServerError,
    TaskCancelledError,
    TaskFailedError,
    TaskTimeoutError,
    UnsupportedOperationError,
)
from pyhugegraph.utils.huge_config import HGraphConfig
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


def transport(responses=(), *, graphspace="DEFAULT", url="https://example.test/proxy", timeout=(0.5, 15)):
    http = RecordingHTTP(responses)
    cfg = SimpleNamespace(
        url=url,
        graph_name="g",
        graphspace=graphspace,
        gs_supported=graphspace is not None,
        username="admin",
        password="private-password",
        timeout=timeout,
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


def test_gremlin_jobs_leave_aliases_to_the_server():
    session, http = transport([{"task_id": 9}, {}])
    gremlin = GremlinManager(session)
    assert gremlin.submit("x + 1", bindings={"x": 2}) == {"task_id": 9}
    request = http.calls[0][0]
    assert request.url.endswith("/jobs/gremlin")
    assert json.loads(request.body) == {"gremlin": "x + 1", "bindings": {"x": 2}, "language": "gremlin-groovy"}
    gremlin.query("x + 1", bindings={"x": 2})
    assert json.loads(http.calls[1][0].body)["aliases"] == {"graph": "DEFAULT-g", "g": "__g_DEFAULT-g"}


def test_neighbor_rank_step_preserves_positional_top():
    step = NeighborRankStep("OUT", ["knows"], 1000, 10, skip_degree=2000)
    assert json.loads(step.dumps()) == {
        "direction": "OUT",
        "labels": ["knows"],
        "max_degree": 1000,
        "top": 10,
        "skip_degree": 2000,
    }


@pytest.mark.parametrize(
    "method", ["get_vertex_by_page", "get_vertex_by_condition", "get_vertex_by_condition_with_page", "get_edge_by_page"]
)
def test_graph_helpers_distinguish_offsets_and_cursor_pages(method):
    session, http = transport([{"vertices": [], "edges": []}] * 3)
    query_graph = getattr(GraphManager(session), method)
    query_graph(label="person", limit=10, offset=5)
    assert query(http.calls[0][0]) == {"label": ["person"], "limit": ["10"], "offset": ["5"]}
    query_graph(label="person", limit=10)
    assert query(http.calls[1][0])["page"] == [""]
    query_graph(label="person", limit=10, page="next", offset=0)
    assert query(http.calls[2][0])["page"] == ["next"]
    for page in ("", "next"):
        with pytest.raises(ValueError, match="page and nonzero offset"):
            query_graph(label="person", limit=10, offset=5, page=page)
    assert len(http.calls) == 3


def test_generated_resources_distinguish_missing_body_from_explicit_null():
    session, http = transport()
    graphs = RestManager(session).graphs
    graphs.reload()
    assert http.calls[0][0].body is None
    graphs.reload(body=None)
    assert http.calls[1][0].body == "null"
    graphs.reload(body={"action": "reload"})
    assert json.loads(http.calls[2][0].body) == {"action": "reload"}


def test_legacy_schema_builder_names_preserve_the_wire_contract():
    session, http = transport([{}, {"property_key": {"name": "name", "data_type": "TEXT"}}])
    SchemaManager(session).propertyKey("name").asText().valueSingle().ifNotExist().create()
    assert http.calls[0][0].method == "GET"
    request = http.calls[1][0]
    assert request.method == "POST"
    assert request.url.endswith("/schema/propertykeys")
    assert json.loads(request.body) == {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"}


def test_legacy_graph_methods_and_edge_properties_keep_working():
    session, http = transport(
        [
            {"id": "alice", "label": "person", "properties": {"name": "Alice"}},
            {"id": "edge", "outV": "alice", "inV": 123, "outVLabel": "person", "inVLabel": "person"},
        ]
    )
    graph = GraphManager(session)
    vertex = graph.addVertex("person", {"name": "Alice"})
    assert vertex.id == "alice"
    assert json.loads(http.calls[0][0].body) == {"label": "person", "properties": {"name": "Alice"}}
    edge = graph.getEdgeById("edge")
    assert edge.outV == edge.out_v == "alice"
    assert edge.inV == edge.in_v == 123
    assert edge.outVLabel == edge.out_v_label == "person"
    assert edge.inVLabel == edge.in_v_label == "person"


@pytest.mark.parametrize("args, kwargs", [((), {}), (("json",), {}), (("groovy",), {}), ((), {"_format": "groovy"})])
def test_legacy_schema_export_name_returns_the_native_json_schema(args, kwargs):
    schema = {"propertykeys": [], "vertexlabels": [], "edgelabels": [], "indexlabels": []}
    session, http = transport([schema])
    assert SchemaManager(session).getSchema(*args, **kwargs) == schema
    assert http.calls[0][0].url.endswith("/schema")


@pytest.mark.parametrize(
    "legacy, resource, native, args, payload",
    [
        ("get_all_graphs", "graphs", "list", (), {"graphs": ["g"]}),
        ("get_version", "version", "list", (), {"versions": {"core": "1.8.0"}}),
        ("get_graph_info", "graphs", "get", ("g",), {"name": "g", "backend": "rocksdb"}),
    ],
)
def test_legacy_graph_helpers_keep_text_while_rest_returns_json(legacy, resource, native, args, payload):
    session, http = transport([payload, payload])
    old_result = getattr(GraphsManager(session), legacy)()
    assert isinstance(old_result, str)
    assert json.loads(old_result) == payload
    new_result = getattr(getattr(RestManager(session), resource), native)(*args)
    assert isinstance(new_result, dict)
    assert new_result == payload
    assert http.calls[0][0].url == http.calls[1][0].url


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


@pytest.mark.parametrize("http_timeout", [(0.5, 15), 2])
def test_wait_loads_result_once_after_success(clock, http_timeout):
    session, http = transport(
        [
            {"id": 7, "task_status": "running"},
            {"id": 7, "task_status": "success"},
            {"id": 7, "task_status": "success", "task_result": '{"count": 3}'},
        ],
        timeout=http_timeout,
    )
    tasks = TaskManager(session)
    task = tasks.wait(7, timeout=5, poll_interval=0.2)
    assert tasks.result(task) == {"count": 3}
    assert [query(req)["with_result"] for req, _ in http.calls] == [["false"], ["false"], ["true"]]
    assert all(options["timeout"].total <= 5 for _, options in http.calls)


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


def test_wait_rechecks_deadline_after_loading_result(clock, monkeypatch):
    session, http = transport([{"id": 7, "task_status": "success"}] * 2)
    send = http.send

    def delayed_result(request, **kwargs):
        if query(request)["with_result"] == ["true"]:
            clock.now += 2
        return send(request, **kwargs)

    monkeypatch.setattr(http, "send", delayed_result)
    with pytest.raises(TaskTimeoutError):
        TaskManager(session).wait(7, timeout=1)


def test_wait_converts_expired_read_timeout(clock, monkeypatch):
    session, http = transport()

    def timeout(request, **kwargs):
        clock.now += 1
        raise requests.ReadTimeout("read timed out")

    monkeypatch.setattr(http, "send", timeout)
    with pytest.raises(TaskTimeoutError):
        TaskManager(session).wait(7, timeout=0.1)


def test_wait_disables_transport_retries_without_changing_later_requests():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            self.send_response(500 if len(calls) <= 2 else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id": 7, "task_status": "running"}')

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session, _ = transport(url=f"http://127.0.0.1:{server.server_port}")
        http = requests.Session()
        http.trust_env = False
        session = HGraphSession(session.cfg, retries=2, backoff_factor=0, session=http)
        try:
            with pytest.raises(ServerError):
                TaskManager(session).wait(7, timeout=1)
            assert len(calls) == 1
            assert TaskManager(session).get_task(7)["task_status"] == "running"
            assert len(calls) == 3
        finally:
            session.close()
            server.shutdown()
            thread.join(timeout=2)


def test_wait_reuses_http_connections_when_retries_are_disabled():
    ports = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            ports.append(self.client_address[1])
            body = json.dumps({"id": 7, "task_status": "running" if len(ports) == 1 else "success"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cfg = HGraphConfig(f"http://127.0.0.1:{server.server_port}", "admin", "password", "g", graphspace="DEFAULT")
        http = requests.Session()
        http.trust_env = False
        session = HGraphSession(cfg, session=http)
        try:
            assert TaskManager(session).wait(7, timeout=2, poll_interval=0.001)["task_status"] == "success"
            assert len(ports) == 3
            assert len(set(ports)) == 1
        finally:
            session.close()
            server.shutdown()
            thread.join(timeout=2)


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


def test_bearer_header_is_not_overwritten_by_basic_or_netrc_authentication(monkeypatch):
    monkeypatch.setattr("requests.sessions.get_netrc_auth", lambda _: ("netrc-user", "netrc-password"))
    session, http = transport()
    RestManager(session).login.verify_token(authorization="Bearer private-token")
    assert http.calls[0][0].headers["Authorization"] == "Bearer private-token"

    session.use_token("session-token")
    AuthManager(session).list_users(name="alice")
    assert http.calls[1][0].headers["Authorization"] == "Bearer session-token"
    assert query(http.calls[1][0]) == {"name": ["alice"]}


@pytest.mark.parametrize("token", [None, "proxy-token"])
def test_version_probe_uses_the_selected_authentication(monkeypatch, token):
    http = RecordingHTTP([{"versions": {"core": "1.6.0"}}])
    monkeypatch.setattr("requests.sessions.get_netrc_auth", lambda _: ("netrc-user", "netrc-password"))
    monkeypatch.setattr("pyhugegraph.utils.huge_config.requests.get", http.get)
    cfg = HGraphConfig("http://example.test/proxy", "admin", "password", "g", token=token)
    assert cfg.version == [1, 6, 0]
    expected = "Bearer proxy-token" if token else requests.auth._basic_auth_str("admin", "password")
    assert http.calls[0][0].headers["Authorization"] == expected
    assert "proxy-token" not in repr(cfg)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), (1, 0), (5, None), (1,), "invalid"])
def test_invalid_http_timeout_fails_before_version_probe(monkeypatch, timeout):
    def unexpected_probe(*_args, **_kwargs):
        pytest.fail("Invalid HTTP timeout must fail before network access")

    monkeypatch.setattr("pyhugegraph.utils.huge_config.requests.get", unexpected_probe)
    with pytest.raises(ValueError, match="HTTP timeout"):
        PyHugeClient("http://example.test", "g", "admin", "password", timeout=timeout)


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
