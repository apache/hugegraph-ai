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

"""Ranking needs document ids; judged retrieval also needs a question."""

import pytest
from fakes import NOW, ScriptedJudge

from hugegraph_llm_eval import (
    HitAtKEvaluator,
    InMemoryArtifactStore,
    MRREvaluator,
    RecallAtKEvaluator,
    evaluate,
    retrieval_input,
)
from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationRecordStatus
from hugegraph_llm_eval.contracts.errors import FailureCategory
from hugegraph_llm_eval.contracts.identity import ComponentRef
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.integrations.retrieval.evaluators.judged import (
    ContextEntityRecallEvaluator,
    ContextPrecisionEvaluator,
    ContextRelevancyEvaluator,
    EvidenceRecallEvaluator,
)
from hugegraph_llm_eval.integrations.retrieval.materializers import RetrievalArtifactMaterializer


@pytest.mark.parametrize("evaluator_type", (RecallAtKEvaluator, HitAtKEvaluator, MRREvaluator))
def test_ranking_accepts_the_input_builders_default_question(evaluator_type) -> None:
    store = InMemoryArtifactStore()
    evaluation_input = retrieval_input(store, candidate_doc_ids=("doc-a",), reference_doc_ids=("doc-a",))
    evaluator = evaluator_type(RetrievalArtifactMaterializer(store), clock=lambda: NOW)

    record = evaluate([evaluator], evaluation_input).records[0]

    assert record.status is EvaluationRecordStatus.COMPLETED
    assert record.measurements
    assert all(measurement.value == 1.0 for measurement in record.measurements)


@pytest.mark.parametrize("question", ("", " \t\n"))
@pytest.mark.parametrize(
    "evaluator_type",
    (ContextPrecisionEvaluator, ContextRelevancyEvaluator, ContextEntityRecallEvaluator, EvidenceRecallEvaluator),
)
def test_judged_retrieval_rejects_blank_questions_before_calling_the_judge(evaluator_type, question) -> None:
    store = InMemoryArtifactStore()
    evaluation_input = retrieval_input(
        store,
        candidate_doc_ids=("doc-a",),
        reference_doc_ids=("doc-a",),
        question=question,
        candidate_contexts=("Alice lives in Paris.",),
        reference_answer="Alice lives in Paris.",
        reference_evidence=("Alice lives in Paris.",),
    )
    judge = ScriptedJudge(())
    content = JudgeContent(
        component=ComponentRef(namespace="test", name="instructions", revision="v1"),
        text="Judge relevance using the supplied question and evidence.",
    )
    evaluator = evaluator_type(
        RetrievalArtifactMaterializer(store),
        judge=judge,
        prompt=content,
        rubric=content,
        clock=lambda: NOW,
    )

    record = evaluate([evaluator], evaluation_input).records[0]

    assert record.status is EvaluationRecordStatus.FAILED
    assert record.failure is not None
    assert record.failure.category is FailureCategory.INVALID_INPUT
    assert record.failure.code == "retrieval_question_required"
    assert not judge.requests
    assert not record.judge_calls
