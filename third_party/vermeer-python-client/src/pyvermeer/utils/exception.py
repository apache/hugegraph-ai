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


class ConnectError(Exception):
    """Raised when there is an issue connecting to the server."""

    def __init__(self, message):
        super().__init__(f"Connection error: {message!s}")


class TimeOutError(Exception):
    """Raised when a request times out."""

    def __init__(self, message):
        super().__init__(f"Request timed out: {message!s}")


class JsonDecodeError(Exception):
    """Raised when the response from the server cannot be decoded as JSON."""

    def __init__(self, message):
        super().__init__(f"Failed to decode JSON response: {message!s}")


class UnknownError(Exception):
    """Raised for any other unknown errors."""

    def __init__(self, message):
        super().__init__(f"Unknown API error: {message!s}")
