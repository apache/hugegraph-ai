# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""LLM-judged candidate faithfulness with complete item-level coverage."""

from collections.abc import Callable
from datetime import datetime

from pydantic import JsonValue

from hugegraph_llm_eval.contracts.digests import canonical_digest, canonical_json_bytes
from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationInput,
    EvaluationRecordDraft,
    EvaluationRecordStatus,
    EvaluatorDescriptor,
    EvidenceLink,
    Finding,
    FindingSeverity,
    Measurement,
    MeasurementDirection,
)
from hugegraph_llm_eval.contracts.domain.graph import (
    GraphCandidate,
    GraphExtractionInput,
    GraphReviewInput,
)
from hugegraph_llm_eval.contracts.domain.judge import JudgeCallRecord
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.contracts.identity import EvaluatorRef, SchemaRef
from hugegraph_llm_eval.evaluation.judges.base import (
    Judge,
    JudgeCallError,
    JudgeMessage,
    JudgeOptions,
    JudgeRequest,
)
from hugegraph_llm_eval.evaluation.judges.batching import BatchingOptions, BatchInputError, payload_batches
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.judges.session import JudgeSession
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.faithfulness_output import (
    FaithfulnessIssueGroup as FaithfulnessIssueGroup,
)
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.faithfulness_output import (
    FaithfulnessItemKind,
    FaithfulnessJudgeOutput,
    FaithfulnessVerdict,
)
from hugegraph_llm_eval.integrations.graph_extraction.materializers import (
    GRAPH_EXTRACTION_INPUT_SCHEMA,
    GRAPH_REVIEW_INPUT_SCHEMA,
    QUALITY_INPUT_SCHEMAS,
    GraphArtifactMaterializer,
    GraphMaterializationError,
)
from hugegraph_llm_eval.utils.text_preview import text_preview

FAITHFULNESS_REF = EvaluatorRef(namespace="graph", name="faithfulness", revision="v1")
EXTRACTION_FAITHFULNESS_REF = EvaluatorRef(namespace="graph", name="faithfulness", revision="v2")


class FaithfulnessEvaluator:
    input_type = EvaluationInput

    def __init__(
        self,
        materializer: GraphArtifactMaterializer,
        *,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
        input_schema: SchemaRef = GRAPH_REVIEW_INPUT_SCHEMA,
        batching: BatchingOptions | None = None,
    ) -> None:
        if input_schema not in QUALITY_INPUT_SCHEMAS:
            raise ValueError("graph quality input schema must be candidate_review or extraction")
        self._materializer = materializer
        self._judge = judge
        self._prompt = prompt
        self._rubric = rubric
        self._clock = clock
        self._input_schema = input_schema
        self._batching = batching or BatchingOptions()
        self.descriptor = EvaluatorDescriptor(
            evaluator=_evaluator_ref(input_schema),
            implementation_digest=canonical_digest(
                {
                    **_implementation_identity(judge, prompt, rubric, input_schema),
                    "batching": self._batching.model_dump(mode="json"),
                }
            ),
            input_schema=input_schema,
            output_schema=SchemaRef(namespace="graph", name="faithfulness_record", version=1),
        )

    @property
    def invocation_key(self) -> str:
        return "faithfulness"

    def evaluate(self, evaluation_input: EvaluationInput, context: EvaluationContext) -> EvaluationRecordDraft:
        try:
            materialized = self._materialize(evaluation_input)
        except GraphMaterializationError as exc:
            return self._failure("graph_materialization_failed", str(exc), FailureCategory.INVALID_INPUT)
        if context.cancellation.is_cancelled:
            return self._failure(
                "evaluation_cancelled",
                context.cancellation.reason or "evaluation cancelled",
                FailureCategory.CANCELLED,
            )
        if not materialized.candidate.vertices and not materialized.candidate.edges:
            return self._empty_candidate()
        session = JudgeSession(
            self._judge,
            JudgeOptions(
                deadline=context.deadline,
                max_attempts=context.max_attempts,
                initial_backoff_seconds=context.retry_backoff_seconds,
            ),
            cancellation=context.cancellation,
            limiter=context.limiter,
            clock=self._clock,
        )
        verdicts: list[FaithfulnessVerdict] = []
        try:
            batches = payload_batches(
                _items(materialized.candidate),
                lambda items: {"source_text": materialized.source_text, "items": list(items)},
                self._batching,
            )
            for index, (items, payload) in enumerate(batches):
                key = "evaluate_items" if index == 0 else f"evaluate_items_{index}"
                output = session.call(key, _judge_request(payload, self._prompt, self._rubric))
                batch_verdicts = output.verdicts()
                coverage_failure = _coverage_failure(items, batch_verdicts)
                if coverage_failure is not None:
                    return self._failure(
                        "incomplete_faithfulness_verdicts",
                        coverage_failure,
                        FailureCategory.INVALID_PROVIDER_OUTPUT,
                        judge_calls=session.calls,
                    )
                verdicts.extend(batch_verdicts)
        except JudgeCallError as exc:
            return self._judge_failure(exc, session)
        except BatchInputError as exc:
            return self._failure(
                "evaluation_payload_too_large",
                str(exc),
                FailureCategory.RESOURCE_EXHAUSTED,
                judge_calls=session.calls,
            )
        return self._completed(evaluation_input, tuple(verdicts), session.calls)

    def _completed(
        self,
        evaluation_input: EvaluationInput,
        verdicts: tuple[FaithfulnessVerdict, ...],
        judge_calls: tuple[JudgeCallRecord, ...],
    ) -> EvaluationRecordDraft:
        vertex_verdicts = tuple(item for item in verdicts if item.item_kind is FaithfulnessItemKind.VERTEX)
        edge_verdicts = tuple(item for item in verdicts if item.item_kind is FaithfulnessItemKind.EDGE)
        faithful_vertices = _faithful_count(vertex_verdicts)
        faithful_edges = _faithful_count(edge_verdicts)
        faithful = faithful_vertices + faithful_edges
        candidate = next(item.artifact for item in evaluation_input.subjects if item.port.value == "candidate_graph")
        findings = tuple(finding for item in verdicts for finding in _findings(item, candidate))
        score = faithful / len(verdicts)
        return EvaluationRecordDraft(
            invocation_key="faithfulness",
            evaluator=self.descriptor.evaluator,
            status=EvaluationRecordStatus.COMPLETED,
            measurements=_faithfulness_measurements(
                score,
                vertex_verdicts,
                faithful_vertices,
                edge_verdicts,
                faithful_edges,
            ),
            findings=findings,
            reason=(
                f"{faithful} of {len(verdicts)} extracted claims are supported by source evidence; "
                f"vertices {faithful_vertices}/{len(vertex_verdicts)}, "
                f"edges {faithful_edges}/{len(edge_verdicts)}"
            ),
            judge_calls=judge_calls,
            attempts=1,
            latency_ms=sum(_judge_call_latency(call) for call in judge_calls),
            created_at=self._clock(),
        )

    def _judge_failure(self, error: JudgeCallError, session: JudgeSession) -> EvaluationRecordDraft:
        return self._failure(
            error.failure.code,
            error.failure.message,
            error.failure.category,
            retryable=error.failure.retryable,
            judge_calls=session.calls,
        )

    def _failure(
        self,
        code: str,
        message: str,
        category: FailureCategory,
        *,
        retryable: bool = False,
        judge_calls: tuple[JudgeCallRecord, ...] = (),
    ) -> EvaluationRecordDraft:
        failure = FailureDetail(category=category, code=code, message=message, retryable=retryable)
        return EvaluationRecordDraft(
            invocation_key="faithfulness",
            evaluator=self.descriptor.evaluator,
            status=(
                EvaluationRecordStatus.CANCELLED
                if category is FailureCategory.CANCELLED
                else EvaluationRecordStatus.FAILED
            ),
            reason=message,
            judge_calls=judge_calls,
            attempts=1,
            latency_ms=sum(_judge_call_latency(call) for call in judge_calls),
            failure=failure,
            created_at=self._clock(),
        )

    def _empty_candidate(self) -> EvaluationRecordDraft:
        return EvaluationRecordDraft(
            invocation_key="faithfulness",
            evaluator=self.descriptor.evaluator,
            status=EvaluationRecordStatus.NOT_APPLICABLE,
            findings=(
                Finding(
                    code="faithfulness.empty_candidate",
                    severity=FindingSeverity.ERROR,
                    message="faithfulness is undefined because candidate graph contains no claims",
                ),
            ),
            reason="faithfulness is not applicable for an empty candidate graph",
            attempts=0,
            latency_ms=0,
            created_at=self._clock(),
        )

    def _materialize(self, evaluation_input: EvaluationInput) -> GraphReviewInput | GraphExtractionInput:
        """Use a complete input offline and preserve the no-GT production review boundary."""
        return self._materializer.quality(evaluation_input, expected_schema=self._input_schema)


def _faithful_count(verdicts: tuple[FaithfulnessVerdict, ...]) -> int:
    """Count supported claims in one graph item kind."""
    return sum(item.faithful for item in verdicts)


def _faithfulness_measurements(
    score: float,
    vertex_verdicts: tuple[FaithfulnessVerdict, ...],
    faithful_vertices: int,
    edge_verdicts: tuple[FaithfulnessVerdict, ...],
    faithful_edges: int,
) -> tuple[Measurement, ...]:
    """Return the micro score plus available per-kind diagnostics."""
    measurements = [
        Measurement(
            name="faithfulness",
            value=score,
            unit="ratio",
            direction=MeasurementDirection.HIGHER_IS_BETTER,
        ),
    ]
    for name, verdicts, faithful in (
        ("faithfulness_vertex", vertex_verdicts, faithful_vertices),
        ("faithfulness_edge", edge_verdicts, faithful_edges),
    ):
        if verdicts:
            measurements.append(
                Measurement(
                    name=name,
                    value=faithful / len(verdicts),
                    unit="ratio",
                    direction=MeasurementDirection.HIGHER_IS_BETTER,
                )
            )
    return tuple(measurements)


def _evaluator_ref(input_schema: SchemaRef) -> EvaluatorRef:
    """Keep offline extraction distinct from candidate-only production review."""
    return EXTRACTION_FAITHFULNESS_REF if input_schema == GRAPH_EXTRACTION_INPUT_SCHEMA else FAITHFULNESS_REF


def _implementation_identity(
    judge: Judge,
    prompt: JudgeContent,
    rubric: JudgeContent,
    input_schema: SchemaRef,
) -> dict[str, JsonValue]:
    return {
        "algorithm": "graph-item-faithfulness",
        "version": 8,
        "score_semantics": "supported_candidate_claims_micro_average_with_vertex_edge_diagnostics",
        "empty_candidate": "not_applicable",
        "input_schema": input_schema.model_dump(mode="json"),
        "judge": judge.descriptor.model_dump(mode="json"),
        "prompt": prompt.reference.model_dump(mode="json"),
        "rubric": rubric.reference.model_dump(mode="json"),
    }


def _judge_call_latency(call: JudgeCallRecord) -> int:
    return sum(attempt.latency_ms for attempt in call.provenance.attempts)


def _judge_request(
    payload: JsonValue,
    prompt: JudgeContent,
    rubric: JudgeContent,
) -> JudgeRequest[FaithfulnessJudgeOutput]:
    return JudgeRequest(
        messages=(
            JudgeMessage(
                role="system",
                content=f"{prompt.text}\n\nRubric:\n{rubric.text}",
            ),
            JudgeMessage(role="user", content=canonical_json_bytes(payload).decode()),
        ),
        response_type=FaithfulnessJudgeOutput,
        prompt=prompt.reference,
        rubric=rubric.reference,
    )


def _items(candidate: GraphCandidate) -> list[JsonValue]:
    vertices: list[JsonValue] = [
        {
            "item_kind": "vertex",
            "item_index": index,
            "label": vertex.label,
            "name": vertex.name,
            "properties": vertex.properties,
            "source_snippet": vertex.source_snippet,
        }
        for index, vertex in enumerate(candidate.vertices)
    ]
    edges: list[JsonValue] = [
        {
            "item_kind": "edge",
            "item_index": index,
            "label": edge.label,
            "out_v": edge.out_v,
            "in_v": edge.in_v,
            "out_v_label": edge.out_v_label,
            "in_v_label": edge.in_v_label,
            "properties": edge.properties,
            "source_snippet": edge.source_snippet,
        }
        for index, edge in enumerate(candidate.edges)
    ]
    return [*vertices, *edges]


def _coverage_failure(items: tuple[JsonValue, ...], verdicts: tuple[FaithfulnessVerdict, ...]) -> str | None:
    expected = {(item["item_kind"], item["item_index"]) for item in items if isinstance(item, dict)}
    actual = {(item.item_kind.value, item.item_index) for item in verdicts}
    if actual == expected and len(actual) == len(verdicts):
        return None
    return "faithfulness judge must return exactly one verdict for every item in the supplied batch"


def _findings(verdict: FaithfulnessVerdict, artifact: ArtifactRef) -> tuple[Finding, ...]:
    """Build the base finding and machine-readable category findings."""
    locator = (
        f"vertices[{verdict.item_index}]"
        if verdict.item_kind is FaithfulnessItemKind.VERTEX
        else f"edges[{verdict.item_index}]"
    )
    description = text_preview(verdict.evidence_quote, 2_000) if verdict.evidence_quote is not None else None
    evidence = (EvidenceLink(artifact=artifact, locator=locator, description=description),)
    base = Finding(
        code="faithfulness.supported" if verdict.faithful else "faithfulness.unsupported",
        severity=FindingSeverity.INFO if verdict.faithful else FindingSeverity.ERROR,
        message=(
            (verdict.support_reason or "supported claim")
            if verdict.faithful
            else (verdict.error_reason or "unsupported claim")
        ),
        evidence=evidence,
    )
    if verdict.faithful:
        return (base,)
    support_findings = (
        (
            Finding(
                code="faithfulness.supported_part",
                severity=FindingSeverity.INFO,
                message=verdict.support_reason,
                evidence=evidence,
            ),
        )
        if verdict.support_reason
        else ()
    )
    category_findings = tuple(
        Finding(
            code=f"faithfulness.issue.{category.value}",
            severity=FindingSeverity.ERROR,
            message=verdict.error_reason or "unsupported claim",
            evidence=evidence,
        )
        for category in verdict.error_categories
    )
    return (*support_findings, *category_findings, base)
