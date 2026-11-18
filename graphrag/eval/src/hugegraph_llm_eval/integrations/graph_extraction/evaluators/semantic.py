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

"""LLM semantic entity and triple matching with deterministic scoring."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.contracts.digests import canonical_digest, canonical_json_bytes
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationInput,
    EvaluationRecordDraft,
    EvaluationRecordStatus,
    EvaluatorDescriptor,
)
from hugegraph_llm_eval.contracts.domain.graph import GraphCandidate, GraphEdge, GraphVertex
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
from hugegraph_llm_eval.evaluation.judges.batching import BatchingOptions, BatchInputError, paired_payload_batches
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.judges.session import JudgeSession
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.semantic_scoring import (
    MatchPair,
    global_optimal_matches,
    semantic_findings,
    semantic_measurements,
)
from hugegraph_llm_eval.integrations.graph_extraction.materializers import (
    GRAPH_EXTRACTION_INPUT_SCHEMA,
    GraphArtifactMaterializer,
    GraphMaterializationError,
)

GraphItem = GraphVertex | GraphEdge
SemanticMatchIssue = Literal[
    "label_mismatch",
    "name_mismatch",
    "property_mismatch",
    "relation_mismatch",
    "endpoint_mismatch",
    "endpoint_label_mismatch",
    "direction_mismatch",
    "no_semantic_match",
]


class SemanticVerdict(StrictModel):
    """One proposed semantic pair, or a reference with no match in this batch."""

    reference_index: int = Field(ge=0)
    candidate_index: int | None = Field(default=None, ge=0)
    match_score: float | None = Field(default=None, ge=0, le=100)
    match_issues: tuple[SemanticMatchIssue, ...]
    reason: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def _match_score_presence(self) -> "SemanticVerdict":
        """Require a score exactly when the verdict contains a match."""
        if self.candidate_index is None and self.match_score is not None:
            raise ValueError("unmatched semantic verdict must not contain a match score")
        if self.candidate_index is not None and self.match_score is None:
            raise ValueError("matched semantic verdict must contain a match score")
        self._validate_match_issues()
        return self

    def _validate_match_issues(self) -> None:
        """Reject duplicate issue labels and hard conflicts on accepted matches."""
        if len(self.match_issues) != len(set(self.match_issues)):
            raise ValueError("semantic verdict match issues must be unique")
        if self.candidate_index is None and "no_semantic_match" not in self.match_issues:
            raise ValueError("unmatched semantic verdict must contain no_semantic_match")
        if self.candidate_index is not None and {
            "no_semantic_match",
            "name_mismatch",
        }.intersection(self.match_issues):
            raise ValueError("matched semantic verdict cannot contain unmatched or name mismatch issues")
        if self.candidate_index is not None and {
            "endpoint_mismatch",
            "direction_mismatch",
        }.intersection(self.match_issues):
            raise ValueError("matched semantic verdict cannot contain endpoint or direction mismatch issues")


class SemanticVerdictOutput(StrictModel):
    verdicts: tuple[SemanticVerdict, ...]

    @model_validator(mode="after")
    def _consistent_pairs(self) -> "SemanticVerdictOutput":
        candidates_by_reference: dict[int, set[int | None]] = {}
        for item in self.verdicts:
            candidates = candidates_by_reference.setdefault(item.reference_index, set())
            if item.candidate_index in candidates:
                raise ValueError("semantic verdict candidate/reference pairs must be unique")
            candidates.add(item.candidate_index)
            if None in candidates and len(candidates) > 1:
                raise ValueError("unmatched semantic verdict cannot accompany matches for the same reference")
        return self


@dataclass(frozen=True, slots=True)
class _SemanticSpec:
    kind: Literal["entity", "triple"]
    invocation_key: str
    evaluator: EvaluatorRef


@dataclass(frozen=True, slots=True)
class _SemanticBatchResult:
    """Result of one independent candidate-batch judge call."""

    output: SemanticVerdictOutput | None
    judge_calls: tuple[JudgeCallRecord, ...]
    failure: FailureDetail | None = None


class _SemanticGraphEvaluator:
    input_type = EvaluationInput

    def __init__(
        self,
        materializer: GraphArtifactMaterializer,
        spec: _SemanticSpec,
        *,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
        batching: BatchingOptions | None = None,
        matching_strategy: Literal["max_weight", "max_cardinality"] = "max_weight",
    ) -> None:
        if matching_strategy not in ("max_weight", "max_cardinality"):
            raise ValueError("matching_strategy must be 'max_weight' or 'max_cardinality'")
        self._batching = batching or BatchingOptions()
        self._matching_strategy = matching_strategy
        self._materializer = materializer
        self._spec = spec
        self._judge = judge
        self._prompt = prompt
        self._rubric = rubric
        self._clock = clock
        self.descriptor = EvaluatorDescriptor(
            evaluator=spec.evaluator,
            implementation_digest=canonical_digest(
                {
                    "algorithm": f"graph-semantic-{spec.kind}",
                    "version": 9,
                    "matching": "two-sided-window-alternative-pairs-global-one-to-one",
                    "matching_strategy": matching_strategy,
                    "batching": self._batching.model_dump(mode="json"),
                    "judge": judge.descriptor.model_dump(mode="json"),
                    "prompt": prompt.reference.model_dump(mode="json"),
                    "rubric": rubric.reference.model_dump(mode="json"),
                }
            ),
            input_schema=GRAPH_EXTRACTION_INPUT_SCHEMA,
            output_schema=SchemaRef(namespace="graph", name=f"semantic_{spec.kind}_record", version=1),
        )

    @property
    def invocation_key(self) -> str:
        return self._spec.invocation_key

    def evaluate(self, evaluation_input: EvaluationInput, context: EvaluationContext) -> EvaluationRecordDraft:
        try:
            value = self._materializer.extraction(evaluation_input)
        except GraphMaterializationError as exc:
            return self._failure("graph_extraction_materialization_failed", str(exc), FailureCategory.INVALID_INPUT)
        if context.cancellation.is_cancelled:
            return self._failure(
                "evaluation_cancelled",
                context.cancellation.reason or "evaluation cancelled",
                FailureCategory.CANCELLED,
            )
        candidate = _items(value.candidate, self._spec.kind)
        reference = _items(value.reference, self._spec.kind)
        if not candidate or not reference:
            return self._completed(evaluation_input, candidate, reference, [], ())
        batch_results = self._run_batches(
            tuple(enumerate(candidate)),
            tuple(enumerate(reference)),
            context,
        )
        judge_calls = self._collected_calls(batch_results)
        failed_batch = self._failed_result(batch_results)
        if failed_batch is not None:
            assert failed_batch.failure is not None
            return self._failure(
                failed_batch.failure.code,
                failed_batch.failure.message,
                failed_batch.failure.category,
                retryable=failed_batch.failure.retryable,
                judge_calls=judge_calls,
            )
        return self._completed(
            evaluation_input,
            candidate,
            reference,
            self._accepted_matches(batch_results),
            judge_calls,
        )

    def _collected_calls(self, batch_results: tuple[_SemanticBatchResult, ...]) -> tuple[JudgeCallRecord, ...]:
        """Flatten batch-local judge calls into one contiguous, persisted run."""
        return _renumber_judge_calls(tuple(call for result in batch_results for call in result.judge_calls))

    def _failed_result(self, batch_results: tuple[_SemanticBatchResult, ...]) -> _SemanticBatchResult | None:
        """Return the first failed candidate batch, if any."""
        return next((result for result in batch_results if result.failure is not None), None)

    def _accepted_matches(self, batch_results: tuple[_SemanticBatchResult, ...]) -> list[MatchPair]:
        """Project accepted verdicts from every batch into candidate/reference pairs."""
        matches: list[MatchPair] = []
        for result in batch_results:
            assert result.output is not None
            matches.extend(_match_pairs(result.output))
        return matches

    def _run_batches(
        self,
        indexed_candidate: tuple[tuple[int, GraphItem], ...],
        indexed_reference: tuple[tuple[int, GraphItem], ...],
        context: EvaluationContext,
    ) -> tuple[_SemanticBatchResult, ...]:
        batches = enumerate(
            paired_payload_batches(
                indexed_candidate,
                indexed_reference,
                lambda candidate, reference: _request_payload(candidate, reference, self._spec.kind),
                self._batching,
            )
        )
        results: list[_SemanticBatchResult] = []
        with ThreadPoolExecutor(
            max_workers=context.max_concurrency,
            thread_name_prefix=f"hugegraph-llm-eval-semantic-{self._spec.kind}",
        ) as executor:
            while True:
                try:
                    group = tuple(islice(batches, context.max_concurrency))
                except BatchInputError as exc:
                    results.append(
                        _SemanticBatchResult(
                            output=None,
                            judge_calls=(),
                            failure=FailureDetail(
                                category=FailureCategory.RESOURCE_EXHAUSTED,
                                code="evaluation_payload_too_large",
                                message=str(exc),
                                retryable=False,
                            ),
                        )
                    )
                    break
                if not group:
                    break
                futures = [
                    executor.submit(self._run_batch, ordinal, candidate, reference, payload, context)
                    for ordinal, (candidate, reference, payload) in group
                ]
                outcomes = tuple(future.result() for future in futures)
                results.extend(outcomes)
                if any(outcome.failure is not None for outcome in outcomes):
                    break
        return tuple(results)

    def _run_batch(
        self,
        batch_ordinal: int,
        candidate_batch: tuple[tuple[int, GraphItem], ...],
        indexed_reference: tuple[tuple[int, GraphItem], ...],
        payload: JsonValue,
        context: EvaluationContext,
    ) -> _SemanticBatchResult:
        """Run one candidate batch in its own judge session."""
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
        request = _request(payload, self._prompt, self._rubric)
        try:
            output = session.call(f"candidate_batch_{batch_ordinal}", request)
        except JudgeCallError as exc:
            return _SemanticBatchResult(
                output=None,
                judge_calls=session.calls,
                failure=exc.failure,
            )
        invalid = _invalid_verdict(output, candidate_batch, indexed_reference)
        if invalid is not None:
            return _SemanticBatchResult(
                output=None,
                judge_calls=session.calls,
                failure=FailureDetail(
                    category=FailureCategory.INVALID_PROVIDER_OUTPUT,
                    code="incomplete_semantic_verdicts",
                    message=invalid,
                    retryable=False,
                ),
            )
        return _SemanticBatchResult(output=output, judge_calls=session.calls)

    def _completed(
        self,
        evaluation_input: EvaluationInput,
        candidate: tuple[GraphItem, ...],
        reference: tuple[GraphItem, ...],
        matches: list[MatchPair],
        judge_calls: tuple[JudgeCallRecord, ...],
    ) -> EvaluationRecordDraft:
        accepted = global_optimal_matches(matches, strategy=self._matching_strategy)
        matched = len(accepted)
        precision = matched / len(candidate) if candidate else 0.0
        recall = matched / len(reference) if reference else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        artifacts = {item.port.value: item.artifact for item in evaluation_input.subjects}
        return EvaluationRecordDraft(
            invocation_key=self._spec.invocation_key,
            evaluator=self.descriptor.evaluator,
            status=EvaluationRecordStatus.COMPLETED,
            measurements=semantic_measurements(self._spec.kind, precision, recall, f1),
            findings=semantic_findings(
                self._spec.kind,
                len(candidate),
                len(reference),
                accepted,
                artifacts["candidate_graph"],
                artifacts["reference_graph"],
            ),
            reason=f"semantic {self._spec.kind} matching accepted {matched} of {len(candidate)} candidates",
            judge_calls=judge_calls,
            attempts=1,
            latency_ms=sum(attempt.latency_ms for call in judge_calls for attempt in call.provenance.attempts),
            created_at=self._clock(),
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
        return EvaluationRecordDraft(
            invocation_key=self._spec.invocation_key,
            evaluator=self.descriptor.evaluator,
            status=(
                EvaluationRecordStatus.CANCELLED
                if category is FailureCategory.CANCELLED
                else EvaluationRecordStatus.FAILED
            ),
            reason=message,
            judge_calls=judge_calls,
            attempts=1,
            latency_ms=sum(attempt.latency_ms for call in judge_calls for attempt in call.provenance.attempts),
            failure=FailureDetail(category=category, code=code, message=message, retryable=retryable),
            created_at=self._clock(),
        )


class SemanticEntityEvaluator(_SemanticGraphEvaluator):
    def __init__(
        self,
        materializer: GraphArtifactMaterializer,
        *,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
        batching: BatchingOptions | None = None,
        matching_strategy: Literal["max_weight", "max_cardinality"] = "max_weight",
    ) -> None:
        super().__init__(
            materializer,
            _SemanticSpec(
                kind="entity",
                invocation_key="semantic_entity",
                evaluator=EvaluatorRef(namespace="graph", name="semantic_entity", revision="v2"),
            ),
            judge=judge,
            prompt=prompt,
            rubric=rubric,
            clock=clock,
            batching=batching,
            matching_strategy=matching_strategy,
        )


class SemanticTripleEvaluator(_SemanticGraphEvaluator):
    def __init__(
        self,
        materializer: GraphArtifactMaterializer,
        *,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
        batching: BatchingOptions | None = None,
        matching_strategy: Literal["max_weight", "max_cardinality"] = "max_weight",
    ) -> None:
        super().__init__(
            materializer,
            _SemanticSpec(
                kind="triple",
                invocation_key="semantic_triple",
                evaluator=EvaluatorRef(namespace="graph", name="semantic_triple", revision="v2"),
            ),
            judge=judge,
            prompt=prompt,
            rubric=rubric,
            clock=clock,
            batching=batching,
            matching_strategy=matching_strategy,
        )


def _items(graph: GraphCandidate, kind: str) -> tuple[GraphItem, ...]:
    return tuple(graph.vertices if kind == "entity" else graph.edges)


def _match_pairs(output: SemanticVerdictOutput) -> tuple[MatchPair, ...]:
    """Project one batch of verdicts into candidate/reference pairs."""
    pairs: list[MatchPair] = []
    for item in output.verdicts:
        if item.candidate_index is None:
            continue
        assert item.match_score is not None
        pairs.append(
            MatchPair(
                candidate_index=item.candidate_index,
                reference_index=item.reference_index,
                reason=item.reason,
                match_score=item.match_score,
                match_issues=item.match_issues,
            )
        )
    return tuple(pairs)


def _renumber_judge_calls(calls: tuple[JudgeCallRecord, ...]) -> tuple[JudgeCallRecord, ...]:
    """Make independently collected batch calls contiguous for the persisted record."""
    return tuple(call.model_copy(update={"call_index": index}) for index, call in enumerate(calls, start=1))


def _request_payload(
    candidate: tuple[tuple[int, GraphItem], ...],
    reference: tuple[tuple[int, GraphItem], ...],
    kind: str,
) -> JsonValue:
    return {
        "item_kind": kind,
        "candidates": [_payload(index, item, kind, "candidate_index") for index, item in candidate],
        "references": [_payload(index, item, kind, "reference_index") for index, item in reference],
    }


def _request(
    payload: JsonValue,
    prompt: JudgeContent,
    rubric: JudgeContent,
) -> JudgeRequest[SemanticVerdictOutput]:
    return JudgeRequest(
        messages=(
            JudgeMessage(role="system", content=f"{prompt.text}\n\nRubric:\n{rubric.text}"),
            JudgeMessage(role="user", content=canonical_json_bytes(payload).decode()),
        ),
        response_type=SemanticVerdictOutput,
        prompt=prompt.reference,
        rubric=rubric.reference,
    )


def _payload(index: int, item: GraphItem, kind: str, index_name: str) -> JsonValue:
    if kind == "entity":
        assert isinstance(item, GraphVertex)
        return {index_name: index, "label": item.label, "name": item.name, "properties": item.properties}
    assert isinstance(item, GraphEdge)
    return {
        index_name: index,
        "label": item.label,
        "out_v": item.out_v,
        "out_v_label": item.out_v_label,
        "in_v": item.in_v,
        "in_v_label": item.in_v_label,
        "properties": item.properties,
    }


def _invalid_verdict(
    output: SemanticVerdictOutput,
    candidate: tuple[tuple[int, GraphItem], ...],
    reference: tuple[tuple[int, GraphItem], ...],
) -> str | None:
    """Reject output that omits or invents a reference verdict."""
    candidate_indices = {index for index, _ in candidate}
    reference_indices = {index for index, _ in reference}
    verdict_indices = {item.reference_index for item in output.verdicts}
    if verdict_indices != reference_indices:
        return "semantic judge must cover every supplied reference with matches or one unmatched verdict"
    if any(
        item.candidate_index is not None and item.candidate_index not in candidate_indices for item in output.verdicts
    ):
        return "semantic judge returned a candidate index outside the supplied candidate batch"
    return None
