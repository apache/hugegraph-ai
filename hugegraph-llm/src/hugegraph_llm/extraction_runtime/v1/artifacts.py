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

"""Pure terminal artifact body construction with no storage I/O."""

from __future__ import annotations

from hugegraph_llm.extraction_runtime.v1.contracts import (
    GraphSnapshotV1,
    TerminalArtifactBodyV1,
    TerminalIntentV1,
)
from hugegraph_llm.extraction_runtime.v1.errors import RuntimeInvariantError
from hugegraph_llm.extraction_runtime.v1.fingerprint import FingerprintLayersV1
from hugegraph_llm.extraction_runtime.v1.json_value import JsonObject


def build_terminal_artifact_body(
    *,
    intent: TerminalIntentV1,
    graph: GraphSnapshotV1 | None,
    review: JsonObject | None,
    final_gate: JsonObject | None,
    trace_head: str | None,
    fingerprints: FingerprintLayersV1,
) -> TerminalArtifactBodyV1:
    if graph is None:
        if intent.graph_revision is not None or intent.graph_digest is not None:
            raise RuntimeInvariantError("terminal intent references a graph when no current graph exists")
    else:
        if intent.graph_revision != graph.revision:
            raise RuntimeInvariantError("terminal intent graph revision does not match current graph")
        if intent.graph_digest != graph.graph_digest:
            raise RuntimeInvariantError("terminal intent graph digest does not match current graph")
    return TerminalArtifactBodyV1(
        intent=intent,
        graph=graph.graph if graph else None,
        review=review,
        final_gate=final_gate,
        trace_head=trace_head,
        run_fingerprint=fingerprints.run_fingerprint,
        runtime_contract_digest=fingerprints.runtime_contract_digest,
        domain_semantic_digest=fingerprints.domain_semantic_digest,
        provider_execution_digest=fingerprints.provider_execution_digest,
        input_digest=fingerprints.input_digest,
        host_plan_digest=fingerprints.host_plan_digest,
    )
