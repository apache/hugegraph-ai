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

from unittest import mock
from urllib.parse import urljoin

import pytest
import requests
from pyhugegraph.api.auth import AuthManager
from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.api.schema_manage.edge_label import EdgeLabel
from pyhugegraph.api.services import ServicesManager
from pyhugegraph.structure.services_data import ServiceCreateParameters
from pyhugegraph.utils.huge_config import HGraphConfig
from pyhugegraph.utils.huge_requests import HGraphSession
from pyhugegraph.utils.huge_router import http

pytestmark = pytest.mark.contract

# FIXME: cover real HGraphSession.resolve() with URL prefixes; this
# DummySession duplicates production routing behavior.


class DummyCfg:
    def __init__(self, url, graphspace, gs_supported, graph_name):
        self.url = url
        self.graphspace = graphspace
        self.gs_supported = gs_supported
        self.graph_name = graph_name


class DummySession:
    """Minimal session mimic implementing resolve and request used by router."""

    def __init__(self, cfg: DummyCfg):
        self.cfg = cfg
        self.last = None

    def resolve(self, path: str) -> str:
        base = f"{self.cfg.url.rstrip('/')}/"
        if self.cfg.gs_supported:
            base = urljoin(base, f"graphspaces/{self.cfg.graphspace}/graphs/{self.cfg.graph_name}/")
        else:
            base = urljoin(base, f"graphs/{self.cfg.graph_name}/")
        return urljoin(base, path).strip("/")

    def request(self, path: str, method: str = "GET", validator=None, **kwargs):
        # mirror behavior of real session.request used by router: resolve path
        self.last = self.resolve(path)
        return {"url": self.last, "method": method}


class DummySchemaSession:
    def __init__(self):
        self.requests = []

    def request(self, path: str, method: str = "GET", validator=None, **kwargs):
        self.requests.append({"path": path, "method": method, **kwargs})
        return {"ok": True}


@pytest.mark.parametrize(
    "endpoint, method_call, args, expected_subpath",
    [
        ("users", "list_users", (), "graphspaces/GS/auth/users"),
        ("users", "get_user", ("u1",), "graphspaces/GS/auth/users/u1"),
        ("accesses", "list_accesses", (), "graphspaces/GS/auth/accesses"),
        (
            "accesses",
            "get_accesses",
            ("a1",),
            "graphspaces/GS/auth/accesses/a1",
        ),
        ("targets", "list_targets", (), "graphspaces/GS/auth/targets"),
        ("belongs", "list_belongs", (), "graphspaces/GS/auth/belongs"),
    ],
)
def test_graphspace_scoped_endpoints_use_graphspace(endpoint, method_call, args, expected_subpath):
    cfg = DummyCfg(url="http://127.0.0.1:8080", graphspace="GS", gs_supported=True, graph_name="g")
    sess = DummySession(cfg)
    auth = AuthManager(sess)

    getattr(auth, method_call)(*args)
    assert sess.last == f"http://127.0.0.1:8080/{expected_subpath}"


@pytest.mark.parametrize(
    "method_call, args, expected_subpath",
    [
        ("list_users", (), "auth/users"),
        ("get_user", ("u1",), "auth/users/u1"),
        ("list_accesses", (), "auth/accesses"),
        ("get_accesses", ("a1",), "auth/accesses/a1"),
        ("list_targets", (), "auth/targets"),
        ("list_belongs", (), "auth/belongs"),
    ],
)
def test_auth_endpoints_use_legacy_paths_without_graphspace(method_call, args, expected_subpath):
    cfg = DummyCfg(url="http://127.0.0.1:8080", graphspace=None, gs_supported=False, graph_name="g")
    sess = DummySession(cfg)
    auth = AuthManager(sess)

    getattr(auth, method_call)(*args)

    assert sess.last == f"http://127.0.0.1:8080/{expected_subpath}"


def test_legacy_auth_ignores_explicit_graphspace_placeholder_argument():
    class ExplicitGraphspaceAuth(HugeParamsBase):
        @http("GET", "/graphspaces/{graphspace}/auth/users")
        def list_users(self, graphspace):
            return self._invoke_request()

    cfg = DummyCfg(url="http://127.0.0.1:8080", graphspace=None, gs_supported=False, graph_name="g")
    sess = DummySession(cfg)

    ExplicitGraphspaceAuth(sess).list_users("SPACE_X")

    assert sess.last == "http://127.0.0.1:8080/auth/users"


@pytest.mark.parametrize(
    "method_call, args",
    [
        ("list_users", ()),
        ("get_user", ("u1",)),
        ("list_accesses", ()),
        ("get_accesses", ("a1",)),
        ("list_targets", ()),
        ("list_belongs", ()),
    ],
)
def test_graphspace_auth_requires_graphspace_when_supported(method_call, args):
    cfg = DummyCfg(url="http://127.0.0.1:8080", graphspace=None, gs_supported=True, graph_name="g")
    sess = DummySession(cfg)

    with pytest.raises(ValueError, match="graphspace is required for this endpoint"):
        getattr(AuthManager(sess), method_call)(*args)


def test_services_use_explicit_graphspace_without_graphspace_session():
    cfg = DummyCfg(url="http://127.0.0.1:8080", graphspace=None, gs_supported=False, graph_name="g")
    sess = DummySession(cfg)
    services = ServicesManager(sess)

    services.get_service("SPACE_X", "svc")
    assert sess.last == "http://127.0.0.1:8080/graphspaces/SPACE_X/services/svc"

    services.list_services("SPACE_X")
    assert sess.last == "http://127.0.0.1:8080/graphspaces/SPACE_X/services"

    body = ServiceCreateParameters(name="svc", description="test service")
    services.create_services("SPACE_X", body)
    assert sess.last == "http://127.0.0.1:8080/graphspaces/SPACE_X/services"


def test_groups_are_server_level():
    # With graphspace support
    cfg = DummyCfg(url="http://127.0.0.1:8080", graphspace="GS", gs_supported=True, graph_name="g")
    sess = DummySession(cfg)
    auth = AuthManager(sess)
    auth.list_groups()
    assert "auth/groups" in sess.last

    # Without graphspace support
    cfg2 = DummyCfg(url="http://127.0.0.1:8080", graphspace=None, gs_supported=False, graph_name="g")
    sess2 = DummySession(cfg2)
    auth2 = AuthManager(sess2)
    auth2.list_groups()
    assert "auth/groups" in sess2.last


class _VersionResponse:
    def __init__(self, core: str):
        self._core = core

    def json(self):
        return {"versions": {"core": self._core}}


def test_hgraph_config_does_not_auto_enable_graphspace_before_1_7(monkeypatch):
    monkeypatch.setattr(
        "pyhugegraph.utils.huge_config.requests.get",
        lambda *_args, **_kwargs: _VersionResponse("1.6.0"),
    )

    cfg = HGraphConfig("127.0.0.1:8080", "admin", "pwd", "hugegraph")

    assert cfg.version == [1, 6, 0]
    assert cfg.graphspace is None
    assert cfg.gs_supported is False

    sess = DummySession(cfg)
    AuthManager(sess).list_users()
    assert sess.last == "http://127.0.0.1:8080/auth/users"

    response = mock.Mock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = {"users": []}
    response.raise_for_status.return_value = None
    raw_session = mock.Mock()
    raw_session.get.return_value = response
    real_session = HGraphSession(cfg, session=raw_session)

    AuthManager(real_session).list_users()

    requested_url = raw_session.get.call_args.args[0]
    assert requested_url == "http://127.0.0.1:8080/auth/users"


def test_hgraph_config_auto_enables_default_graphspace_for_1_7(monkeypatch):
    monkeypatch.setattr(
        "pyhugegraph.utils.huge_config.requests.get",
        lambda *_args, **_kwargs: _VersionResponse("1.7.0"),
    )

    cfg = HGraphConfig("127.0.0.1:8080", "admin", "pwd", "hugegraph")

    assert cfg.version == [1, 7, 0]
    assert cfg.graphspace == "DEFAULT"
    assert cfg.gs_supported is True


def test_edge_label_parent_emits_sub_edge_payload():
    sess = DummySchemaSession()
    edge_label = EdgeLabel(sess)
    edge_label.create_parameter_holder()
    edge_label.add_parameter("name", "knows_more")
    edge_label.add_parameter("not_exist", True)

    edge_label.sourceLabel("person").targetLabel("person").parent("knows").create()

    request = sess.requests[-1]
    assert request["path"] == "schema/edgelabels"
    assert request["method"] == "POST"
    assert '"parent_label": "knows"' in request["data"]
    assert '"edgelabel_type": "SUB"' in request["data"]


def test_session_debug_log_redacts_sensitive_kwargs():
    cfg = DummyCfg(url="http://127.0.0.1:8080", graphspace=None, gs_supported=False, graph_name="g")
    cfg.username = "admin"
    cfg.password = "admin-password"
    cfg.timeout = 30
    response = mock.Mock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = {"ok": True}
    response.raise_for_status.return_value = None
    raw_session = mock.Mock()
    raw_session.post.return_value = response
    session = HGraphSession(cfg, session=raw_session)

    with (
        mock.patch("pyhugegraph.utils.huge_requests.log.isEnabledFor", return_value=True),
        mock.patch("pyhugegraph.utils.huge_requests.log.debug") as log_debug,
    ):
        session.request(
            "/auth/users",
            method="POST",
            data='{"user_name":"marko","user_password":"super-secret"}',
        )

    logged_args = str(log_debug.call_args)
    assert "super-secret" not in logged_args
    assert "***REDACTED***" in logged_args


def test_session_skips_debug_redaction_when_debug_disabled():
    cfg = DummyCfg(url="http://127.0.0.1:8080", graphspace=None, gs_supported=False, graph_name="g")
    cfg.username = "admin"
    cfg.password = "admin-password"
    cfg.timeout = 30
    response = mock.Mock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = {"ok": True}
    response.raise_for_status.return_value = None
    raw_session = mock.Mock()
    raw_session.post.return_value = response
    session = HGraphSession(cfg, session=raw_session)

    with (
        mock.patch("pyhugegraph.utils.huge_requests.log.isEnabledFor", return_value=False),
        mock.patch("pyhugegraph.utils.huge_requests.redact_sensitive_data") as redact,
    ):
        session.request(
            "/auth/users",
            method="POST",
            data='{"user_name":"marko","user_password":"super-secret"}',
        )

    redact.assert_not_called()
