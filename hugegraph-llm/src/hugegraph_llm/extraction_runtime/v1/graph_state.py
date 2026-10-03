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

"""Single-authority immutable graph revision state."""

from __future__ import annotations

from hugegraph_llm.extraction_runtime.v1.contracts import GraphSnapshotV1
from hugegraph_llm.extraction_runtime.v1.errors import RuntimeInvariantError, StaleGraphError
from hugegraph_llm.extraction_runtime.v1.json_value import JsonObject, digest_json, freeze_json_object


class GraphStateV1:
    """Own exactly one authoritative immutable graph snapshot."""

    def __init__(self) -> None:
        self._current: GraphSnapshotV1 | None = None

    @property
    def current(self) -> GraphSnapshotV1 | None:
        return self._current

    def promote_initial(self, candidate_graph: JsonObject) -> GraphSnapshotV1:
        if self._current is not None:
            raise RuntimeInvariantError("initial graph has already been promoted")
        snapshot = self._build_snapshot(candidate_graph, revision=0)
        self._current = snapshot
        return snapshot

    def promote_repair(self, candidate_graph: JsonObject, *, expected_base_digest: str) -> GraphSnapshotV1:
        current = self._current
        if current is None:
            raise RuntimeInvariantError("cannot promote a repair before the initial graph")
        if expected_base_digest != current.graph_digest:
            raise StaleGraphError(f"repair targets {expected_base_digest!r}, current graph is {current.graph_digest!r}")
        snapshot = self._build_snapshot(candidate_graph, revision=current.revision + 1)
        self._current = snapshot
        return snapshot

    @staticmethod
    def _build_snapshot(candidate_graph: JsonObject, *, revision: int) -> GraphSnapshotV1:
        frozen = freeze_json_object(candidate_graph)
        return GraphSnapshotV1(revision=revision, graph=frozen, graph_digest=digest_json(frozen))
