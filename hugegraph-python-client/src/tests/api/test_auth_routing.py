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
from pyhugegraph.utils.huge_requests import HGraphSession

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
    assert expected_subpath in sess.last


@pytest.mark.parametrize(
    "endpoint, method_call, args",
    [
        ("users", "list_users", ()),
        ("users", "get_user", ("u1",)),
        ("accesses", "list_accesses", ()),
        ("accesses", "get_accesses", ("a1",)),
        ("targets", "list_targets", ()),
        ("belongs", "list_belongs", ()),
    ],
)
def test_graphspace_scoped_endpoints_require_graphspace(endpoint, method_call, args):
    # HugeGraph 1.7.0+ requires graphspace for these auth endpoints.
    cfg = DummyCfg(url="http://127.0.0.1:8080", graphspace=None, gs_supported=False, graph_name="g")
    sess = DummySession(cfg)
    auth = AuthManager(sess)

    with pytest.raises(ValueError, match="graphspace is required for auth endpoints"):
        getattr(auth, method_call)(*args)


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
