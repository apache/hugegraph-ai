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

from unittest.mock import Mock

import pytest
import requests
from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.hugegraph_ai_client import get, health_check, post, request


class FakeResponse:
    def __init__(self, data=None, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


def _cfg(**overrides):
    values = {
        "ai_url": "http://ai.example:8001",
        "allow_ai": True,
        "timeout_seconds": 7,
    }
    values.update(overrides)
    return MCPConfig(**values)


def test_request_success(monkeypatch):
    http_request = Mock(return_value=FakeResponse({"status": "ok"}))
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is True
    assert result["data"] == {"status": "ok"}
    http_request.assert_called_once_with(
        "GET",
        "http://ai.example:8001/health",
        params=None,
        headers=None,
        timeout=7,
    )


def test_request_unwraps_thin_api_success_envelope(monkeypatch):
    thin_response = {
        "ok": True,
        "data": {"status": "ready"},
        "error": None,
        "warnings": ["remote warning"],
        "next_actions": ["continue"],
        "meta": {"request_id": "req-ai-1", "duration_ms": 1},
    }
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse(thin_response)),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is True
    assert result["data"] == {"status": "ready"}
    assert result["warnings"] == ["remote warning"]
    assert result["next_actions"] == ["continue"]
    assert result["meta"]["request_id"] == "req-ai-1"


def test_request_propagates_thin_api_error_envelope(monkeypatch):
    thin_response = {
        "ok": False,
        "data": None,
        "error": {
            "type": "FLOW_EXECUTION_FAILED",
            "message": "flow failed",
            "suggestion": "check model configuration",
            "retryable": False,
            "source": "hugegraph-llm",
            "details": {"stage": "extract"},
        },
        "warnings": [],
        "next_actions": [],
        "meta": {"request_id": "req-ai-2", "duration_ms": 1},
    }
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse(thin_response)),
    )

    result = request("POST", "/graph-extract", cfg=_cfg(), json={})

    assert result["ok"] is False
    assert result["error"]["type"] == "FLOW_EXECUTION_FAILED"
    assert result["error"]["message"] == "flow failed"
    assert result["error"]["source"] == "hugegraph-llm"
    assert result["error"]["details"] == {"stage": "extract"}
    assert result["meta"]["request_id"] == "req-ai-2"


def test_request_unwraps_error_envelope_nested_in_success_envelope(monkeypatch):
    inner_error = {
        "ok": False,
        "data": None,
        "error": {
            "type": "FLOW_EXECUTION_FAILED",
            "message": "inner flow failed",
            "suggestion": "check the flow",
            "retryable": False,
            "source": "hugegraph-llm",
            "details": {"stage": "extract"},
        },
        "warnings": ["inner warning"],
        "next_actions": ["inspect configuration"],
        "meta": {"request_id": "req-inner", "duration_ms": 1},
    }
    outer_success = {
        "ok": True,
        "data": inner_error,
        "error": None,
        "warnings": [],
        "next_actions": [],
        "meta": {"request_id": "req-outer", "duration_ms": 2},
    }
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse(outer_success)),
    )

    result = request("POST", "/graph-extract", cfg=_cfg(), json={})

    assert result["ok"] is False
    assert result["data"] is None
    assert result["error"]["type"] == "FLOW_EXECUTION_FAILED"
    assert result["error"]["message"] == "inner flow failed"
    assert result["error"]["details"] == {"stage": "extract"}
    assert result["warnings"] == ["inner warning"]
    assert result["next_actions"] == ["inspect configuration"]
    assert result["meta"]["request_id"] == "req-inner"


def test_request_rejects_excessively_nested_thin_api_envelopes(monkeypatch):
    payload = {"status": "ready"}
    for index in reversed(range(3)):
        payload = {
            "ok": True,
            "data": payload,
            "error": None,
            "warnings": [],
            "next_actions": [],
            "meta": {"request_id": f"req-depth-{index}", "duration_ms": 1},
        }
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse(payload)),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["type"] == "HUGEGRAPH_AI_UNAVAILABLE"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"] == {
        "reason": "invalid_upstream_response",
        "issue": "nested_envelope_depth_exceeded",
        "max_nested_envelopes": 1,
    }


def test_request_rejects_cyclic_thin_api_envelope(monkeypatch):
    cyclic = {
        "ok": True,
        "data": None,
        "error": None,
        "warnings": [],
        "next_actions": [],
        "meta": {"request_id": "req-cycle", "duration_ms": 1},
    }
    cyclic["data"] = cyclic
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse(cyclic)),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["details"]["reason"] == "invalid_upstream_response"
    assert result["error"]["details"]["issue"] == "cyclic_nested_envelope"


def test_request_rejects_malformed_nested_thin_api_envelope(monkeypatch):
    malformed = {
        "ok": True,
        "data": {"status": "ready"},
        "error": None,
        "warnings": "not-a-list",
        "next_actions": [],
        "meta": {"request_id": "req-malformed", "duration_ms": 1},
    }
    outer = {
        "ok": True,
        "data": malformed,
        "error": None,
        "warnings": [],
        "next_actions": [],
        "meta": {"request_id": "req-outer", "duration_ms": 1},
    }
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse(outer)),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["details"]["reason"] == "invalid_upstream_response"
    assert result["error"]["details"]["issue"] == "malformed_nested_envelope"


def test_request_propagates_thin_api_error_envelope_on_http_error(monkeypatch):
    thin_response = {
        "ok": False,
        "data": None,
        "error": {"type": "VALIDATION_ERROR", "message": "bad request"},
        "warnings": [],
        "next_actions": [],
        "meta": {"request_id": "req-ai-3", "duration_ms": 1},
    }
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse(thin_response, status_code=400)),
    )

    result = request("POST", "/graph-extract", cfg=_cfg(), json={})

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["meta"]["request_id"] == "req-ai-3"


def test_request_does_not_allow_success_envelope_to_hide_http_error(monkeypatch):
    thin_response = {
        "ok": True,
        "data": {"status": "ready"},
        "error": None,
        "warnings": [],
        "next_actions": [],
        "meta": {"request_id": "req-ai-4", "duration_ms": 1},
    }
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse(thin_response, status_code=500)),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["details"]["status_code"] == 500


def test_request_preserves_http_error_for_non_json_body(monkeypatch):
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse(ValueError("not json"), status_code=500)),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["details"]["status_code"] == 500


def test_request_does_not_unwrap_domain_dict_that_only_looks_like_envelope(monkeypatch):
    domain_data = {"ok": True, "data": 1, "error": None, "meta": {}}
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse(domain_data)),
    )

    result = request("GET", "/domain", cfg=_cfg())

    assert result["ok"] is True
    assert result["data"] == domain_data


def test_request_accepts_relative_path_without_leading_slash(monkeypatch):
    http_request = Mock(return_value=FakeResponse({"status": "ok"}))
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = request("GET", "health", cfg=_cfg())

    assert result["ok"] is True
    http_request.assert_called_once_with(
        "GET",
        "http://ai.example:8001/health",
        params=None,
        headers=None,
        timeout=7,
    )


@pytest.mark.parametrize(
    "path",
    [
        "http://attacker.example/collect",
        "HTTPS://attacker.example/collect",
        "ftp://attacker.example/collect",
        "//attacker.example/collect",
    ],
)
def test_request_rejects_absolute_url_before_network_call(monkeypatch, path):
    http_request = Mock()
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = request("GET", path, cfg=_cfg(ai_token="ai-secret"))

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"] == {
        "method": "GET",
        "reason": "absolute_url_not_allowed",
    }
    assert "ai-secret" not in repr(result)
    assert "attacker.example" not in repr(result)
    http_request.assert_not_called()


def test_request_does_not_reuse_graph_password_for_ai_auth(monkeypatch):
    http_request = Mock(return_value=FakeResponse({"status": "ok"}))
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = request("GET", "/health", cfg=_cfg(user="alice", password="secret"))

    assert result["ok"] is True
    http_request.assert_called_once_with(
        "GET",
        "http://ai.example:8001/health",
        params=None,
        headers=None,
        timeout=7,
    )


def test_request_injects_configured_bearer_token(monkeypatch):
    http_request = Mock(return_value=FakeResponse({"status": "ok"}))
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = request(
        "GET",
        "/health",
        cfg=_cfg(ai_token="ai-secret"),
        headers={"X-Trace": "trace-1"},
    )

    assert result["ok"] is True
    assert http_request.call_args.kwargs["headers"] == {
        "Authorization": "Bearer ai-secret",
        "X-Trace": "trace-1",
    }


def test_explicit_authorization_header_overrides_configured_token(monkeypatch):
    http_request = Mock(return_value=FakeResponse({"status": "ok"}))
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = request(
        "GET",
        "/health",
        cfg=_cfg(ai_token="configured-token"),
        headers={"authorization": "Bearer explicit-token", "X-Trace": "trace-1"},
    )

    assert result["ok"] is True
    assert http_request.call_args.kwargs["headers"] == {
        "authorization": "Bearer explicit-token",
        "X-Trace": "trace-1",
    }


def test_request_connection_error(monkeypatch):
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(side_effect=requests.exceptions.ConnectionError("connection refused")),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["type"] == "HUGEGRAPH_AI_UNAVAILABLE"


def test_request_timeout(monkeypatch):
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(side_effect=requests.exceptions.Timeout("timed out")),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["type"] == "HUGEGRAPH_AI_UNAVAILABLE"


def test_request_http_500(monkeypatch):
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse({"error": "boom"}, status_code=500)),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["type"] == "HUGEGRAPH_AI_UNAVAILABLE"
    assert result["error"]["details"]["status_code"] == 500


def test_request_http_401_is_authorization_failed(monkeypatch):
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse({"error": "denied"}, status_code=401)),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["type"] == "AUTHORIZATION_FAILED"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"]["status_code"] == 401


def test_request_http_404_is_not_authorization_failed(monkeypatch):
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse({"error": "missing"}, status_code=404)),
    )

    result = request("GET", "/missing", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["type"] == "HUGEGRAPH_AI_UNAVAILABLE"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"]["status_code"] == 404


def test_request_http_429_is_retryable_ai_error(monkeypatch):
    monkeypatch.setattr(
        "hugegraph_mcp.hugegraph_ai_client.requests.request",
        Mock(return_value=FakeResponse({"error": "rate limited"}, status_code=429)),
    )

    result = request("GET", "/health", cfg=_cfg())

    assert result["ok"] is False
    assert result["error"]["type"] == "HUGEGRAPH_AI_UNAVAILABLE"
    assert result["error"]["retryable"] is True
    assert result["error"]["details"]["status_code"] == 429


def test_request_allow_ai_disabled(monkeypatch):
    http_request = Mock()
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = request("GET", "/health", cfg=_cfg(allow_ai=False))

    assert result["ok"] is False
    assert result["error"]["type"] == "FEATURE_DISABLED"
    assert result["error"]["message"] == "AI calls are disabled by configuration"
    assert "HUGEGRAPH_MCP_ALLOW_AI=true" in result["error"]["suggestion"]
    assert result["error"]["retryable"] is False
    assert result["error"]["details"]["reason"] == "allow_ai_false"
    http_request.assert_not_called()


def test_post_convenience(monkeypatch):
    http_request = Mock(return_value=FakeResponse({"gremlin": "g.V().count()"}))
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = post("/generate-gremlin", cfg=_cfg(), json={"question": "count vertices"})

    assert result["ok"] is True
    http_request.assert_called_once_with(
        "POST",
        "http://ai.example:8001/generate-gremlin",
        params=None,
        headers=None,
        timeout=7,
        json={"question": "count vertices"},
    )


def test_get_convenience(monkeypatch):
    http_request = Mock(return_value=FakeResponse({"ready": True}))
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = get("/graph-index-info", cfg=_cfg())

    assert result["ok"] is True
    http_request.assert_called_once_with(
        "GET",
        "http://ai.example:8001/graph-index-info",
        params=None,
        headers=None,
        timeout=7,
    )


def test_health_check(monkeypatch):
    http_request = Mock(return_value=FakeResponse({"ok": True, "data": "ready"}))
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = health_check(cfg=_cfg())

    assert result["ok"] is True
    assert result["data"]["status"] == "available"
    assert result["data"]["health_endpoint"] == "/graph-index-info"
    http_request.assert_called_once_with(
        "GET",
        "http://ai.example:8001/graph-index-info",
        params=None,
        headers=None,
        timeout=7,
    )


def test_health_check_falls_back_to_openapi(monkeypatch):
    http_request = Mock(
        side_effect=[
            FakeResponse({"detail": "missing"}, status_code=404),
            FakeResponse({"openapi": "3.1.0"}),
        ]
    )
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = health_check(cfg=_cfg())

    assert result["ok"] is True
    assert result["data"]["status"] == "available"
    assert result["data"]["health_endpoint"] == "/openapi.json"
    assert result["data"]["openapi"] == "3.1.0"
    assert len(result["warnings"]) == 1
    assert http_request.call_args_list[0].args[:2] == (
        "GET",
        "http://ai.example:8001/graph-index-info",
    )
    assert http_request.call_args_list[1].args[:2] == (
        "GET",
        "http://ai.example:8001/openapi.json",
    )


def test_health_check_does_not_report_inner_failure_as_available(monkeypatch):
    inner_error = {
        "ok": False,
        "data": None,
        "error": {
            "type": "FLOW_EXECUTION_FAILED",
            "message": "index inspection failed",
            "retryable": False,
            "source": "hugegraph-llm",
            "details": {},
        },
        "warnings": [],
        "next_actions": [],
        "meta": {"request_id": "req-ai-health", "duration_ms": 1},
    }
    http_request = Mock(
        side_effect=[
            FakeResponse(inner_error),
            FakeResponse({"openapi": "3.1.0"}),
        ]
    )
    monkeypatch.setattr("hugegraph_mcp.hugegraph_ai_client.requests.request", http_request)

    result = health_check(cfg=_cfg())

    assert result["ok"] is True
    assert result["data"]["status"] == "available"
    assert result["data"]["health_endpoint"] == "/openapi.json"
    assert "index inspection failed" in result["warnings"][0]
    assert http_request.call_count == 2
