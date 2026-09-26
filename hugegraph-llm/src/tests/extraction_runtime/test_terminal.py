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
    GateDisposition,
    ReviewDisposition,
    TerminalEvidenceV1,
    TerminalKind,
    resolve_terminal,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("evidence", "kind", "reason"),
    [
        (TerminalEvidenceV1(technical_failure="provider_protocol"), TerminalKind.FAILED, "provider_protocol"),
        (
            TerminalEvidenceV1(
                safe_graph=True,
                schema_valid=True,
                identity_valid=True,
                review=ReviewDisposition.BLOCK,
            ),
            TerminalKind.BLOCKED,
            "review_blocked",
        ),
        (
            TerminalEvidenceV1(
                safe_graph=True,
                schema_valid=True,
                identity_valid=True,
                review=ReviewDisposition.PASS,
                gate=GateDisposition.BLOCK,
            ),
            TerminalKind.BLOCKED,
            "gate_blocked",
        ),
        (TerminalEvidenceV1(safe_graph=False), TerminalKind.BLOCKED, "unsafe_graph"),
        (
            TerminalEvidenceV1(
                safe_graph=True,
                schema_valid=True,
                identity_valid=True,
                review=ReviewDisposition.FIX,
                quality_budget_exhausted=True,
            ),
            TerminalKind.CANDIDATE,
            "quality_budget_exhausted",
        ),
        (
            TerminalEvidenceV1(
                safe_graph=True,
                schema_valid=True,
                identity_valid=True,
                review=ReviewDisposition.PASS,
                gate=GateDisposition.HOLD,
            ),
            TerminalKind.CANDIDATE,
            "gate_hold",
        ),
        (
            TerminalEvidenceV1(
                safe_graph=True,
                schema_valid=True,
                identity_valid=True,
                review=ReviewDisposition.PASS,
                gate=GateDisposition.PASS,
            ),
            TerminalKind.FINAL,
            "accepted",
        ),
    ],
)
def test_terminal_truth_table(evidence: TerminalEvidenceV1, kind: TerminalKind, reason: str) -> None:
    resolution = resolve_terminal(evidence)
    assert resolution.kind is kind
    assert resolution.reason_code == reason


def test_incomplete_terminal_evidence_is_a_runtime_failure() -> None:
    resolution = resolve_terminal(
        TerminalEvidenceV1(
            safe_graph=True,
            schema_valid=True,
            identity_valid=True,
            review=ReviewDisposition.PASS,
        )
    )
    assert resolution.kind is TerminalKind.FAILED
    assert resolution.reason_code == "incomplete_terminal_evidence"
