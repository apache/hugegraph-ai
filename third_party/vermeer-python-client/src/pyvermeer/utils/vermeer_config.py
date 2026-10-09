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


class VermeerConfig:
    """The configuration of a Vermeer instance."""

    ip: str
    port: int
    token: str
    factor: str
    username: str
    graph_space: str

    def __init__(self, ip: str, port: int, token: str, timeout: tuple[float, float] = (0.5, 15.0)):
        """Initialize the configuration for a Vermeer instance."""
        self.ip = ip
        self.port = port
        self.token = token
        self.timeout = timeout
