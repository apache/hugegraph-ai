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

"""Answer and factual correctness over explicit claim classifications."""

from collections.abc import Callable
from datetime import datetime

from pydantic import Field, JsonValue, model_validator

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationInput,
    EvaluationRecordDraft,
    Finding,
    FindingSeverity,
    Measurement,
    MeasurementDirection,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory
from hugegraph_llm_eval.evaluation.judges.base import Judge, JudgeCallError
from hugegraph_llm_eval.evaluation.judges.batching import BatchingOptions, BatchInputError, BatchOutputError
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.integrations.answer.evaluators.claims import (
    NLIVerdict,
    claim_evidence,
    complete_verdicts,
    decompose,
    ordered_verdicts,
    verify,
)
from hugegraph_llm_eval.integrations.answer.evaluators.judged_common import (
    JudgedAnswerEvaluator,
    reference_text,
)
from hugegraph_llm_eval.integrations.answer.materializers import AnswerArtifactMaterializer


class CorrectnessMatch(StrictModel):
    candidate_index: int = Field(ge=0)
    reference_index: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=4_000)


class UnmatchedClaim(StrictModel):
    statement_index: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=4_000)


class CorrectnessOutput(StrictModel):
    matches: tuple[CorrectnessMatch, ...]
    false_positives: tuple[UnmatchedClaim, ...]
    false_negatives: tuple[UnmatchedClaim, ...]

    @model_validator(mode="after")
    def _unique_indices(self) -> "CorrectnessOutput":
        candidate = tuple(item.candidate_index for item in self.matches) + tuple(
            item.statement_index for item in self.false_positives
        )
        reference = tuple(item.reference_index for item in self.matches) + tuple(
            item.statement_index for item in self.false_negatives
        )
        if len(candidate) != len(set(candidate)) or len(reference) != len(set(reference)):
            raise ValueError("correctness classifications must be one-to-one")
        return self


class AnswerCorrectnessEvaluator(JudgedAnswerEvaluator):
    def __init__(
        self,
        materializer: AnswerArtifactMaterializer,
        *,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
        use_default_task_prompts: bool = False,
        batching: BatchingOptions | None = None,
    ) -> None:
        super().__init__(
            materializer,
            invocation_key="answer_correctness",
            judge=judge,
            prompt=prompt,
            rubric=rubric,
            clock=clock,
            use_default_task_prompts=use_default_task_prompts,
            batching=batching,
        )

    def evaluate(self, evaluation_input: EvaluationInput, context: EvaluationContext) -> EvaluationRecordDraft:
        value = self.materialize(evaluation_input)
        if isinstance(value, EvaluationRecordDraft):
            return value
        session = self.session(context)
        try:
            candidate = decompose(self, session, "decompose_candidate", value.source.question, value.candidate.text)
            reference = decompose(self, session, "decompose_reference", value.source.question, reference_text(value))
            output = session.call(
                "classify_claims",
                self.request_for_task(
                    "correctness",
                    CorrectnessOutput,
                    {
                        "task": "classify_correctness",
                        "question": value.source.question,
                        "candidate": _indexed_claims(candidate),
                        "reference": _indexed_claims(reference),
                    },
                ),
            )
        except (JudgeCallError, BatchInputError, BatchOutputError) as exc:
            return self.judge_failure(exc, session)
        if not _complete_classification(output, len(candidate), len(reference)):
            return self.failure(
                "incomplete_correctness_classification",
                "correctness judge must classify every candidate and reference claim exactly once",
                FailureCategory.INVALID_PROVIDER_OUTPUT,
                calls=session.calls,
            )
        tp, fp, fn = len(output.matches), len(output.false_positives), len(output.false_negatives)
        score = _f1(tp, fp, fn)
        artifacts = {item.port.value: item.artifact for item in evaluation_input.subjects}
        return self.completed(
            _count_measurements("answer_correctness", "answer", score, tp, fp, fn),
            _correctness_findings(
                output, artifacts["answer_candidate"], artifacts["answer_reference"], candidate, reference
            ),
            f"answer correctness classified {tp} TP, {fp} FP, and {fn} FN claims",
            session,
        )


class FactualCorrectnessEvaluator(JudgedAnswerEvaluator):
    def __init__(
        self,
        materializer: AnswerArtifactMaterializer,
        *,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
        use_default_task_prompts: bool = False,
        batching: BatchingOptions | None = None,
    ) -> None:
        super().__init__(
            materializer,
            invocation_key="factual_correctness",
            judge=judge,
            prompt=prompt,
            rubric=rubric,
            clock=clock,
            use_default_task_prompts=use_default_task_prompts,
            batching=batching,
        )

    def evaluate(self, evaluation_input: EvaluationInput, context: EvaluationContext) -> EvaluationRecordDraft:
        value = self.materialize(evaluation_input)
        if isinstance(value, EvaluationRecordDraft):
            return value
        session = self.session(context)
        reference_value = reference_text(value)
        try:
            candidate = decompose(self, session, "decompose_candidate", value.source.question, value.candidate.text)
            precision = verify(self, session, "verify_candidate", candidate, reference_value)
            reference = decompose(self, session, "decompose_reference", value.source.question, reference_value)
            recall = verify(self, session, "verify_reference", reference, value.candidate.text)
        except (JudgeCallError, BatchInputError, BatchOutputError) as exc:
            return self.judge_failure(exc, session)
        if not complete_verdicts(precision, len(candidate)) or not complete_verdicts(recall, len(reference)):
            return self.failure(
                "incomplete_nli_verdicts",
                "factual correctness judge must return one NLI verdict per claim",
                FailureCategory.INVALID_PROVIDER_OUTPUT,
                calls=session.calls,
            )
        precision_ordered = ordered_verdicts(precision)
        recall_ordered = ordered_verdicts(recall)
        tp = sum(item.entailed for item in precision_ordered)
        fp = len(precision_ordered) - tp
        fn = sum(not item.entailed for item in recall_ordered)
        score = _f1(tp, fp, fn)
        artifacts = {item.port.value: item.artifact for item in evaluation_input.subjects}
        findings = tuple(
            _nli_finding("factual_correctness", item, artifacts["answer_candidate"], "text", candidate)
            for item in precision_ordered
        ) + tuple(
            _nli_finding("factual_correctness.reference", item, artifacts["answer_reference"], "answers", reference)
            for item in recall_ordered
        )
        return self.completed(
            _count_measurements("factual_correctness", "factual_correctness", score, tp, fp, fn),
            findings,
            f"factual correctness found {tp} supported, {fp} unsupported, and {fn} missing claims",
            session,
        )


def _indexed_claims(claims: tuple[str, ...]) -> list[JsonValue]:
    return [{"statement_index": index, "text": claim} for index, claim in enumerate(claims)]


def _complete_classification(output: CorrectnessOutput, candidate_count: int, reference_count: int) -> bool:
    candidate = {item.candidate_index for item in output.matches} | {
        item.statement_index for item in output.false_positives
    }
    reference = {item.reference_index for item in output.matches} | {
        item.statement_index for item in output.false_negatives
    }
    return candidate == set(range(candidate_count)) and reference == set(range(reference_count))


def _f1(tp: int, fp: int, fn: int) -> float:
    denominator = 2 * tp + fp + fn
    return 2 * tp / denominator if denominator else 1.0


def _count_measurements(
    score_name: str,
    count_prefix: str,
    score: float,
    tp: int,
    fp: int,
    fn: int,
) -> tuple[Measurement, ...]:
    return (
        Measurement(
            name=score_name, value=round(score, 4), unit="ratio", direction=MeasurementDirection.HIGHER_IS_BETTER
        ),
        Measurement(name=f"{count_prefix}_tp", value=tp, unit="count"),
        Measurement(name=f"{count_prefix}_fp", value=fp, unit="count"),
        Measurement(name=f"{count_prefix}_fn", value=fn, unit="count"),
    )


def _correctness_findings(
    output: CorrectnessOutput,
    candidate_artifact: ArtifactRef,
    reference_artifact: ArtifactRef,
    candidate: tuple[str, ...],
    reference: tuple[str, ...],
) -> tuple[Finding, ...]:
    matched = tuple(
        Finding(
            code="answer_correctness.tp",
            severity=FindingSeverity.INFO,
            message=item.reason,
            evidence=(
                claim_evidence(
                    candidate_artifact, f"text#statement-{item.candidate_index}", candidate[item.candidate_index]
                ),
                claim_evidence(
                    reference_artifact, f"answers#statement-{item.reference_index}", reference[item.reference_index]
                ),
            ),
        )
        for item in output.matches
    )
    false_positives = tuple(
        Finding(
            code="answer_correctness.fp",
            severity=FindingSeverity.ERROR,
            message=item.reason,
            evidence=(
                claim_evidence(
                    candidate_artifact, f"text#statement-{item.statement_index}", candidate[item.statement_index]
                ),
            ),
        )
        for item in output.false_positives
    )
    false_negatives = tuple(
        Finding(
            code="answer_correctness.fn",
            severity=FindingSeverity.ERROR,
            message=item.reason,
            evidence=(
                claim_evidence(
                    reference_artifact, f"answers#statement-{item.statement_index}", reference[item.statement_index]
                ),
            ),
        )
        for item in output.false_negatives
    )
    return (*matched, *false_positives, *false_negatives)


def _nli_finding(
    prefix: str, verdict: NLIVerdict, artifact: ArtifactRef, locator: str, claims: tuple[str, ...]
) -> Finding:
    return Finding(
        code=f"{prefix}.entailed" if verdict.entailed else f"{prefix}.not_entailed",
        severity=FindingSeverity.INFO if verdict.entailed else FindingSeverity.ERROR,
        message=verdict.reason,
        evidence=(
            claim_evidence(artifact, f"{locator}#statement-{verdict.statement_index}", claims[verdict.statement_index]),
        ),
    )
