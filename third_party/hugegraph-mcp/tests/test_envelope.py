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

from hugegraph_mcp.config import config
from hugegraph_mcp.envelope import (
    ErrorType,
    envelope_err,
    envelope_ok,
    generate_request_id,
)


def test_envelope_ok_basic():
    result = envelope_ok({"items": [1, 2]}, duration_ms=12.5)

    assert result["ok"] is True
    assert result["data"] == {"items": [1, 2]}
    assert result["error"] is None
    assert result["warnings"] == []
    assert result["meta"]["request_id"].startswith("req-")
    assert len(result["meta"]["request_id"]) == len("req-") + 12


def test_envelope_ok_with_warnings():
    result = envelope_ok(
        {"created": 1},
        warnings=["schema cache is stale"],
        meta={"operation": "schema_create"},
    )

    assert result["ok"] is True
    assert result["warnings"] == ["schema cache is stale"]
    assert result["meta"]["operation"] == "schema_create"


def test_envelope_err_basic():
    result = envelope_err(
        ErrorType.CONNECTION_FAILED,
        "Cannot connect to HugeGraph server",
        suggestion="Check if HugeGraph Server is running",
        retryable=True,
        details={"url": "http://127.0.0.1:8080"},
    )

    assert result["ok"] is False
    assert result["data"] is None
    assert result["error"]["type"] == "CONNECTION_FAILED"
    assert result["error"]["message"] == "Cannot connect to HugeGraph server"
    assert result["error"]["suggestion"] == "Check if HugeGraph Server is running"
    assert result["error"]["retryable"] is True
    assert result["error"]["source"] == "hugegraph-mcp"
    assert result["error"]["details"] == {"url": "http://127.0.0.1:8080"}
    assert result["warnings"] == []


def test_envelope_err_defaults():
    """suggestion defaults to None, retryable to False, source to hugegraph-mcp, details to {}."""
    result = envelope_err(ErrorType.TIMEOUT, "Request timed out")

    assert result["error"]["suggestion"] is None
    assert result["error"]["retryable"] is False
    assert result["error"]["source"] == "hugegraph-mcp"
    assert result["error"]["details"] == {}


def test_envelope_err_all_error_types():
    assert len(ErrorType) == 26
    assert ErrorType.VALIDATION_ERROR.value == "VALIDATION_ERROR"
    assert ErrorType.PLAN_EXPIRED.value == "PLAN_EXPIRED"
    assert ErrorType.PLAN_ALREADY_USED.value == "PLAN_ALREADY_USED"
    assert ErrorType.WRITE_CONFLICT.value == "WRITE_CONFLICT"
    assert ErrorType.WRITE_OUTCOME_UNKNOWN.value == "WRITE_OUTCOME_UNKNOWN"
    assert ErrorType.NOT_FOUND.value == "NOT_FOUND"
    assert ErrorType.FEATURE_DISABLED.value == "FEATURE_DISABLED"
    assert ErrorType.QUERY_SYNTAX_ERROR.value == "QUERY_SYNTAX_ERROR"
    assert ErrorType.SERVER_ERROR.value == "SERVER_ERROR"

    for error_type in ErrorType:
        result = envelope_err(error_type, f"{error_type.value} failed")
        assert result["ok"] is False
        assert result["error"]["type"] == error_type.value
        assert result["error"]["message"] == f"{error_type.value} failed"


def test_request_id_unique():
    request_ids = {generate_request_id() for _ in range(100)}

    assert len(request_ids) == 100
    assert all(request_id.startswith("req-") for request_id in request_ids)
    assert all(len(request_id) == len("req-") + 12 for request_id in request_ids)


def test_meta_includes_config_fields():
    result = envelope_ok("ok")

    assert result["meta"]["graph"] == config.graph
    assert result["meta"]["graphspace"] == config.graphspace
    assert result["meta"]["readonly"] == config.readonly


def test_meta_reads_current_env(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_GRAPH", "runtime_graph")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "runtime_space")
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    result = envelope_ok("ok")

    assert result["meta"]["graph"] == "runtime_graph"
    assert result["meta"]["graphspace"] == "runtime_space"
    assert result["meta"]["readonly"] is True


def test_duration_ms_passthrough():
    result = envelope_ok("ok", duration_ms=123)

    assert result["meta"]["duration_ms"] == 123
