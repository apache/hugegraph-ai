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


"""Exercise connection diagnostics without replacing the application's logger."""

import io
import json
import logging
import traceback
from unittest.mock import Mock

import pytest
import requests
from requests.auth import HTTPBasicAuth

from hugegraph_llm.demo.rag_demo import configs_block

pytestmark = pytest.mark.contract
SECRETS = {
    "url_password": "synthetic-url-password",
    "query": "synthetic-query-token",
    "header": "synthetic-header-token",
    "param": "synthetic-param-token",
    "body": "synthetic-body-password",
    "auth": "synthetic-auth-password",
    "response": "synthetic-response-secret",
    "exception": "synthetic-exception-secret",
}
SENSITIVE_URL = f"https://probe-user:{SECRETS['url_password']}@service.invalid/check?api_key={SECRETS['query']}"


@pytest.fixture
def captured_log():
    # Add a normal handler to the real logger: formatting, level selection and
    # logging calls still execute, including the vulnerable DEBUG branch.
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = configs_block.log
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        handler.close()


def assert_safe(*texts):
    combined = "\n".join(texts)
    for marker in SECRETS.values():
        assert marker not in combined


def formatted_error(exc_info):
    return "".join(traceback.format_exception(exc_info.type, exc_info.value, exc_info.tb))


@pytest.mark.parametrize("method", ["get", "pOsT"])
def test_success_diagnostics_omit_request_secrets_and_preserve_transport(monkeypatch, captured_log, method):
    get = Mock(return_value=Mock(status_code=200, text=SECRETS["response"]))
    post = Mock(return_value=Mock(status_code=200, text=SECRETS["response"]))
    monkeypatch.setattr(configs_block.requests, "get", get)
    monkeypatch.setattr(configs_block.requests, "post", post)
    info = Mock()
    monkeypatch.setattr(configs_block.gr, "Info", info)
    headers = {"Authorization": f"Bearer {SECRETS['header']}"}
    params = {"api_key": SECRETS["param"]}
    body = {"password": SECRETS["body"]}
    auth = HTTPBasicAuth("probe-user", SECRETS["auth"])

    result = configs_block.test_api_connection(
        SENSITIVE_URL,
        method=method,
        headers=headers,
        params=params,
        body=body,
        auth=auth,
    )

    assert result == 200
    expected = {"headers": headers, "params": params, "timeout": (1.0, 5.0), "auth": auth}
    if method.upper() == "POST":
        post.assert_called_once_with(SENSITIVE_URL, json=body, **expected)
        get.assert_not_called()
    else:
        get.assert_called_once_with(SENSITIVE_URL, **expected)
        post.assert_not_called()
    info.assert_called_once()
    assert "successful" in captured_log.getvalue()
    assert_safe(captured_log.getvalue(), str(info.call_args))


@pytest.mark.parametrize("origin", ["http", None])
@pytest.mark.parametrize("body_kind", ["message", "text", "array"])
def test_rejected_response_keeps_status_without_echoing_body(monkeypatch, captured_log, origin, body_kind):
    response_text = {
        "message": json.dumps({"message": f"Rejected token: {SECRETS['response']}"}),
        "text": f"<html>Request credentials: {SECRETS['response']}</html>",
        "array": json.dumps([SECRETS["response"]]),
    }[body_kind]
    monkeypatch.setattr(configs_block.requests, "get", Mock(return_value=Mock(status_code=403, text=response_text)))
    rendered = ""
    if origin == "http":
        assert configs_block.test_api_connection("https://service.invalid/check", origin_call=origin) == 403
    else:
        with pytest.raises(configs_block.gr.Error) as exc_info:
            configs_block.test_api_connection("https://service.invalid/check")
        rendered = formatted_error(exc_info)
    assert "403" in captured_log.getvalue()
    assert_safe(captured_log.getvalue(), rendered)
    if origin is None:
        assert "403" in str(exc_info.value)


@pytest.mark.parametrize("origin", ["http", None])
@pytest.mark.parametrize("exception_type", [requests.exceptions.ConnectionError, requests.exceptions.Timeout])
def test_transport_failure_diagnostics_do_not_expose_exception_or_chain(
    monkeypatch,
    captured_log,
    origin,
    exception_type,
):
    error = exception_type(f"Request failed at {SENSITIVE_URL}: {SECRETS['exception']}")
    monkeypatch.setattr(configs_block.requests, "get", Mock(side_effect=error))
    rendered = ""
    if origin == "http":
        assert configs_block.test_api_connection("https://service.invalid/check", origin_call=origin) == -1
    else:
        with pytest.raises(configs_block.gr.Error) as exc_info:
            configs_block.test_api_connection("https://service.invalid/check")
        rendered = formatted_error(exc_info)
    assert "Connection" in captured_log.getvalue()
    assert_safe(captured_log.getvalue(), rendered)
