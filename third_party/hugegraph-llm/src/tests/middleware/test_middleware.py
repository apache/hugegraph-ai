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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from hugegraph_llm.middleware.middleware import UseTimeMiddleware

pytestmark = pytest.mark.unit


class TestUseTimeMiddlewareInit(unittest.TestCase):
    def setUp(self):
        self.mock_app = MagicMock(spec=FastAPI)

    def test_init(self):
        # Test that the middleware initializes correctly
        middleware = UseTimeMiddleware(self.mock_app)
        self.assertIsInstance(middleware, UseTimeMiddleware)


class TestUseTimeMiddlewareDispatch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mock_app = MagicMock(spec=FastAPI)
        self.middleware = UseTimeMiddleware(self.mock_app)

        # Create a mock request with necessary attributes
        # Use plain MagicMock to avoid AttributeError with FastAPI's read-only properties
        self.mock_request = MagicMock()
        self.mock_request.method = "GET"
        self.mock_request.query_params = {}
        # Create a simple client object to avoid read-only property issues
        self.mock_request.client = type("Client", (), {"host": "127.0.0.1"})()
        self.mock_request.url = "http://localhost:8000/api"

        # Create a mock response with necessary attributes
        # Use plain MagicMock to avoid AttributeError with FastAPI's read-only properties
        self.mock_response = MagicMock()
        self.mock_response.status_code = 200
        self.mock_response.headers = {}

        # Create a mock call_next function
        self.mock_call_next = AsyncMock()
        self.mock_call_next.return_value = self.mock_response

    @patch("time.perf_counter")
    @patch("hugegraph_llm.middleware.middleware.log")
    async def test_dispatch(self, mock_log, mock_time):
        # Setup mock time to return specific values on consecutive calls
        mock_time.side_effect = [100.0, 100.5]  # Start time, end time (0.5s difference)

        # Call the dispatch method
        result = await self.middleware.dispatch(self.mock_request, self.mock_call_next)

        # Verify call_next was called with the request
        self.mock_call_next.assert_called_once_with(self.mock_request)

        # Verify the response headers were set correctly
        self.assertEqual(self.mock_response.headers["X-Process-Time"], "500.00 ms")

        # Verify log.info was called with the correct arguments
        mock_log.info.assert_any_call("Request process time: %.2f ms, code=%d", 500.0, 200)
        mock_log.info.assert_any_call(
            "%s - Args: %s, IP: %s, URL: %s", "GET", {}, "127.0.0.1", "http://localhost:8000/api"
        )

        # Verify the result is the response
        self.assertEqual(result, self.mock_response)


if __name__ == "__main__":
    unittest.main()
