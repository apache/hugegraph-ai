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

"""Deterministic Recall@K, Hit@K, and MRR Evaluators."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

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
from hugegraph_llm_eval.integrations.retrieval.materializers import (
    RETRIEVAL_COMPARISON_INPUT_SCHEMA,
    RetrievalArtifactMaterializer,
    RetrievalMaterializationError,
)
from hugegraph_llm_eval.integrations.retrieval.schemas import RetrievalComparisonInput
from hugegraph_llm_eval.utils.text_normalize import normalize_doc_id


@dataclass(frozen=True, slots=True)
class _RankingSpec:
    invocation_key: str
    evaluator: EvaluatorRef
    algorithm: str
    calculator: Callable[[RetrievalComparisonInput, tuple[int, ...]], Mapping[str, float]]


class _RankingEvaluator:
    input_type = EvaluationInput

    def __init__(
        self,
        materializer: RetrievalArtifactMaterializer,
        spec: _RankingSpec,
        *,
        clock: Callable[[], datetime],
        k_values: tuple[int, ...] = (),
    ) -> None:
        if k_values and (any(value <= 0 for value in k_values) or len(k_values) != len(set(k_values))):
            raise ValueError("k_values must contain unique positive integers")
        self._materializer = materializer
        self._spec = spec
        self._clock = clock
        self._k_values = k_values
        self.descriptor = EvaluatorDescriptor(
            evaluator=spec.evaluator,
            implementation_digest=canonical_digest(
                {
                    "algorithm": spec.algorithm,
                    "version": 2,
                    "k_values": list(k_values),
                    "question_required": False,
                }
            ),
            input_schema=RETRIEVAL_COMPARISON_INPUT_SCHEMA,
            output_schema=SchemaRef(namespace="retrieval", name=f"{spec.algorithm}_record", version=1),
        )

    @property
    def invocation_key(self) -> str:
        return self._spec.invocation_key

    def evaluate(self, evaluation_input: EvaluationInput, context: EvaluationContext) -> EvaluationRecordDraft:
        del context
        try:
            materialized = self._materializer.comparison(evaluation_input)
        except RetrievalMaterializationError as exc:
            return self._failure(str(exc))
        scores = self._spec.calculator(materialized, self._k_values)
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
            reason=f"{self._spec.algorithm} produced {len(measurements)} ranking measurements",
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
                code="retrieval_materialization_failed",
                message=message,
                retryable=False,
            ),
            created_at=self._clock(),
        )


class RecallAtKEvaluator(_RankingEvaluator):
    def __init__(
        self,
        materializer: RetrievalArtifactMaterializer,
        *,
        k_values: tuple[int, ...] = (1, 5, 10, 20),
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(
            materializer,
            _RankingSpec(
                "recall_at_k",
                EvaluatorRef(namespace="retrieval", name="recall_at_k", revision="v2"),
                "recall_at_k",
                _recall_scores,
            ),
            clock=clock,
            k_values=k_values,
        )


class HitAtKEvaluator(_RankingEvaluator):
    def __init__(
        self,
        materializer: RetrievalArtifactMaterializer,
        *,
        k_values: tuple[int, ...] = (1, 5, 10, 20),
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(
            materializer,
            _RankingSpec(
                "hit_at_k",
                EvaluatorRef(namespace="retrieval", name="hit_at_k", revision="v2"),
                "hit_at_k",
                _hit_scores,
            ),
            clock=clock,
            k_values=k_values,
        )


class MRREvaluator(_RankingEvaluator):
    def __init__(self, materializer: RetrievalArtifactMaterializer, *, clock: Callable[[], datetime]) -> None:
        super().__init__(
            materializer,
            _RankingSpec(
                "mrr",
                EvaluatorRef(namespace="retrieval", name="mrr", revision="v2"),
                "mrr",
                _mrr_scores,
            ),
            clock=clock,
        )


def _normalize(value: str) -> str:
    return normalize_doc_id(value)


def _recall_scores(materialized: RetrievalComparisonInput, k_values: tuple[int, ...]) -> Mapping[str, float]:
    gold = {_normalize(value) for value in materialized.reference.doc_ids}
    return {
        f"recall@{k}": round(
            len({_normalize(value) for value in materialized.candidate.doc_ids[:k]} & gold) / len(gold), 4
        )
        if gold
        else 0.0
        for k in k_values
    }


def _hit_scores(materialized: RetrievalComparisonInput, k_values: tuple[int, ...]) -> Mapping[str, float]:
    gold = {_normalize(value) for value in materialized.reference.doc_ids}
    scores: dict[str, float] = {}
    for k in k_values:
        selected = {_normalize(value) for value in materialized.candidate.doc_ids[:k]}
        scores[f"hit_any@{k}"] = float(bool(gold and selected & gold))
        scores[f"hit_all@{k}"] = float(bool(gold and gold <= selected))
    return scores


def _mrr_scores(materialized: RetrievalComparisonInput, k_values: tuple[int, ...]) -> Mapping[str, float]:
    del k_values
    gold = {_normalize(value) for value in materialized.reference.doc_ids}
    for rank, value in enumerate(materialized.candidate.doc_ids, start=1):
        if _normalize(value) in gold:
            return {"mrr": round(1 / rank, 4)}
    return {"mrr": 0.0}
