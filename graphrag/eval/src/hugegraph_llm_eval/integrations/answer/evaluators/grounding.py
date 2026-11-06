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

"""Answer faithfulness and retrieval-noise attribution Evaluators."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

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
from hugegraph_llm_eval.evaluation.judges.session import JudgeSession
from hugegraph_llm_eval.integrations.answer.evaluators.claims import (
    NLIVerdict,
    NLIVerdictsOutput,
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
from hugegraph_llm_eval.integrations.answer.schemas import AnswerComparisonInput


@dataclass(frozen=True, slots=True)
class _NoiseJudgements:
    reference_claims: tuple[str, ...]
    candidate_claims: tuple[str, ...]
    reference_by_context: tuple[NLIVerdictsOutput, ...]
    candidate_by_context: tuple[NLIVerdictsOutput, ...]
    correctness: NLIVerdictsOutput


class FaithfulnessEvaluator(JudgedAnswerEvaluator):
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
            invocation_key="faithfulness",
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
        if not value.source.contexts:
            return self.completed((_ratio("faithfulness", 0),), (), "no contexts support the answer", session)
        if not value.candidate.text.strip():
            return self.completed((_ratio("faithfulness", 1),), (), "empty answer has no unsupported claims", session)
        try:
            claims = decompose(self, session, "decompose_answer", value.source.question, value.candidate.text)
            verdicts = verify(self, session, "verify_answer", claims, "\n\n".join(value.source.contexts))
        except (JudgeCallError, BatchInputError, BatchOutputError) as exc:
            return self.judge_failure(exc, session)
        if not complete_verdicts(verdicts, len(claims)):
            return self.failure(
                "incomplete_nli_verdicts",
                "faithfulness judge must return one NLI verdict per answer claim",
                FailureCategory.INVALID_PROVIDER_OUTPUT,
                calls=session.calls,
            )
        ordered = ordered_verdicts(verdicts)
        supported = sum(item.entailed for item in ordered)
        score = supported / len(ordered) if ordered else 1.0
        artifact = _subject(evaluation_input, "answer_candidate")
        findings = tuple(_faithfulness_finding(item, artifact, claims) for item in ordered)
        return self.completed(
            (_ratio("faithfulness", round(score, 4)),),
            findings,
            f"contexts support {supported} of {len(ordered)} answer claims",
            session,
        )


class NoiseSensitivityEvaluator(JudgedAnswerEvaluator):
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
            invocation_key="noise_sensitivity",
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
        if not value.candidate.text.strip() or not value.source.contexts:
            return self.not_applicable("noise sensitivity requires a non-empty answer and contexts", session)
        try:
            judgements = _judge_noise(self, session, value)
        except (JudgeCallError, BatchInputError, BatchOutputError) as exc:
            return self.judge_failure(exc, session)
        if not _complete_matrix(
            judgements.reference_by_context,
            len(judgements.reference_claims),
        ) or not _complete_matrix(judgements.candidate_by_context, len(judgements.candidate_claims)):
            return self.failure(
                "incomplete_context_nli_verdicts",
                "noise sensitivity judge must cover every claim for every context",
                FailureCategory.INVALID_PROVIDER_OUTPUT,
                calls=session.calls,
            )
        if not complete_verdicts(judgements.correctness, len(judgements.candidate_claims)):
            return self.failure(
                "incomplete_correctness_nli_verdicts",
                "noise sensitivity judge must classify every answer claim against the reference",
                FailureCategory.INVALID_PROVIDER_OUTPUT,
                calls=session.calls,
            )
        caused = _caused_errors(
            judgements.reference_by_context,
            judgements.candidate_by_context,
            judgements.correctness,
        )
        score = sum(caused) / len(caused) if caused else 0.0
        artifact = _subject(evaluation_input, "answer_candidate")
        findings = tuple(
            _noise_finding(index, verdict, caused[index], artifact, judgements.candidate_claims[index])
            for index, verdict in enumerate(ordered_verdicts(judgements.correctness))
        )
        return self.completed(
            (
                Measurement(
                    name="noise_sensitivity",
                    value=round(score, 4),
                    unit="ratio",
                    direction=MeasurementDirection.LOWER_IS_BETTER,
                ),
            ),
            findings,
            f"retrieval context caused {sum(caused)} of {len(caused)} answer claims to be wrong",
            session,
        )


def _judge_noise(
    evaluator: JudgedAnswerEvaluator,
    session: JudgeSession,
    value: AnswerComparisonInput,
) -> _NoiseJudgements:
    reference_value = reference_text(value)
    reference_claims = decompose(
        evaluator,
        session,
        "decompose_reference",
        value.source.question,
        reference_value,
    )
    candidate_claims = decompose(
        evaluator,
        session,
        "decompose_candidate",
        value.source.question,
        value.candidate.text,
    )
    reference_rows: list[NLIVerdictsOutput] = []
    candidate_rows: list[NLIVerdictsOutput] = []
    for index, source_context in enumerate(value.source.contexts):
        reference_rows.append(
            verify(evaluator, session, f"verify_reference_context_{index}", reference_claims, source_context)
        )
        candidate_rows.append(
            verify(evaluator, session, f"verify_candidate_context_{index}", candidate_claims, source_context)
        )
    return _NoiseJudgements(
        reference_claims=reference_claims,
        candidate_claims=candidate_claims,
        reference_by_context=tuple(reference_rows),
        candidate_by_context=tuple(candidate_rows),
        correctness=verify(
            evaluator,
            session,
            "verify_candidate_reference",
            candidate_claims,
            reference_value,
        ),
    )


def _ratio(name: str, value: float) -> Measurement:
    return Measurement(name=name, value=value, unit="ratio", direction=MeasurementDirection.HIGHER_IS_BETTER)


def _subject(evaluation_input: EvaluationInput, port: str) -> ArtifactRef:
    return next(item.artifact for item in evaluation_input.subjects if item.port.value == port)


def _faithfulness_finding(verdict: NLIVerdict, artifact: ArtifactRef, claims: tuple[str, ...]) -> Finding:
    return Finding(
        code="answer_faithfulness.supported" if verdict.entailed else "answer_faithfulness.unsupported",
        severity=FindingSeverity.INFO if verdict.entailed else FindingSeverity.ERROR,
        message=verdict.reason,
        evidence=(
            claim_evidence(artifact, f"text#statement-{verdict.statement_index}", claims[verdict.statement_index]),
        ),
    )


def _complete_matrix(rows: tuple[NLIVerdictsOutput, ...], claim_count: int) -> bool:
    return all(complete_verdicts(row, claim_count) for row in rows)


def _caused_errors(
    reference_rows: tuple[NLIVerdictsOutput, ...],
    candidate_rows: tuple[NLIVerdictsOutput, ...],
    correctness: NLIVerdictsOutput,
) -> tuple[bool, ...]:
    relevant_context = [any(item.entailed for item in ordered_verdicts(row)) for row in reference_rows]
    candidate_matrix = [ordered_verdicts(row) for row in candidate_rows]
    correct = tuple(item.entailed for item in ordered_verdicts(correctness))
    return tuple(
        not correct[index]
        and any(
            relevant_context[context_index] and row[index].entailed
            for context_index, row in enumerate(candidate_matrix)
        )
        for index in range(len(correct))
    )


def _noise_finding(index: int, verdict: NLIVerdict, caused: bool, artifact: ArtifactRef, claim: str) -> Finding:
    if verdict.entailed:
        code, severity = "noise_sensitivity.correct", FindingSeverity.INFO
    elif caused:
        code, severity = "noise_sensitivity.caused_error", FindingSeverity.ERROR
    else:
        code, severity = "noise_sensitivity.unattributed_error", FindingSeverity.WARNING
    return Finding(
        code=code,
        severity=severity,
        message=verdict.reason,
        evidence=(claim_evidence(artifact, f"text#statement-{index}", claim),),
    )
