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

"""Deterministic runtime trace hash chain."""

from __future__ import annotations

from dataclasses import dataclass

from hugegraph_llm.extraction_runtime.v1.contracts import GraphSnapshotV1
from hugegraph_llm.extraction_runtime.v1.json_value import (
    JsonObject,
    digest_json,
    ensure_credential_free,
    freeze_json_object,
)


@dataclass(frozen=True)
class TraceEventV1:
    sequence: int
    stage: str
    outcome: str
    graph_revision: int | None
    graph_digest: str | None
    details: JsonObject
    previous_head: str | None
    event_digest: str


@dataclass(frozen=True)
class TraceRecorderV1:
    events: tuple[TraceEventV1, ...] = ()

    @property
    def trace_head(self) -> str | None:
        return self.events[-1].event_digest if self.events else None

    def append(
        self,
        stage: str,
        outcome: str,
        graph: GraphSnapshotV1 | None,
        details: JsonObject | None = None,
    ) -> TraceRecorderV1:
        frozen_details = freeze_json_object(details or {})
        ensure_credential_free(frozen_details, path="$.details")
        payload = {
            "contract": "extraction-trace-event/v1",
            "sequence": len(self.events),
            "stage": stage,
            "outcome": outcome,
            "graph_revision": graph.revision if graph else None,
            "graph_digest": graph.graph_digest if graph else None,
            "details": frozen_details,
            "previous_head": self.trace_head,
        }
        event = TraceEventV1(
            sequence=len(self.events),
            stage=stage,
            outcome=outcome,
            graph_revision=graph.revision if graph else None,
            graph_digest=graph.graph_digest if graph else None,
            details=frozen_details,
            previous_head=self.trace_head,
            event_digest=digest_json(payload),
        )
        return TraceRecorderV1(self.events + (event,))
