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

import os
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, FastAPI, status
from fastapi.testclient import TestClient

from hugegraph_llm.api.admin_api import admin_http_api
from hugegraph_llm.config import admin_settings
from hugegraph_llm.demo.rag_demo import admin_block

pytestmark = pytest.mark.contract


async def _empty_log_stream(_log_path):
    if False:
        yield ""


def _make_client(log_stream=None):
    router = APIRouter()
    admin_http_api(router, log_stream or _empty_log_stream)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_logs_rejects_path_traversal_before_streaming(monkeypatch):
    monkeypatch.setattr(admin_settings, "admin_token", "secure-admin-token")
    log_stream = Mock(side_effect=_empty_log_stream)
    client = _make_client(log_stream)

    response = client.post(
        "/logs",
        json={
            "admin_token": "secure-admin-token",
            "log_file": "../config_prompt.yaml",
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "Invalid log file name."
    log_stream.assert_not_called()


def test_logs_rejects_absolute_paths_before_streaming(monkeypatch):
    monkeypatch.setattr(admin_settings, "admin_token", "secure-admin-token")
    log_stream = Mock(side_effect=_empty_log_stream)
    client = _make_client(log_stream)

    response = client.post(
        "/logs",
        json={
            "admin_token": "secure-admin-token",
            "log_file": "/etc/passwd",
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["detail"] == "Invalid log file name."
    log_stream.assert_not_called()


def test_logs_rejects_default_admin_token(monkeypatch):
    monkeypatch.setattr(admin_settings, "admin_token", "xxxx")
    log_stream = Mock(side_effect=_empty_log_stream)
    client = _make_client(log_stream)

    response = client.post(
        "/logs",
        json={
            "admin_token": "xxxx",
            "log_file": "llm-server.log",
        },
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["detail"] == "Admin token is not configured securely."
    log_stream.assert_not_called()


def test_admin_block_rejects_default_admin_token(monkeypatch):
    monkeypatch.setattr(admin_settings, "admin_token", "xxxx")
    read_log = Mock(return_value="sensitive logs")
    monkeypatch.setattr(admin_block, "read_llm_server_log", read_log)

    output = admin_block.check_password("xxxx")

    assert output[0] == ""
    assert output[-1]["value"] == "Admin token is not configured securely."
    read_log.assert_not_called()


def test_admin_block_reads_logs_with_secure_admin_token(monkeypatch):
    monkeypatch.setattr(admin_settings, "admin_token", "secure-admin-token")
    read_log = Mock(return_value="safe logs")
    monkeypatch.setattr(admin_block, "read_llm_server_log", read_log)

    output = admin_block.check_password("secure-admin-token")

    assert output[0] == "safe logs"
    read_log.assert_called_once_with()


def test_logs_streams_valid_log_file_under_logs_dir(monkeypatch):
    monkeypatch.setattr(admin_settings, "admin_token", "secure-admin-token")
    log_stream = Mock(side_effect=_empty_log_stream)
    client = _make_client(log_stream)

    response = client.post(
        "/logs",
        json={
            "admin_token": "secure-admin-token",
            "log_file": "llm-server.log",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    log_stream.assert_called_once_with(os.path.join("logs", "llm-server.log"))
