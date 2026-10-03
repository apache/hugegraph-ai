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

"""Experimental versioned extraction contracts and chunk execution."""

from hugegraph_llm.extraction_runtime.v1.artifacts import build_terminal_artifact_body
from hugegraph_llm.extraction_runtime.v1.batch import ChunkRunResultV1, run_chunks_v1
from hugegraph_llm.extraction_runtime.v1.contracts import (
    FailureDisposition,
    FailureOutcomeV1,
    GateDisposition,
    GateOutcomeV1,
    GraphSnapshotV1,
    IdentityOutcomeV1,
    NormalizedChunkV1,
    RepairOutcomeV1,
    RepairReason,
    RepairRequestV1,
    ReviewDisposition,
    ReviewOutcomeV1,
    TerminalArtifactBodyV1,
    TerminalIntentV1,
    TerminalKind,
    ValidationOutcomeV1,
)
from hugegraph_llm.extraction_runtime.v1.diagnostics import DiagnosticSeverity, DiagnosticV1
from hugegraph_llm.extraction_runtime.v1.engine import (
    ExtractionBundleV1,
    ExtractionEngineV1,
    ExtractionRunResultV1,
    RunControlV1,
)
from hugegraph_llm.extraction_runtime.v1.errors import (
    ArtifactConstructionError,
    BudgetExhaustedError,
    ExtractionRuntimeError,
    InvalidGraphError,
    RepairStageError,
    RuntimeInvariantError,
    StaleGraphError,
)
from hugegraph_llm.extraction_runtime.v1.fingerprint import (
    FingerprintLayersV1,
    compose_run_fingerprint,
    compute_input_digest,
)
from hugegraph_llm.extraction_runtime.v1.graph_state import GraphStateV1
from hugegraph_llm.extraction_runtime.v1.json_value import JsonObject, JsonValue, canonical_json, digest_json
from hugegraph_llm.extraction_runtime.v1.manifest import DomainSemanticManifestV1, SemanticResourceV1
from hugegraph_llm.extraction_runtime.v1.review_loop import ReviewBudgetStateV1, ReviewBudgetV1
from hugegraph_llm.extraction_runtime.v1.terminal import (
    TerminalEvidenceV1,
    TerminalResolutionV1,
    resolve_terminal,
)
from hugegraph_llm.extraction_runtime.v1.trace import TraceEventV1, TraceRecorderV1

__all__ = [
    "ArtifactConstructionError",
    "BudgetExhaustedError",
    "ChunkRunResultV1",
    "DiagnosticSeverity",
    "DiagnosticV1",
    "DomainSemanticManifestV1",
    "ExtractionBundleV1",
    "ExtractionEngineV1",
    "ExtractionRunResultV1",
    "ExtractionRuntimeError",
    "FailureDisposition",
    "FailureOutcomeV1",
    "FingerprintLayersV1",
    "GateDisposition",
    "GateOutcomeV1",
    "GraphSnapshotV1",
    "GraphStateV1",
    "IdentityOutcomeV1",
    "InvalidGraphError",
    "JsonObject",
    "JsonValue",
    "NormalizedChunkV1",
    "RepairOutcomeV1",
    "RepairReason",
    "RepairRequestV1",
    "RepairStageError",
    "ReviewBudgetStateV1",
    "ReviewBudgetV1",
    "ReviewDisposition",
    "ReviewOutcomeV1",
    "RunControlV1",
    "RuntimeInvariantError",
    "SemanticResourceV1",
    "StaleGraphError",
    "TerminalArtifactBodyV1",
    "TerminalEvidenceV1",
    "TerminalIntentV1",
    "TerminalKind",
    "TerminalResolutionV1",
    "TraceEventV1",
    "TraceRecorderV1",
    "ValidationOutcomeV1",
    "build_terminal_artifact_body",
    "canonical_json",
    "compose_run_fingerprint",
    "compute_input_digest",
    "digest_json",
    "resolve_terminal",
    "run_chunks_v1",
]
