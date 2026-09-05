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

"""Python 3.10-compatible typed control contracts for extraction runtime v1."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from hugegraph_llm.extraction_runtime.v1.json_value import (
    JsonObject,
    digest_json,
    ensure_credential_free,
    freeze_json_object,
)


def _freeze_objects(values: tuple[JsonObject, ...]) -> tuple[JsonObject, ...]:
    frozen = tuple(freeze_json_object(value) for value in values)
    for index, value in enumerate(frozen):
        ensure_credential_free(value, path=f"$[{index}]")
    return frozen


def _freeze_credential_free(value: JsonObject, *, path: str) -> JsonObject:
    frozen = freeze_json_object(value)
    ensure_credential_free(frozen, path=path)
    return frozen


class TerminalKind(str, Enum):
    FINAL = "final"
    CANDIDATE = "candidate"
    BLOCKED = "blocked"
    FAILED = "failed"


class ReviewDisposition(str, Enum):
    PASS = "pass"
    FIX = "fix"
    BLOCK = "block"


class GateDisposition(str, Enum):
    PASS = "pass"
    HOLD = "hold"
    BLOCK = "block"


class FailureDisposition(str, Enum):
    RETRY = "retry"
    CANDIDATE = "candidate"
    BLOCKED = "blocked"
    FAILED = "failed"


class RepairReason(str, Enum):
    SCHEMA = "schema"
    IDENTITY = "identity"
    REVIEW = "review"


@dataclass(frozen=True)
class NormalizedChunkV1:
    document_id: str
    chunk_id: str
    ordinal: int
    text: str
    visible_metadata: JsonObject = field(default_factory=dict)
    input_digest: str = ""
    contract: Literal["normalized-chunk/v1"] = "normalized-chunk/v1"

    def __post_init__(self) -> None:
        if not self.document_id:
            raise ValueError("document_id must not be empty")
        if not self.chunk_id:
            raise ValueError("chunk_id must not be empty")
        if self.ordinal < 0:
            raise ValueError("ordinal must be non-negative")
        if self.contract != "normalized-chunk/v1":
            raise ValueError("unsupported normalized chunk contract")
        object.__setattr__(
            self,
            "visible_metadata",
            _freeze_credential_free(self.visible_metadata, path="$.visible_metadata"),
        )


@dataclass(frozen=True)
class GraphSnapshotV1:
    revision: int
    graph: JsonObject
    graph_digest: str

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("graph revision must be non-negative")
        frozen = _freeze_credential_free(self.graph, path="$.graph")
        if digest_json(frozen) != self.graph_digest:
            raise ValueError("graph_digest does not bind the graph payload")
        object.__setattr__(self, "graph", frozen)


@dataclass(frozen=True)
class ValidationOutcomeV1:
    valid: bool
    diagnostics: tuple[JsonObject, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", _freeze_objects(self.diagnostics))


@dataclass(frozen=True)
class IdentityOutcomeV1:
    valid: bool
    identity: JsonObject = field(default_factory=dict)
    diagnostics: tuple[JsonObject, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "identity", _freeze_credential_free(self.identity, path="$.identity"))
        object.__setattr__(self, "diagnostics", _freeze_objects(self.diagnostics))


@dataclass(frozen=True)
class ReviewOutcomeV1:
    disposition: ReviewDisposition
    expected_graph_digest: str
    findings: tuple[JsonObject, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", _freeze_objects(self.findings))


@dataclass(frozen=True)
class RepairOutcomeV1:
    base_graph_digest: str
    candidate_graph: JsonObject
    patch: JsonObject | None = None
    diagnostics: tuple[JsonObject, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_graph",
            _freeze_credential_free(self.candidate_graph, path="$.candidate_graph"),
        )
        if self.patch is not None:
            object.__setattr__(self, "patch", _freeze_credential_free(self.patch, path="$.patch"))
        object.__setattr__(self, "diagnostics", _freeze_objects(self.diagnostics))


@dataclass(frozen=True)
class GateOutcomeV1:
    disposition: GateDisposition
    expected_graph_digest: str
    report: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "report", _freeze_credential_free(self.report, path="$.report"))


@dataclass(frozen=True)
class FailureOutcomeV1:
    disposition: FailureDisposition
    reason_code: str
    retryable: bool
    diagnostics: tuple[JsonObject, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", _freeze_objects(self.diagnostics))


@dataclass(frozen=True)
class RepairRequestV1:
    reason: RepairReason
    expected_graph_digest: str
    context: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", _freeze_credential_free(self.context, path="$.context"))


@dataclass(frozen=True)
class TerminalIntentV1:
    kind: TerminalKind
    reason_code: str
    graph_revision: int | None
    graph_digest: str | None
    retryable: bool

    def as_json_object(self) -> JsonObject:
        return freeze_json_object(
            {
                "kind": self.kind.value,
                "reason_code": self.reason_code,
                "graph_revision": self.graph_revision,
                "graph_digest": self.graph_digest,
                "retryable": self.retryable,
            }
        )


@dataclass(frozen=True)
class TerminalArtifactBodyV1:
    intent: TerminalIntentV1
    graph: JsonObject | None
    review: JsonObject | None
    final_gate: JsonObject | None
    trace_head: str | None
    run_fingerprint: str
    runtime_contract_digest: str
    domain_semantic_digest: str
    provider_execution_digest: str
    input_digest: str
    host_plan_digest: str | None
    contract: Literal["extraction-terminal-body/v1"] = "extraction-terminal-body/v1"

    def __post_init__(self) -> None:
        if self.contract != "extraction-terminal-body/v1":
            raise ValueError("unsupported terminal artifact body contract")
        for name in ("graph", "review", "final_gate"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _freeze_credential_free(value, path=f"$.{name}"))
        if self.graph is None:
            if self.intent.graph_revision is not None or self.intent.graph_digest is not None:
                raise ValueError("terminal intent references a graph missing from the artifact body")
        else:
            if self.intent.graph_revision is None:
                raise ValueError("terminal artifact graph requires an intent graph revision")
            if digest_json(self.graph) != self.intent.graph_digest:
                raise ValueError("terminal intent graph digest does not bind the artifact graph")
        required_digests = (
            self.run_fingerprint,
            self.runtime_contract_digest,
            self.domain_semantic_digest,
            self.provider_execution_digest,
            self.input_digest,
        )
        if not all(required_digests):
            raise ValueError("terminal artifact body requires complete fingerprint layers")

    def as_json_object(self) -> JsonObject:
        return freeze_json_object(
            {
                "contract": self.contract,
                "intent": self.intent.as_json_object(),
                "graph": self.graph,
                "review": self.review,
                "final_gate": self.final_gate,
                "trace_head": self.trace_head,
                "runtime_contract_digest": self.runtime_contract_digest,
                "domain_semantic_digest": self.domain_semantic_digest,
                "provider_execution_digest": self.provider_execution_digest,
                "input_digest": self.input_digest,
                "host_plan_digest": self.host_plan_digest,
                "run_fingerprint": self.run_fingerprint,
            }
        )
