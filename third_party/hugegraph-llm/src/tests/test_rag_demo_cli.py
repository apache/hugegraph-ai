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

from unittest.mock import Mock

import pytest

from hugegraph_llm.demo.rag_demo import app

pytestmark = pytest.mark.contract


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.255.255.254", True),
        ("::1", True),
        ("localhost", True),
        ("LOCALHOST", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.168.1.10", False),
        ("example.internal", False),
    ],
)
def test_is_loopback_host(host, expected):
    assert app.is_loopback_host(host) is expected


def test_parse_args_defaults_to_loopback():
    args = app.parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 8001


def test_run_server_passes_default_loopback_host_to_uvicorn(monkeypatch):
    uvicorn_run = Mock()
    monkeypatch.delenv("HG_DEV_RELOAD", raising=False)
    monkeypatch.setattr(app.uvicorn, "run", uvicorn_run)

    app.run_server(app.parse_args([]))

    uvicorn_run.assert_called_once_with(
        "hugegraph_llm.demo.rag_demo.app:create_app",
        host="127.0.0.1",
        port=8001,
        factory=True,
        reload=False,
    )


def test_run_server_warns_when_binding_non_loopback(monkeypatch):
    uvicorn_run = Mock()
    warning = Mock()
    monkeypatch.setattr(app.uvicorn, "run", uvicorn_run)
    monkeypatch.setattr(app.log, "warning", warning)

    app.run_server(app.parse_args(["--host", "0.0.0.0"]))

    warning.assert_called_once()
    message = warning.call_args.args[0]
    assert "no unified authentication" in message.lower()
    assert "reverse proxy authentication" in message.lower()
    assert "firewall" in message.lower()
    assert "trusted network" in message.lower()
    uvicorn_run.assert_called_once()
    assert uvicorn_run.call_args.kwargs["host"] == "0.0.0.0"


def test_run_server_does_not_warn_for_loopback(monkeypatch):
    monkeypatch.setattr(app.uvicorn, "run", Mock())
    warning = Mock()
    monkeypatch.setattr(app.log, "warning", warning)

    app.run_server(app.parse_args(["--host", "::1"]))

    warning.assert_not_called()
