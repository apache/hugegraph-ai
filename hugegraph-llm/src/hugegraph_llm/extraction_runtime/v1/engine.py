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

"""Fixed domain-neutral single-chunk extraction engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from hugegraph_llm.extraction_runtime.v1.artifacts import build_terminal_artifact_body
from hugegraph_llm.extraction_runtime.v1.contracts import (
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
from hugegraph_llm.extraction_runtime.v1.errors import ArtifactConstructionError, RepairStageError
from hugegraph_llm.extraction_runtime.v1.fingerprint import FingerprintLayersV1, compose_run_fingerprint
from hugegraph_llm.extraction_runtime.v1.graph_state import GraphStateV1
from hugegraph_llm.extraction_runtime.v1.json_value import (
    JsonObject,
    digest_json,
    ensure_stable_provenance,
    freeze_json_object,
)
from hugegraph_llm.extraction_runtime.v1.manifest import DomainSemanticManifestV1
from hugegraph_llm.extraction_runtime.v1.review_loop import ReviewBudgetStateV1, ReviewBudgetV1
from hugegraph_llm.extraction_runtime.v1.terminal import TerminalEvidenceV1, TerminalResolutionV1, resolve_terminal
from hugegraph_llm.extraction_runtime.v1.trace import TraceRecorderV1


class ExtractionBundleV1(Protocol):
    def semantic_manifest(self) -> DomainSemanticManifestV1: ...

    def extract(self, chunk: NormalizedChunkV1) -> JsonObject: ...

    def validate_schema(self, graph: GraphSnapshotV1, chunk: NormalizedChunkV1) -> ValidationOutcomeV1: ...

    def identify(self, graph: GraphSnapshotV1, chunk: NormalizedChunkV1) -> IdentityOutcomeV1: ...

    def review(
        self,
        graph: GraphSnapshotV1,
        chunk: NormalizedChunkV1,
        validation: ValidationOutcomeV1,
        identity: IdentityOutcomeV1,
    ) -> ReviewOutcomeV1: ...

    def repair(
        self,
        graph: GraphSnapshotV1,
        chunk: NormalizedChunkV1,
        request: RepairRequestV1,
    ) -> RepairOutcomeV1: ...

    def final_gate(
        self,
        graph: GraphSnapshotV1,
        chunk: NormalizedChunkV1,
        validation: ValidationOutcomeV1,
        identity: IdentityOutcomeV1,
        review: ReviewOutcomeV1,
    ) -> GateOutcomeV1: ...


@dataclass(frozen=True)
class RunControlV1:
    budget: ReviewBudgetV1
    provider_execution: JsonObject
    host_plan: JsonObject | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_execution", freeze_json_object(self.provider_execution))
        ensure_stable_provenance(self.provider_execution, path="$.provider_execution")
        if self.host_plan is not None:
            object.__setattr__(self, "host_plan", freeze_json_object(self.host_plan))
            ensure_stable_provenance(self.host_plan, path="$.host_plan")


@dataclass(frozen=True)
class ExtractionRunResultV1:
    intent: TerminalIntentV1
    artifact: TerminalArtifactBodyV1
    current_graph: GraphSnapshotV1 | None
    budget: ReviewBudgetStateV1
    fingerprints: FingerprintLayersV1
    trace: TraceRecorderV1
    diagnostics: tuple[DiagnosticV1, ...]


class ExtractionEngineV1:
    """Execute the v1 fixed lifecycle for one normalized chunk."""

    def run(
        self,
        *,
        bundle: ExtractionBundleV1,
        chunk: NormalizedChunkV1,
        control: RunControlV1,
    ) -> ExtractionRunResultV1:
        graph_state = GraphStateV1()
        budget = ReviewBudgetStateV1(control.budget)
        trace = TraceRecorderV1()
        diagnostics: tuple[DiagnosticV1, ...] = ()

        try:
            fingerprints = compose_run_fingerprint(
                manifest=bundle.semantic_manifest(),
                provider_execution=control.provider_execution,
                chunk=chunk,
                host_plan=control.host_plan,
            )
        except Exception as exc:  # noqa: BLE001 - the runtime maps boundary failures to failed
            return self._failed_without_fingerprints(exc, budget)

        try:
            current = graph_state.promote_initial(bundle.extract(chunk))
            trace = trace.append("extract", "promoted", current, {})
        except Exception as exc:  # noqa: BLE001 - the runtime maps boundary failures to failed
            return self._failed(
                code="extract_failed",
                stage="extract",
                exc=exc,
                graph=graph_state.current,
                budget=budget,
                fingerprints=fingerprints,
                trace=trace,
                diagnostics=diagnostics,
            )

        last_review: ReviewOutcomeV1 | None = None
        while True:
            current = graph_state.current
            if current is None:
                return self._failed(
                    code="runtime_invariant",
                    stage="schema",
                    exc=RuntimeError("current graph disappeared"),
                    graph=None,
                    budget=budget,
                    fingerprints=fingerprints,
                    trace=trace,
                    diagnostics=diagnostics,
                )
            active_stage = "schema"
            try:
                validation = bundle.validate_schema(current, chunk)
                trace = trace.append("schema", "pass" if validation.valid else "invalid", current, {})
                if not validation.valid:
                    if not budget.can_fix:
                        return self._terminal(
                            resolution=resolve_terminal(TerminalEvidenceV1(safe_graph=True, schema_valid=False)),
                            graph=current,
                            budget=budget,
                            fingerprints=fingerprints,
                            trace=trace,
                            diagnostics=diagnostics,
                            review=last_review,
                            gate=None,
                        )
                    active_stage = "repair"
                    graph_state, budget, trace = self._repair(
                        bundle=bundle,
                        chunk=chunk,
                        graph_state=graph_state,
                        budget=budget,
                        trace=trace,
                        reason=RepairReason.SCHEMA,
                    )
                    continue

                active_stage = "identity"
                identity = bundle.identify(current, chunk)
                trace = trace.append("identity", "pass" if identity.valid else "invalid", current, {})
                if not identity.valid:
                    if not budget.can_fix:
                        return self._terminal(
                            resolution=resolve_terminal(
                                TerminalEvidenceV1(safe_graph=True, schema_valid=True, identity_valid=False)
                            ),
                            graph=current,
                            budget=budget,
                            fingerprints=fingerprints,
                            trace=trace,
                            diagnostics=diagnostics,
                            review=last_review,
                            gate=None,
                        )
                    active_stage = "repair"
                    graph_state, budget, trace = self._repair(
                        bundle=bundle,
                        chunk=chunk,
                        graph_state=graph_state,
                        budget=budget,
                        trace=trace,
                        reason=RepairReason.IDENTITY,
                    )
                    continue

                if not budget.can_review:
                    return self._terminal(
                        resolution=resolve_terminal(
                            TerminalEvidenceV1(
                                safe_graph=True,
                                schema_valid=True,
                                identity_valid=True,
                                quality_budget_exhausted=True,
                            )
                        ),
                        graph=current,
                        budget=budget,
                        fingerprints=fingerprints,
                        trace=trace,
                        diagnostics=diagnostics,
                        review=last_review,
                        gate=None,
                    )
                budget = budget.consume_review()
                active_stage = "review"
                last_review = bundle.review(current, chunk, validation, identity)
                self._require_current_digest(last_review.expected_graph_digest, current, "review")
                trace = trace.append("review", last_review.disposition.value, current, {"attempt": budget.reviews_used})
                if last_review.disposition is ReviewDisposition.BLOCK:
                    return self._terminal(
                        resolution=resolve_terminal(
                            TerminalEvidenceV1(
                                safe_graph=True,
                                schema_valid=True,
                                identity_valid=True,
                                review=ReviewDisposition.BLOCK,
                            )
                        ),
                        graph=current,
                        budget=budget,
                        fingerprints=fingerprints,
                        trace=trace,
                        diagnostics=diagnostics,
                        review=last_review,
                        gate=None,
                    )
                if last_review.disposition is ReviewDisposition.FIX:
                    if not budget.can_fix:
                        return self._terminal(
                            resolution=resolve_terminal(
                                TerminalEvidenceV1(
                                    safe_graph=True,
                                    schema_valid=True,
                                    identity_valid=True,
                                    review=ReviewDisposition.FIX,
                                    quality_budget_exhausted=True,
                                )
                            ),
                            graph=current,
                            budget=budget,
                            fingerprints=fingerprints,
                            trace=trace,
                            diagnostics=diagnostics,
                            review=last_review,
                            gate=None,
                        )
                    active_stage = "repair"
                    graph_state, budget, trace = self._repair(
                        bundle=bundle,
                        chunk=chunk,
                        graph_state=graph_state,
                        budget=budget,
                        trace=trace,
                        reason=RepairReason.REVIEW,
                        review=last_review,
                    )
                    continue

                active_stage = "final_gate"
                gate = bundle.final_gate(current, chunk, validation, identity, last_review)
                self._require_current_digest(gate.expected_graph_digest, current, "final_gate")
                trace = trace.append("final_gate", gate.disposition.value, current, {})
                return self._terminal(
                    resolution=resolve_terminal(
                        TerminalEvidenceV1(
                            safe_graph=True,
                            schema_valid=True,
                            identity_valid=True,
                            review=ReviewDisposition.PASS,
                            gate=gate.disposition,
                        )
                    ),
                    graph=current,
                    budget=budget,
                    fingerprints=fingerprints,
                    trace=trace,
                    diagnostics=diagnostics,
                    review=last_review,
                    gate=gate,
                )
            except Exception as exc:  # noqa: BLE001 - Bundle hooks are a typed failure boundary
                if isinstance(exc, RepairStageError):
                    code, stage = "repair_failed", "repair"
                elif isinstance(exc, ArtifactConstructionError):
                    code, stage = "artifact_construction_failed", "artifact"
                else:
                    code, stage = "stage_failed", active_stage
                return self._failed(
                    code=code,
                    stage=stage,
                    exc=exc,
                    graph=graph_state.current,
                    budget=budget,
                    fingerprints=fingerprints,
                    trace=trace,
                    diagnostics=diagnostics,
                )

    @staticmethod
    def _repair(
        *,
        bundle: ExtractionBundleV1,
        chunk: NormalizedChunkV1,
        graph_state: GraphStateV1,
        budget: ReviewBudgetStateV1,
        trace: TraceRecorderV1,
        reason: RepairReason,
        review: ReviewOutcomeV1 | None = None,
    ) -> tuple[GraphStateV1, ReviewBudgetStateV1, TraceRecorderV1]:
        current = graph_state.current
        if current is None:
            raise RuntimeError("repair requires a current graph")
        context: JsonObject = {
            "review_disposition": review.disposition.value if review else None,
            "review_findings": list(review.findings) if review else [],
        }
        try:
            outcome = bundle.repair(
                current,
                chunk,
                RepairRequestV1(reason=reason, expected_graph_digest=current.graph_digest, context=context),
            )
            repaired = graph_state.promote_repair(
                outcome.candidate_graph,
                expected_base_digest=outcome.base_graph_digest,
            )
        except Exception as exc:
            raise RepairStageError("repair candidate was not promoted") from exc
        budget = budget.consume_fix()
        trace = trace.append("repair", "promoted", repaired, {"reason": reason.value, "fix": budget.fixes_used})
        return graph_state, budget, trace

    @staticmethod
    def _require_current_digest(expected: str, current: GraphSnapshotV1, stage: str) -> None:
        if expected != current.graph_digest:
            raise RuntimeError(f"{stage} outcome targets a stale graph digest")

    @staticmethod
    def _outcome_payload(outcome: ReviewOutcomeV1 | GateOutcomeV1 | None) -> JsonObject | None:
        if outcome is None:
            return None
        if isinstance(outcome, ReviewOutcomeV1):
            return {
                "disposition": outcome.disposition.value,
                "expected_graph_digest": outcome.expected_graph_digest,
                "findings": list(outcome.findings),
            }
        return {
            "disposition": outcome.disposition.value,
            "expected_graph_digest": outcome.expected_graph_digest,
            "report": outcome.report,
        }

    def _terminal(
        self,
        *,
        resolution: TerminalResolutionV1,
        graph: GraphSnapshotV1,
        budget: ReviewBudgetStateV1,
        fingerprints: FingerprintLayersV1,
        trace: TraceRecorderV1,
        diagnostics: tuple[DiagnosticV1, ...],
        review: ReviewOutcomeV1 | None,
        gate: GateOutcomeV1 | None,
    ) -> ExtractionRunResultV1:
        kind = resolution.kind
        reason_code = resolution.reason_code
        retryable = resolution.retryable
        trace = trace.append("terminal", kind.value, graph, {"reason_code": reason_code})
        intent = TerminalIntentV1(
            kind=kind,
            reason_code=reason_code,
            graph_revision=graph.revision,
            graph_digest=graph.graph_digest,
            retryable=retryable,
        )
        try:
            artifact = build_terminal_artifact_body(
                intent=intent,
                graph=graph,
                review=self._outcome_payload(review),
                final_gate=self._outcome_payload(gate),
                trace_head=trace.trace_head,
                fingerprints=fingerprints,
            )
        except Exception as exc:
            raise ArtifactConstructionError("terminal artifact body construction failed") from exc
        return ExtractionRunResultV1(intent, artifact, graph, budget, fingerprints, trace, diagnostics)

    def _failed(
        self,
        *,
        code: str,
        stage: str,
        exc: Exception,
        graph: GraphSnapshotV1 | None,
        budget: ReviewBudgetStateV1,
        fingerprints: FingerprintLayersV1,
        trace: TraceRecorderV1,
        diagnostics: tuple[DiagnosticV1, ...],
    ) -> ExtractionRunResultV1:
        diagnostic = DiagnosticV1(
            code=code,
            stage=stage,
            severity=DiagnosticSeverity.ERROR,
            details={"exception_type": type(exc.__cause__ or exc).__name__},
        )
        diagnostics += (diagnostic,)
        trace = trace.append("terminal", TerminalKind.FAILED.value, graph, {"reason_code": code})
        intent = TerminalIntentV1(
            kind=TerminalKind.FAILED,
            reason_code=code,
            graph_revision=graph.revision if graph else None,
            graph_digest=graph.graph_digest if graph else None,
            retryable=False,
        )
        artifact = build_terminal_artifact_body(
            intent=intent,
            graph=graph,
            review=None,
            final_gate=None,
            trace_head=trace.trace_head,
            fingerprints=fingerprints,
        )
        return ExtractionRunResultV1(intent, artifact, graph, budget, fingerprints, trace, diagnostics)

    def _failed_without_fingerprints(
        self,
        exc: Exception,
        budget: ReviewBudgetStateV1,
    ) -> ExtractionRunResultV1:
        failure_digest = digest_json({"contract": "untrusted-fingerprint-failure/v1"})
        fallback = FingerprintLayersV1(
            failure_digest,
            failure_digest,
            failure_digest,
            failure_digest,
            None,
            failure_digest,
        )
        return self._failed(
            code="fingerprint_failed",
            stage="fingerprint",
            exc=exc,
            graph=None,
            budget=budget,
            fingerprints=fallback,
            trace=TraceRecorderV1(),
            diagnostics=(),
        )
