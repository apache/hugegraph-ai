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

import unittest
from unittest.mock import Mock

import pytest
import requests
from pyhugegraph.utils.exceptions import NotAuthorizedError, NotFoundError, ResponseParseError, ServerError
from pyhugegraph.utils.util import ResponseValidation, check_if_success, redact_sensitive_data

pytestmark = pytest.mark.contract


class TestResponseValidation(unittest.TestCase):
    def _mock_error_response(self, body, text):
        response = Mock(spec=requests.Response)
        response.status_code = 400
        response.text = text
        response.content = response.text.encode("utf-8")
        response.json.return_value = body
        response.request = Mock()
        response.request.body = "g.V2()"
        response.raise_for_status.side_effect = requests.exceptions.HTTPError("400 Client Error")
        return response

    def test_numeric_status_body_raises_server_exception_with_message(self):
        response = self._mock_error_response(
            {"status": 400, "message": "bad gremlin"},
            '{"status":400,"message":"bad gremlin"}',
        )
        validator = ResponseValidation()

        with self.assertRaisesRegex(Exception, "Server Exception: bad gremlin"):
            validator(response, "POST", "/gremlin")

    def test_non_dict_json_body_raises_server_exception_with_response_text(self):
        response = self._mock_error_response(["bad gremlin"], "bad gremlin")
        validator = ResponseValidation()

        with self.assertRaisesRegex(Exception, "Server Exception: bad gremlin"):
            validator(response, "POST", "/gremlin")

    def test_backend_error_envelope_preserves_message(self):
        response = Mock(spec=requests.Response)
        response.status_code = 500
        response.text = '{"exception":"BackendException","message":"quality failure"}'
        response.content = response.text.encode("utf-8")
        response.json.return_value = {"exception": "BackendException", "message": "quality failure"}
        response.request = Mock(body='{"gremlin":"g.V2()"}', url="http://127.0.0.1:8080/gremlin")
        response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        validator = ResponseValidation()

        with pytest.raises(Exception) as exc_info:
            validator(response, method="POST", path="/gremlin")

        assert "quality failure" in str(exc_info.value)

    def test_malformed_error_body_uses_response_text(self):
        response = self._mock_error_response(ValueError("not json"), "not json")
        response.json.side_effect = ValueError("not json")
        validator = ResponseValidation()

        with self.assertRaisesRegex(Exception, "Server Exception: not json"):
            validator(response, "POST", "/gremlin")

    def test_unauthorized_error_preserves_not_authorized_type(self):
        response = Mock(spec=requests.Response)
        response.status_code = 401
        response.text = '{"exception":"NotAuthorizedException","message":"Authentication failed"}'
        response.content = response.text.encode("utf-8")
        response.request = Mock(body="Empty body", url="http://127.0.0.1:8080/graphs")
        response.raise_for_status.side_effect = requests.exceptions.HTTPError("401 Client Error")
        validator = ResponseValidation()

        with pytest.raises(NotAuthorizedError) as exc_info:
            validator(response, method="GET", path="/graphs")

        assert "Please check your username and password" in str(exc_info.value)

    def test_malformed_success_json_raises_parse_error(self):
        response = Mock(spec=requests.Response)
        response.status_code = 200
        response.text = "not json"
        response.content = b"not json"
        response.json.side_effect = ValueError("not json")
        response.raise_for_status.return_value = None
        validator = ResponseValidation()

        with pytest.raises(ResponseParseError, match="Failed to parse json response"):
            validator(response, "GET", "/graphs/hugegraph")

    def test_unknown_content_type_raises_value_error_without_wrapping(self):
        response = Mock(spec=requests.Response)
        validator = ResponseValidation(content_type="xml")

        with pytest.raises(ValueError, match="Unknown content type: xml"):
            validator(response, "GET", "/graphs/hugegraph")

    def test_strict_404_preserves_not_found_type(self):
        response = self._mock_error_response(
            {"message": "missing vertex"},
            '{"message":"missing vertex"}',
        )
        response.status_code = 404
        validator = ResponseValidation()

        with pytest.raises(NotFoundError):
            validator(response, "GET", "/graphs/hugegraph")

    def test_error_log_preserves_plain_utf8_request_body(self):
        response = self._mock_error_response(
            {"message": "bad request"},
            '{"message":"bad request"}',
        )
        response.request.body = "中文 payload"
        validator = ResponseValidation()

        with pytest.raises(ServerError), unittest.mock.patch("pyhugegraph.utils.util.log.error") as log_error:
            validator(response, "POST", "/gremlin")

        assert "中文 payload" in str(log_error.call_args)

    def test_error_log_redacts_sensitive_request_body(self):
        response = self._mock_error_response(
            {"message": "bad request"},
            '{"message":"bad request"}',
        )
        response.request.body = '{"user_name":"marko","user_password":"super-secret"}'
        validator = ResponseValidation()

        with pytest.raises(ServerError), unittest.mock.patch("pyhugegraph.utils.util.log.error") as log_error:
            validator(response, "POST", "/auth/users")

        logged_args = str(log_error.call_args)
        assert "super-secret" not in logged_args
        assert "***REDACTED***" in logged_args

    def test_check_if_success_redacts_sensitive_response_body(self):
        response = self._mock_error_response(
            {"message": "bad request"},
            '{"message":"token=server-secret"}',
        )
        response.request.body = '{"query":"g.V()"}'

        with pytest.raises(NotFoundError), unittest.mock.patch("pyhugegraph.utils.util.log.error") as log_error:
            check_if_success(response)

        logged_args = str(log_error.call_args)
        assert "server-secret" not in logged_args
        assert "***REDACTED***" in logged_args

    def test_redact_sensitive_data_returns_non_sensitive_string_unchanged(self):
        plain_body = "large non-sensitive payload with unicode 中文"

        assert redact_sensitive_data(plain_body) == plain_body


if __name__ == "__main__":
    unittest.main()
