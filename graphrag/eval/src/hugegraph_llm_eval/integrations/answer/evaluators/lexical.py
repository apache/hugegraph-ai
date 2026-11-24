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

"""Deterministic ROUGE-L Evaluator."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rouge_score import rouge_scorer

from hugegraph_llm_eval.contracts.digests import canonical_digest
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationInput,
    EvaluationRecordDraft,
    EvaluationRecordStatus,
    EvaluatorDescriptor,
    Measurement,
    MeasurementDirection,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.contracts.identity import EvaluatorRef, SchemaRef
from hugegraph_llm_eval.integrations.answer.materializers import (
    ANSWER_COMPARISON_INPUT_SCHEMA,
    AnswerArtifactMaterializer,
    AnswerMaterializationError,
)
from hugegraph_llm_eval.integrations.answer.schemas import AnswerComparisonInput
from hugegraph_llm_eval.utils.text_normalize import tokenize


@dataclass(frozen=True, slots=True)
class _LexicalSpec:
    invocation_key: str
    evaluator: EvaluatorRef
    algorithm: str
    calculator: Callable[[AnswerComparisonInput], Mapping[str, float]]


class _LexicalEvaluator:
    input_type = EvaluationInput

    def __init__(
        self,
        materializer: AnswerArtifactMaterializer,
        spec: _LexicalSpec,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._materializer = materializer
        self._spec = spec
        self._clock = clock
        self.descriptor = EvaluatorDescriptor(
            evaluator=spec.evaluator,
            implementation_digest=canonical_digest({"algorithm": spec.algorithm, "version": 2}),
            input_schema=ANSWER_COMPARISON_INPUT_SCHEMA,
            output_schema=SchemaRef(namespace="answer", name=f"{spec.algorithm}_record", version=1),
        )

    @property
    def invocation_key(self) -> str:
        return self._spec.invocation_key

    def evaluate(self, evaluation_input: EvaluationInput, context: EvaluationContext) -> EvaluationRecordDraft:
        del context
        try:
            materialized = self._materializer.comparison(evaluation_input)
        except AnswerMaterializationError as exc:
            return self._failure(str(exc))
        scores = self._spec.calculator(materialized)
        measurements = tuple(
            Measurement(
                name=name,
                value=value,
                unit="ratio",
                direction=MeasurementDirection.HIGHER_IS_BETTER,
            )
            for name, value in scores.items()
        )
        return EvaluationRecordDraft(
            invocation_key=self._spec.invocation_key,
            evaluator=self.descriptor.evaluator,
            status=EvaluationRecordStatus.COMPLETED,
            measurements=measurements,
            reason=f"{self._spec.algorithm} produced {len(measurements)} lexical measurements",
            attempts=1,
            latency_ms=0,
            created_at=self._clock(),
        )

    def _failure(self, message: str) -> EvaluationRecordDraft:
        return EvaluationRecordDraft(
            invocation_key=self._spec.invocation_key,
            evaluator=self.descriptor.evaluator,
            status=EvaluationRecordStatus.FAILED,
            reason=message,
            attempts=1,
            latency_ms=0,
            failure=FailureDetail(
                category=FailureCategory.INVALID_INPUT,
                code="answer_materialization_failed",
                message=message,
                retryable=False,
            ),
            created_at=self._clock(),
        )


class RougeLEvaluator(_LexicalEvaluator):
    def __init__(self, materializer: AnswerArtifactMaterializer, *, clock: Callable[[], datetime]) -> None:
        super().__init__(
            materializer,
            _LexicalSpec(
                "rouge_l",
                EvaluatorRef(namespace="answer", name="rouge_l", revision="v2"),
                "rouge_l",
                _rouge_scores,
            ),
            clock=clock,
        )


def _rouge_scorer():
    try:
        from rouge_score import rouge_scorer
    except ImportError as exc:
        msg = "ROUGE-L scoring requires the 'rouge' extra: pip install hugegraph-llm-eval[rouge]"
        raise ImportError(msg) from exc
    return rouge_scorer


def _rouge_scores(value: AnswerComparisonInput) -> Mapping[str, float]:
    if not value.candidate.text.strip() and not any(answer.strip() for answer in value.reference.answers):
        return {"rouge_l_precision": 1.0, "rouge_l_recall": 1.0, "rouge_l_f1": 1.0}
    if not value.candidate.text.strip():
        return {"rouge_l_precision": 0.0, "rouge_l_recall": 0.0, "rouge_l_f1": 0.0}
    if value.source.language == "zh":
        scores = tuple(_chinese_rouge(value.candidate.text, answer) for answer in value.reference.answers)
    else:
        scorer = _rouge_scorer().RougeScorer(["rougeL"], use_stemmer=True)
        scores = tuple(_english_rouge(scorer, value.candidate.text, answer) for answer in value.reference.answers)
    return max(scores, key=lambda item: item["rouge_l_f1"])


def _english_rouge(
    scorer: rouge_scorer.RougeScorer,
    prediction: str,
    reference: str,
) -> dict[str, float]:
    if not reference.strip():
        return {"rouge_l_precision": 0.0, "rouge_l_recall": 0.0, "rouge_l_f1": 0.0}
    score = scorer.score(reference, prediction)["rougeL"]
    return {
        "rouge_l_precision": round(score.precision, 4),
        "rouge_l_recall": round(score.recall, 4),
        "rouge_l_f1": round(score.fmeasure, 4),
    }


def _chinese_rouge(prediction: str, reference: str) -> dict[str, float]:
    prediction_tokens = tokenize(prediction, "zh")
    reference_tokens = tokenize(reference, "zh")
    common = _lcs_length(prediction_tokens, reference_tokens)
    precision = common / len(prediction_tokens) if prediction_tokens else 0.0
    recall = common / len(reference_tokens) if reference_tokens else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "rouge_l_precision": round(precision, 4),
        "rouge_l_recall": round(recall, 4),
        "rouge_l_f1": round(f1, 4),
    }


def _lcs_length(first: list[str], second: list[str]) -> int:
    previous = [0] * (len(second) + 1)
    for left in first:
        current = [0]
        for index, right in enumerate(second, start=1):
            current.append(previous[index - 1] + 1 if left == right else max(previous[index], current[-1]))
        previous = current
    return previous[-1]
