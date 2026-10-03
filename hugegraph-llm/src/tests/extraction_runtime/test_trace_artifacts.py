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

import pytest

from hugegraph_llm.extraction_runtime.v1 import (
    FingerprintLayersV1,
    GraphStateV1,
    RuntimeInvariantError,
    TerminalIntentV1,
    TerminalKind,
    TraceRecorderV1,
    build_terminal_artifact_body,
)

pytestmark = pytest.mark.unit


def test_trace_is_deterministic_hash_chain_without_volatile_fields() -> None:
    graph = GraphStateV1().promote_initial({"items": [{"sku": "A"}]})
    first = TraceRecorderV1().append("extract", "promoted", graph, {"source": "replay"})
    second = first.append("schema", "pass", graph, {})
    repeated = (
        TraceRecorderV1().append("extract", "promoted", graph, {"source": "replay"}).append("schema", "pass", graph, {})
    )

    assert [event.sequence for event in second.events] == [0, 1]
    assert second.trace_head == repeated.trace_head
    assert second.events[1].previous_head == second.events[0].event_digest


def test_trace_rejects_credential_details() -> None:
    with pytest.raises(ValueError, match="credential"):
        TraceRecorderV1().append(
            "extract",
            "failed",
            None,
            {"api_key": "not-a-real-key"},  # pragma: allowlist secret
        )


def test_artifact_body_requires_intent_and_graph_consistency() -> None:
    graph = GraphStateV1().promote_initial({"items": [{"sku": "A"}]})
    trace = TraceRecorderV1().append("terminal", "final", graph, {})
    intent = TerminalIntentV1(
        kind=TerminalKind.FINAL,
        reason_code="accepted",
        graph_revision=graph.revision,
        graph_digest=graph.graph_digest,
        retryable=False,
    )

    artifact = build_terminal_artifact_body(
        intent=intent,
        graph=graph,
        review={"disposition": "pass"},
        final_gate={"disposition": "pass"},
        trace_head=trace.trace_head,
        fingerprints=FingerprintLayersV1(
            runtime_contract_digest="sha256:runtime",
            domain_semantic_digest="sha256:domain",
            provider_execution_digest="sha256:provider",
            input_digest="sha256:input",
            host_plan_digest=None,
            run_fingerprint="sha256:run",
        ),
    )
    assert artifact.graph == graph.graph
    assert artifact.trace_head == trace.trace_head

    with pytest.raises(RuntimeInvariantError, match="digest"):
        build_terminal_artifact_body(
            intent=TerminalIntentV1(
                kind=TerminalKind.FINAL,
                reason_code="accepted",
                graph_revision=graph.revision,
                graph_digest="sha256:wrong",
                retryable=False,
            ),
            graph=graph,
            review=None,
            final_gate=None,
            trace_head=trace.trace_head,
            fingerprints=FingerprintLayersV1(
                runtime_contract_digest="sha256:runtime",
                domain_semantic_digest="sha256:domain",
                provider_execution_digest="sha256:provider",
                input_digest="sha256:input",
                host_plan_digest=None,
                run_fingerprint="sha256:run",
            ),
        )
