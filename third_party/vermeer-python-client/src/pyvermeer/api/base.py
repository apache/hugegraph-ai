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

from pyvermeer.utils.log import log


class BaseModule:
    """Base class"""

    def __init__(self, client):
        self._client = client
        self.log = log.getChild(__name__)

    @property
    def session(self):
        """Return the client's session object"""
        return self._client.session

    def _send_request(self, method: str, endpoint: str, params: dict | None = None):
        """Unified request entry point"""
        self.log.debug(f"Sending {method} to {endpoint}")
        return self._client.send_request(method=method, endpoint=endpoint, params=params)
