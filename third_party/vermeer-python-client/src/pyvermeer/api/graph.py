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

from pyvermeer.structure.graph_data import GraphResponse, GraphsResponse

from .base import BaseModule


class GraphModule(BaseModule):
    """Graph"""

    def get_graph(self, graph_name: str) -> GraphResponse:
        """Get task list"""
        response = self._send_request("GET", f"/graphs/{graph_name}")
        return GraphResponse(response)

    def get_graphs(self) -> GraphsResponse:
        """Get task list"""
        response = self._send_request(
            "GET",
            "/graphs",
        )
        return GraphsResponse(response)
