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
from pyhugegraph.utils.exceptions import NotAuthorizedError
from pyhugegraph.utils.util import ResponseValidation

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


if __name__ == "__main__":
    unittest.main()
