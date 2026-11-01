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

"""Online full-graph algorithms executed as server-side asynchronous jobs.

For immediate neighbourhood and path queries use client.traverser() (OLTP).
"""

from collections.abc import Mapping
from typing import Any

from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.api.task import TaskManager
from pyhugegraph.utils.exceptions import ResponseParseError


class OlapManager(HugeParamsBase):
    def submit(self, name: str, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit a job; custom/server-added algorithm names are accepted."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("algorithm name must be a non-empty string")
        if parameters is not None and not isinstance(parameters, Mapping):
            raise TypeError("parameters must be a mapping")
        receipt = self.request("algorithm.post", path_params={"name": name}, body=dict(parameters or {}))
        if not isinstance(receipt, dict) or "task_id" not in receipt:
            raise ResponseParseError("Algorithm submission response has no task_id")
        return receipt

    def run(
        self, name: str, parameters: Mapping[str, Any] | None = None, *, timeout: float = 300, poll_interval: float = 1
    ) -> Any:
        """Submit, wait and return the decoded result; use submit for asynchronous use."""
        TaskManager.validate_wait(timeout, poll_interval)
        receipt = self.submit(name, parameters)
        tasks = TaskManager(self.session)
        return tasks.result(tasks.wait(receipt["task_id"], timeout, poll_interval))

    # BEGIN GENERATED ALGORITHM METHODS

    def count_edge(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the count_edge full-graph algorithm and return its task receipt."""
        return self.submit("count_edge", parameters)

    def count_vertex(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the count_vertex full-graph algorithm and return its task receipt."""
        return self.submit("count_vertex", parameters)

    def subgraph_stat(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the subgraph_stat full-graph algorithm and return its task receipt."""
        return self.submit("subgraph_stat", parameters)

    def betweenness_centrality(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the betweenness_centrality full-graph algorithm and return its task receipt."""
        return self.submit("betweenness_centrality", parameters)

    def closeness_centrality(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the closeness_centrality full-graph algorithm and return its task receipt."""
        return self.submit("closeness_centrality", parameters)

    def degree_centrality(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the degree_centrality full-graph algorithm and return its task receipt."""
        return self.submit("degree_centrality", parameters)

    def eigenvector_centrality(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the eigenvector_centrality full-graph algorithm and return its task receipt."""
        return self.submit("eigenvector_centrality", parameters)

    def stress_centrality(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the stress_centrality full-graph algorithm and return its task receipt."""
        return self.submit("stress_centrality", parameters)

    def cluster_coefficient(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the cluster_coefficient full-graph algorithm and return its task receipt."""
        return self.submit("cluster_coefficient", parameters)

    def k_core(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the k_core full-graph algorithm and return its task receipt."""
        return self.submit("k_core", parameters)

    def louvain(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the louvain full-graph algorithm and return its task receipt."""
        return self.submit("louvain", parameters)

    def lpa(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the lpa full-graph algorithm and return its task receipt."""
        return self.submit("lpa", parameters)

    def triangle_count(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the triangle_count full-graph algorithm and return its task receipt."""
        return self.submit("triangle_count", parameters)

    def weak_connected_component(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the weak_connected_component full-graph algorithm and return its task receipt."""
        return self.submit("weak_connected_component", parameters)

    def rings(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the rings full-graph algorithm and return its task receipt."""
        return self.submit("rings", parameters)

    def page_rank(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the page_rank full-graph algorithm and return its task receipt."""
        return self.submit("page_rank", parameters)

    def fusiform_similarity(self, parameters: Mapping[str, Any] | None = None) -> dict:
        """Submit the fusiform_similarity full-graph algorithm and return its task receipt."""
        return self.submit("fusiform_similarity", parameters)
