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

import json
from dataclasses import FrozenInstanceError

import pytest

from hugegraph_llm.extraction_runtime.v1 import (
    FailureDisposition,
    FailureOutcomeV1,
    GateDisposition,
    GateOutcomeV1,
    GraphSnapshotV1,
    IdentityOutcomeV1,
    NormalizedChunkV1,
    RepairOutcomeV1,
    ReviewDisposition,
    ReviewOutcomeV1,
    TerminalArtifactBodyV1,
    TerminalIntentV1,
    TerminalKind,
    ValidationOutcomeV1,
    canonical_json,
    digest_json,
)

pytestmark = pytest.mark.contract


def test_control_contracts_are_typed_and_frozen() -> None:
    chunk = NormalizedChunkV1(
        document_id="inventory",
        chunk_id="inventory-0",
        ordinal=0,
        text="two bolts",
        visible_metadata={"source": "fixture"},
        input_digest="sha256:input",
    )
    validation = ValidationOutcomeV1(valid=True)
    identity = IdentityOutcomeV1(valid=True, identity={"keys": ["bolt"]})
    review = ReviewOutcomeV1(
        disposition=ReviewDisposition.PASS,
        expected_graph_digest="sha256:graph",
        findings=({"code": "ok"},),
    )
    repair = RepairOutcomeV1(
        base_graph_digest="sha256:graph",
        candidate_graph={"items": [{"name": "bolt"}]},
        patch={"replace": "items"},
    )
    gate = GateOutcomeV1(
        disposition=GateDisposition.PASS,
        expected_graph_digest="sha256:graph",
        report={"accepted": True},
    )
    failure = FailureOutcomeV1(
        disposition=FailureDisposition.FAILED,
        reason_code="provider_protocol",
        retryable=False,
    )
    graph = {"items": [{"name": "bolt"}]}
    graph_digest = digest_json(graph)
    intent = TerminalIntentV1(
        kind=TerminalKind.FINAL,
        reason_code="accepted",
        graph_revision=0,
        graph_digest=graph_digest,
        retryable=False,
    )
    artifact = TerminalArtifactBodyV1(
        intent=intent,
        graph=graph,
        review={"disposition": "pass"},
        final_gate={"disposition": "pass"},
        trace_head="sha256:trace",
        run_fingerprint="sha256:run",
        runtime_contract_digest="sha256:runtime",
        domain_semantic_digest="sha256:domain",
        provider_execution_digest="sha256:provider",
        input_digest="sha256:input",
        host_plan_digest=None,
    )

    assert chunk.contract == "normalized-chunk/v1"
    assert validation.valid and identity.valid
    assert review.disposition is ReviewDisposition.PASS
    assert repair.patch == {"replace": "items"}
    assert gate.disposition is GateDisposition.PASS
    assert failure.disposition is FailureDisposition.FAILED
    assert artifact.contract == "extraction-terminal-body/v1"
    assert artifact.intent.kind is TerminalKind.FINAL
    serialized = json.loads(canonical_json(artifact.as_json_object()))
    assert serialized["intent"]["kind"] == "final"
    assert serialized["graph"] == graph
    with pytest.raises(FrozenInstanceError):
        chunk.text = "mutated"  # type: ignore[misc]


def test_graph_and_control_payloads_reject_credential_fields() -> None:
    graph = {"vertices": [{"password": "not-a-real-password"}]}  # pragma: allowlist secret
    with pytest.raises(ValueError, match="credential"):
        GraphSnapshotV1(revision=0, graph=graph, graph_digest=digest_json(graph))
    with pytest.raises(ValueError, match="credential"):
        ReviewOutcomeV1(
            disposition=ReviewDisposition.PASS,
            expected_graph_digest="digest",
            findings=({"authorization": "not-a-real-credential"},),
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"document_id": "", "chunk_id": "x", "ordinal": 0, "text": "x"}, "document_id"),
        ({"document_id": "d", "chunk_id": "", "ordinal": 0, "text": "x"}, "chunk_id"),
        ({"document_id": "d", "chunk_id": "x", "ordinal": -1, "text": "x"}, "ordinal"),
    ],
)
def test_normalized_chunk_rejects_invalid_control_fields(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        NormalizedChunkV1(**kwargs)  # type: ignore[arg-type]
