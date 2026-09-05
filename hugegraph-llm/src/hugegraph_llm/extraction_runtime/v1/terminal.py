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

"""Four-terminal semantic truth table."""

from __future__ import annotations

from dataclasses import dataclass

from hugegraph_llm.extraction_runtime.v1.contracts import GateDisposition, ReviewDisposition, TerminalKind


@dataclass(frozen=True)
class TerminalEvidenceV1:
    safe_graph: bool = False
    schema_valid: bool = False
    identity_valid: bool = False
    review: ReviewDisposition | None = None
    gate: GateDisposition | None = None
    quality_budget_exhausted: bool = False
    technical_failure: str | None = None


@dataclass(frozen=True)
class TerminalResolutionV1:
    kind: TerminalKind
    reason_code: str
    retryable: bool = False


def resolve_terminal(evidence: TerminalEvidenceV1) -> TerminalResolutionV1:
    """Resolve semantic terminal state with technical and safety precedence."""
    if evidence.technical_failure:
        return TerminalResolutionV1(TerminalKind.FAILED, evidence.technical_failure)
    if evidence.review is ReviewDisposition.BLOCK:
        return TerminalResolutionV1(TerminalKind.BLOCKED, "review_blocked")
    if evidence.gate is GateDisposition.BLOCK:
        return TerminalResolutionV1(TerminalKind.BLOCKED, "gate_blocked")
    if not evidence.safe_graph:
        return TerminalResolutionV1(TerminalKind.BLOCKED, "unsafe_graph")
    if not evidence.schema_valid:
        return TerminalResolutionV1(TerminalKind.BLOCKED, "schema_invalid")
    if not evidence.identity_valid:
        return TerminalResolutionV1(TerminalKind.BLOCKED, "identity_invalid")
    if evidence.quality_budget_exhausted:
        return TerminalResolutionV1(TerminalKind.CANDIDATE, "quality_budget_exhausted")
    if evidence.gate is GateDisposition.HOLD:
        return TerminalResolutionV1(TerminalKind.CANDIDATE, "gate_hold")
    if evidence.review is ReviewDisposition.PASS and evidence.gate is GateDisposition.PASS:
        return TerminalResolutionV1(TerminalKind.FINAL, "accepted")
    return TerminalResolutionV1(TerminalKind.FAILED, "incomplete_terminal_evidence")
