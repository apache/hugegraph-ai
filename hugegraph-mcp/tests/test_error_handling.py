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

"""Test improved error handling for Gremlin operations."""

from unittest.mock import Mock, patch

import pytest
import requests
from pyhugegraph.utils.exceptions import (
    DataFormatError,
    InvalidParameterError,
    NotAuthorizedError,
    NotFoundError,
    ResponseParseError,
    ServerError,
    ServiceUnavailableError,
)

from hugegraph_mcp.confirmable_workflow import (
    confirm_required_error,
    mark_readonly_preview,
    plan_hash_error,
)
from hugegraph_mcp.envelope import (
    REDACTED_VALUE,
    ErrorType,
    envelope_err,
    sanitize_for_response,
)
from hugegraph_mcp.error_mapping import (
    classify_hugegraph_error_message,
    classify_hugegraph_exception,
)
from hugegraph_mcp.gremlin_tools import execute_gremlin_read, execute_gremlin_write


def test_connection_error_handling():
    """Test handling of connection errors."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.side_effect = requests.exceptions.ConnectionError(
            "Connection refused"
        )
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().count()")

        assert result["ok"] is False
        assert result["error"]["type"] == "CONNECTION_FAILED"
        assert "Cannot connect to HugeGraph server" in result["error"]["message"]
        assert "Check if HugeGraph server is running" in result["error"]["suggestion"]
        assert result["error"]["details"]["error_type"] == "connection_error"
    assert result["error"]["retryable"] is True


@pytest.mark.parametrize("exc_type", [InvalidParameterError, DataFormatError])
def test_generic_parameter_errors_are_validation_errors(exc_type):
    classification = classify_hugegraph_exception(exc_type("invalid value"))

    assert classification.error_type == ErrorType.VALIDATION_ERROR
    assert classification.reason == "validation_error"
    assert classification.retryable is False


@pytest.mark.parametrize("exc_type", [InvalidParameterError, DataFormatError])
def test_gremlin_parameter_errors_remain_query_syntax_errors(exc_type):
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client.return_value.exec.side_effect = exc_type("invalid query")
        result = execute_gremlin_read("g.V().limit(10)")

    assert result["error"]["type"] == "QUERY_SYNTAX_ERROR"
    assert result["error"]["retryable"] is False


def test_read_client_initialization_connection_error_is_enveloped():
    """Connection failures while constructing the client should not escape."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client.side_effect = requests.exceptions.ConnectionError(
            "Connection refused during init"
        )

        result = execute_gremlin_read("g.V().count()")

        assert result["ok"] is False
        assert result["error"]["type"] == "CONNECTION_FAILED"
        assert "Cannot connect to HugeGraph server" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "connection_error"
        assert result["error"]["retryable"] is True


def test_write_client_initialization_connection_error_is_enveloped(monkeypatch):
    """Write client construction failures should use the same envelope path."""
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    with patch("hugegraph_mcp.gremlin_tools._get_write_client") as mock_client:
        mock_client.side_effect = requests.exceptions.ConnectionError(
            "Connection refused during init"
        )

        result = execute_gremlin_write("g.addV('test')")

        assert result["ok"] is False
        assert result["error"]["type"] == "CONNECTION_FAILED"
        assert "Cannot connect to HugeGraph server" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "connection_error"
        assert result["error"]["retryable"] is True


def test_http_500_error_handling(monkeypatch):
    """Test handling of HTTP 500 server errors."""
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "false")
    monkeypatch.setenv("HUGEGRAPH_MCP_ADMIN_MODE", "true")
    with patch("hugegraph_mcp.gremlin_tools._get_write_client") as mock_client:
        mock_client_instance = Mock()

        # Create a mock response with status code 500
        mock_response = Mock()
        mock_response.status_code = 500
        error = requests.exceptions.HTTPError(
            "Internal Server Error", response=mock_response
        )
        mock_client_instance.exec.side_effect = error
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_write("g.addV('test')")

        assert result["ok"] is False
        assert result["error"]["type"] == "SERVER_ERROR"
        assert "HugeGraph server internal error" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "server_error"
        assert result["error"]["details"]["status_code"] == 500
        assert "Check the Gremlin query syntax" in result["error"]["suggestion"]
        assert result["error"]["retryable"] is True


def test_http_503_error_is_retryable():
    """Temporary 5xx HTTP failures should be retryable."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()

        mock_response = Mock()
        mock_response.status_code = 503
        error = requests.exceptions.HTTPError(
            "Service Unavailable", response=mock_response
        )
        mock_client_instance.exec.side_effect = error
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().limit(10)")

        assert result["ok"] is False
        assert result["error"]["type"] == "SERVER_ERROR"
        assert result["error"]["details"]["error_type"] == "http_error"
        assert result["error"]["details"]["status_code"] == 503
        assert result["error"]["retryable"] is True


def test_http_404_error_handling():
    """Test handling of HTTP 404 graph or endpoint errors."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()

        mock_response = Mock()
        mock_response.status_code = 404
        error = requests.exceptions.HTTPError("Not Found", response=mock_response)
        mock_client_instance.exec.side_effect = error
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().limit(10)")

        assert result["ok"] is False
        assert result["error"]["type"] == "NOT_FOUND"
        assert "Graph or endpoint not found" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "not_found_error"
        assert result["error"]["details"]["status_code"] == 404
        assert result["error"]["retryable"] is False


def test_timeout_error_handling():
    """Test handling of request timeouts."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.side_effect = requests.exceptions.Timeout(
            "Read timed out"
        )
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().count()")

        assert result["ok"] is False
        assert result["error"]["type"] == "TIMEOUT"
        assert "timed out" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "timeout_error"
        assert result["error"]["retryable"] is True


def test_authentication_error_handling():
    """Test handling of authentication errors (401)."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()

        # Create a mock response with status code 401
        mock_response = Mock()
        mock_response.status_code = 401
        error = requests.exceptions.HTTPError("Unauthorized", response=mock_response)
        mock_client_instance.exec.side_effect = error
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().limit(10)")

        assert result["ok"] is False
        assert result["error"]["type"] == "AUTHENTICATION_FAILED"
        assert "Authentication failed" in result["error"]["message"]
        assert "Check HUGEGRAPH_USER" in result["error"]["suggestion"]
        assert result["error"]["details"]["error_type"] == "authentication_error"


def test_pyhugegraph_authentication_error_handling():
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client.return_value.exec.side_effect = NotAuthorizedError(
            "bad credentials"
        )

        result = execute_gremlin_read("g.V().limit(10)")

    assert result["ok"] is False
    assert result["error"]["type"] == "AUTHENTICATION_FAILED"
    assert result["error"]["details"]["error_type"] == "authentication_error"
    assert result["error"]["retryable"] is False


def test_pyhugegraph_not_found_error_handling():
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client.return_value.exec.side_effect = NotFoundError("graph not found")

        result = execute_gremlin_read("g.V().limit(10)")

    assert result["ok"] is False
    assert result["error"]["type"] == "NOT_FOUND"
    assert result["error"]["details"]["error_type"] == "not_found_error"
    assert result["error"]["retryable"] is False


def test_pyhugegraph_server_error_preserves_no_index_classification():
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client.return_value.exec.side_effect = ServerError(
            "Server Exception: NoIndexException"
        )

        result = execute_gremlin_read("g.V().has('name', 'alice').limit(10)")

    assert result["ok"] is False
    assert result["error"]["type"] == "NO_INDEX"
    assert result["error"]["details"]["error_type"] == "no_index_error"
    assert result["error"]["retryable"] is False


@pytest.mark.parametrize(
    ("exception", "expected_retryable"),
    [
        (ResponseParseError("invalid response"), False),
        (ServiceUnavailableError("temporarily unavailable"), True),
    ],
)
def test_pyhugegraph_server_error_preserves_retryable_classification(
    exception, expected_retryable
):
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client.return_value.exec.side_effect = exception

        result = execute_gremlin_read("g.V().limit(10)")

    assert result["ok"] is False
    assert result["error"]["type"] == "SERVER_ERROR"
    assert result["error"]["retryable"] is expected_retryable


def test_readonly_mode_error():
    """Test readonly mode error handling."""
    with patch.dict("os.environ", {"HUGEGRAPH_MCP_READONLY": "true"}):
        result = execute_gremlin_write("g.addV('test')")

        assert result["ok"] is False
        assert result["error"]["type"] == "READONLY_VIOLATION"
        assert result["meta"]["readonly"] is True


def test_validation_error_for_read_operations():
    """Test validation error when trying to use write keywords in read operations."""
    result = execute_gremlin_read("g.addV('test')")

    assert result["ok"] is False
    assert result["error"]["type"] == "UNSAFE_GREMLIN"
    assert "write" in result["error"]["message"].lower()


def test_syntax_error_handling():
    """Test handling of Gremlin syntax errors."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.side_effect = ValueError("Invalid Gremlin syntax")
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().count()")

        assert result["ok"] is False
        assert result["error"]["type"] == "QUERY_SYNTAX_ERROR"
        assert "syntax error" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "query_syntax_error"
        assert result["error"]["retryable"] is False


def test_unknown_error_handling():
    """Test handling of unexpected errors."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.side_effect = RuntimeError("Unexpected error")
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().count()")

        assert result["ok"] is False
        assert result["error"]["type"] == "SERVER_ERROR"
        assert "Unexpected error" in result["error"]["message"]
        assert result["error"]["details"]["error_type"] == "unknown_error"


def test_no_index_exception_is_classified_as_no_index():
    """HugeGraph NoIndexException should not be reported as a connection failure."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.side_effect = RuntimeError(
            "Gremlin can't get results: Server Exception: "
            "org.apache.hugegraph.exception.NoIndexException"
        )
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().has('occupation','engineer')")

        assert result["ok"] is False
        assert result["error"]["type"] == "NO_INDEX"
        assert result["error"]["details"]["error_type"] == "no_index_error"
        assert "Create an index" in result["error"]["suggestion"]
        assert result["error"]["retryable"] is False


def test_hugegraph_error_mapping_recognizes_no_index_message_variants():
    messages = [
        "NoIndexException: no index",
        "The property key 'name' is not indexed",
        "may not match secondary condition without index",
    ]

    for message in messages:
        classification = classify_hugegraph_error_message(message)
        assert classification.error_type == "NO_INDEX"
        assert classification.retryable is False
        assert classification.reason == "no_index"


def test_hugegraph_error_mapping_recognizes_schema_missing_messages():
    messages = [
        "Property key does not exist: age",
        "Edge label does not exist: knows",
    ]

    for message in messages:
        classification = classify_hugegraph_error_message(message)
        assert classification.error_type == "SCHEMA_MISMATCH"
        assert classification.retryable is False
        assert classification.reason == "schema_missing"
        assert "live schema" in classification.suggestion
        assert "label" in classification.suggestion
        assert "property key" in classification.suggestion


def test_hugegraph_error_mapping_recognizes_not_found_message_variants():
    messages = [
        "404 Not Found",
        "Vertex does not exist: 1",
        "edge not found",
    ]

    for message in messages:
        classification = classify_hugegraph_error_message(message)
        assert classification.error_type == "NOT_FOUND"
        assert classification.retryable is False
        assert classification.reason == "not_found"


def test_hugegraph_error_mapping_keeps_no_index_before_schema_missing():
    messages = [
        "NoIndexException: property key does not exist: age",
        "The property key 'age' is not indexed",
    ]

    for message in messages:
        classification = classify_hugegraph_error_message(message)
        assert classification.error_type == "NO_INDEX"
        assert classification.retryable is False
        assert classification.reason == "no_index"


def test_confirmable_workflow_helpers_preserve_standard_envelopes():
    payload, warnings, next_actions = mark_readonly_preview(
        {"confirmable": True},
        warning="readonly warning",
        next_action="rerun dry_run",
    )
    assert payload["confirmable"] is False
    assert payload["readonly_preview_only"] is True
    assert warnings == ["readonly warning"]
    assert next_actions == ["rerun dry_run"]

    confirm_error = confirm_required_error(
        message="confirm required",
        suggestion="run dry_run",
        source="test_tool",
    )
    assert confirm_error["error"]["type"] == "CONFIRM_REQUIRED"
    assert confirm_error["error"]["source"] == "test_tool"

    expired_error = plan_hash_error(
        error_type=ErrorType.PLAN_EXPIRED,
        details={"reason": "expired"},
        mismatch_message="mismatch",
        expired_message="expired",
        suggestion="rerun",
    )
    assert expired_error["error"]["type"] == "PLAN_EXPIRED"
    assert expired_error["error"]["message"] == "expired"


def test_error_envelope_redacts_sensitive_values():
    result = envelope_err(
        ErrorType.SERVER_ERROR,
        "failed password=secret token=abc http://user:pass@example.com/path",
        suggestion="Check Authorization header",
        details={
            "password": "secret",
            "nested": {"access_token": "abc"},
            "url": "http://user:pass@example.com/path?token=abc",
        },
    )

    rendered = str(result)
    assert "secret" not in rendered
    assert "token=abc" not in rendered
    assert "user:pass@" not in rendered
    assert result["error"]["details"]["password"] == "***REDACTED***"
    assert result["error"]["details"]["nested"]["access_token"] == "***REDACTED***"


def test_sanitize_redacts_http_header_format():
    message = "Authorization: Bearer abc123token"

    redacted = sanitize_for_response(message)

    assert "abc123token" not in redacted
    assert redacted == f"Authorization: {REDACTED_VALUE}"


def test_sanitize_redacts_python_dict_repr_format():
    message = "{'Authorization': 'Bearer abc123', 'token': 'xyz'}"

    redacted = sanitize_for_response(message)

    assert "abc123" not in redacted
    assert "xyz" not in redacted
    assert redacted == (
        "{'Authorization': '***REDACTED***', 'token': '***REDACTED***'}"
    )


def test_sanitize_redacts_bare_text_format():
    message = "request failed, token abc123 rejected"

    redacted = sanitize_for_response(message)

    assert "abc123" not in redacted
    assert "request failed" in redacted
    assert "rejected" in redacted
    assert redacted == f"request failed, token {REDACTED_VALUE} rejected"


def test_sanitize_preserves_existing_quoted_json_format():
    message = '{"api_key": "sk-xxx"}'

    redacted = sanitize_for_response(message)

    assert "sk-xxx" not in redacted
    assert redacted == '{"api_key": "***REDACTED***"}'


def test_sanitize_preserves_existing_query_string_format():
    message = "token=abc123&other=1"

    redacted = sanitize_for_response(message)

    assert "abc123" not in redacted
    assert redacted == f"token={REDACTED_VALUE}&other=1"


def test_sanitize_does_not_redact_unrelated_text():
    message = "vertex label already exists: person"

    redacted = sanitize_for_response(message)

    assert redacted == message


def test_sanitize_bare_text_does_not_over_match_short_values():
    message = "the token is invalid"

    redacted = sanitize_for_response(message)

    assert redacted == message
    assert "token is invalid" in redacted


def test_successful_execution_preserves_format():
    """Test that successful execution maintains the expected format."""
    with patch("hugegraph_mcp.gremlin_tools._get_read_client") as mock_client:
        mock_client_instance = Mock()
        mock_client_instance.exec.return_value = [{"id": "1", "label": "person"}]
        mock_client.return_value = mock_client_instance

        result = execute_gremlin_read("g.V().limit(1)")

        assert result["ok"] is True
        assert result["error"] is None
        assert result["data"]["is_read"] is True
        assert result["data"]["total"] == 1
        assert result["data"]["data"] == [{"id": "1", "label": "person"}]
        assert isinstance(result["meta"]["duration_ms"], (int, float))
