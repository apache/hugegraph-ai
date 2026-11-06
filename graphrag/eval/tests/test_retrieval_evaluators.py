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

"""Typed retrieval inputs preserve v1 ranking semantics in v2 records."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fakes import ScriptedJudge

from hugegraph_llm_eval.artifacts.memory import InMemoryArtifactStore
from hugegraph_llm_eval.contracts.domain.artifacts import (
    ArtifactDescriptor,
    ArtifactRetention,
    ArtifactSensitivity,
)
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationInput,
    EvaluationRecordStatus,
    EvaluationSubject,
)
from hugegraph_llm_eval.contracts.domain.operation import PortName
from hugegraph_llm_eval.contracts.identity import ComponentRef, EvaluationRunId, SchemaRef
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.options import CancellationToken
from hugegraph_llm_eval.integrations.retrieval.evaluators.coverage import ReferenceEntitiesOutput
from hugegraph_llm_eval.integrations.retrieval.evaluators.judged import (
    ContextEntityRecallEvaluator,
    ContextEntityRecallOutput,
    ContextEntityVerdict,
    ContextPrecisionEvaluator,
    ContextPrecisionOutput,
    ContextPrecisionVerdict,
    ContextRelevancyEvaluator,
    ContextRelevancyOutput,
    ContextRelevancyVerdict,
    EvidenceRecallEvaluator,
    EvidenceRecallOutput,
    EvidenceVerdict,
)
from hugegraph_llm_eval.integrations.retrieval.evaluators.ranking import (
    HitAtKEvaluator,
    MRREvaluator,
    RecallAtKEvaluator,
)
from hugegraph_llm_eval.integrations.retrieval.materializers import (
    RETRIEVAL_COMPARISON_INPUT_SCHEMA,
    RetrievalArtifactMaterializer,
    RetrievalMaterializationError,
)

NOW = datetime(2026, 7, 25, tzinfo=UTC)


def _store() -> InMemoryArtifactStore:
    return InMemoryArtifactStore(clock=lambda: NOW)


def _put(store: InMemoryArtifactStore, name: str, payload: bytes):
    """_put."""
    return store.put(
        payload,
        ArtifactDescriptor(
            media_type="application/json",
            schema_ref=SchemaRef(namespace="retrieval", name=name, version=1),
            sensitivity=ArtifactSensitivity.INTERNAL,
            retention=ArtifactRetention.STANDARD,
        ),
    )


def _input(store: InMemoryArtifactStore) -> EvaluationInput:
    """_input."""
    candidate = _put(
        store,
        "candidate",
        b'{"doc_ids":[" DOC A ","doc c","DOC B"],"contexts":["A","C","B"]}',
    )
    reference = _put(
        store,
        "reference",
        b'{"doc_ids":["doc a","doc b"],"evidence":["A","B"],"answer":"answer"}',
    )
    query = _put(store, "query", b'{"question":"Where is the answer?"}')
    return EvaluationInput.create(
        schema_ref=RETRIEVAL_COMPARISON_INPUT_SCHEMA,
        subjects=(
            EvaluationSubject(port=PortName(value="retrieval_candidate"), artifact=candidate),
            EvaluationSubject(port=PortName(value="retrieval_reference"), artifact=reference),
            EvaluationSubject(port=PortName(value="query"), artifact=query),
        ),
    )


def _context() -> EvaluationContext:
    """_context."""
    return EvaluationContext(
        run_id=EvaluationRunId.new(),
        request_key="retrieval:case-1",
        deadline=None,
        cancellation=CancellationToken(),
    )


def _content(name: str) -> JudgeContent:
    """_content."""
    return JudgeContent(
        component=ComponentRef(namespace="retrieval", name=name, revision="v1"),
        text=f"Apply the {name} instructions to every supplied indexed item.",
    )


def _measurements(draft) -> dict[str, float]:
    """_measurements."""
    return {measurement.name: measurement.value for measurement in draft.measurements}


def test_retrieval_materializer_requires_typed_candidate_reference_and_query(tmp_path: Path) -> None:
    """test_retrieval_materializer_requires_typed_candidate_reference_and_query."""
    store = _store()
    materialized = RetrievalArtifactMaterializer(store).comparison(_input(store))

    assert materialized.query.question == "Where is the answer?"
    assert materialized.candidate.doc_ids == ("DOC A", "doc c", "DOC B")
    assert materialized.reference.answer == "answer"

    incomplete = EvaluationInput.create(
        schema_ref=RETRIEVAL_COMPARISON_INPUT_SCHEMA,
        subjects=_input(store).subjects[:2],
    )
    with pytest.raises(RetrievalMaterializationError, match="missing required ports"):
        RetrievalArtifactMaterializer(store).comparison(incomplete)


def test_recall_hit_and_mrr_preserve_normalization_and_rank_semantics(tmp_path: Path) -> None:
    """test_recall_hit_and_mrr_preserve_normalization_and_rank_semantics."""
    store = _store()
    materializer = RetrievalArtifactMaterializer(store)
    evaluators = (
        RecallAtKEvaluator(materializer, k_values=(1, 2, 3), clock=lambda: NOW),
        HitAtKEvaluator(materializer, k_values=(1, 2, 3), clock=lambda: NOW),
        MRREvaluator(materializer, clock=lambda: NOW),
    )

    drafts = tuple(evaluator.evaluate(_input(store), _context()) for evaluator in evaluators)

    assert all(draft.status is EvaluationRecordStatus.COMPLETED for draft in drafts)
    assert _measurements(drafts[0]) == {"recall@1": 0.5, "recall@2": 0.5, "recall@3": 1.0}
    assert _measurements(drafts[1]) == {
        "hit_any@1": 1.0,
        "hit_all@1": 0.0,
        "hit_any@2": 1.0,
        "hit_all@2": 0.0,
        "hit_any@3": 1.0,
        "hit_all@3": 1.0,
    }
    assert _measurements(drafts[2]) == {"mrr": 1.0}


def test_empty_gold_is_a_completed_zero_measurement_not_missing(tmp_path: Path) -> None:
    """test_empty_gold_is_a_completed_zero_measurement_not_missing."""
    store = _store()
    evaluation_input = _input(store)
    empty_reference = _put(store, "reference", b'{"doc_ids":[],"evidence":[],"answer":""}')
    evaluation_input = EvaluationInput.create(
        schema_ref=RETRIEVAL_COMPARISON_INPUT_SCHEMA,
        subjects=tuple(
            EvaluationSubject(port=subject.port, artifact=empty_reference)
            if subject.port.value == "retrieval_reference"
            else subject
            for subject in evaluation_input.subjects
        ),
    )

    draft = RecallAtKEvaluator(
        RetrievalArtifactMaterializer(store),
        k_values=(1,),
        clock=lambda: NOW,
    ).evaluate(evaluation_input, _context())

    assert draft.status is EvaluationRecordStatus.COMPLETED
    assert _measurements(draft) == {"recall@1": 0.0}


def test_context_precision_and_relevancy_preserve_every_context_verdict(tmp_path: Path) -> None:
    """test_context_precision_and_relevancy_preserve_every_context_verdict."""
    store = _store()
    precision_judge = ScriptedJudge(
        (
            ContextPrecisionOutput(
                verdicts=(
                    ContextPrecisionVerdict(context_index=0, relevant=True, reason="direct support"),
                    ContextPrecisionVerdict(context_index=1, relevant=False, reason="unrelated"),
                    ContextPrecisionVerdict(context_index=2, relevant=True, reason="partial support"),
                )
            ),
        )
    )
    relevancy_judge = ScriptedJudge(
        (
            ContextRelevancyOutput(
                verdicts=(
                    ContextRelevancyVerdict(context_index=0, score=2, reason="direct"),
                    ContextRelevancyVerdict(context_index=1, score=0, reason="none"),
                    ContextRelevancyVerdict(context_index=2, score=1, reason="partial"),
                )
            ),
        )
    )
    materializer = RetrievalArtifactMaterializer(store)
    precision = ContextPrecisionEvaluator(
        materializer,
        judge=precision_judge,
        prompt=_content("context_precision_prompt"),
        rubric=_content("context_precision_rubric"),
        clock=lambda: NOW,
    ).evaluate(_input(store), _context())
    relevancy = ContextRelevancyEvaluator(
        materializer,
        judge=relevancy_judge,
        prompt=_content("context_relevancy_prompt"),
        rubric=_content("context_relevancy_rubric"),
        clock=lambda: NOW,
    ).evaluate(_input(store), _context())

    assert _measurements(precision) == {"context_precision": 0.8333}
    assert _measurements(relevancy) == {"context_relevancy": 0.5}
    assert len(precision.findings) == len(relevancy.findings) == 3
    assert [item.evidence[0].locator for item in precision.findings] == [
        "contexts[0]",
        "contexts[1]",
        "contexts[2]",
    ]
    assert len(precision.judge_calls) == len(relevancy.judge_calls) == 1


def test_context_entity_and_evidence_recall_keep_semantic_item_reasons(tmp_path: Path) -> None:
    """Context entity recall is a direct LLM judgement, not an exact-match set intersection."""
    store = _store()
    materializer = RetrievalArtifactMaterializer(store)
    entity_judge = ScriptedJudge(
        (
            ReferenceEntitiesOutput(entities=("answer", "Car")),
            ContextEntityRecallOutput(
                has_reference_entities=True,
                verdicts=(
                    ContextEntityVerdict(
                        entity_index=0,
                        entity="answer",
                        covered=False,
                        reason="not supported by the retrieved contexts",
                    ),
                    ContextEntityVerdict(
                        entity_index=1,
                        entity="Car",
                        covered=True,
                        reason="a synonymous entity reference is present",
                    ),
                ),
            ),
        )
    )
    evidence_judge = ScriptedJudge(
        (
            EvidenceRecallOutput(
                verdicts=(
                    EvidenceVerdict(evidence_index=0, attributed=True, reason="A is present"),
                    EvidenceVerdict(evidence_index=1, attributed=False, reason="B is missing"),
                )
            ),
        )
    )
    entity = ContextEntityRecallEvaluator(
        materializer,
        judge=entity_judge,
        prompt=_content("entity_extraction_prompt"),
        rubric=_content("entity_extraction_rubric"),
        clock=lambda: NOW,
    ).evaluate(_input(store), _context())
    evidence = EvidenceRecallEvaluator(
        materializer,
        judge=evidence_judge,
        prompt=_content("evidence_recall_prompt"),
        rubric=_content("evidence_recall_rubric"),
        clock=lambda: NOW,
    ).evaluate(_input(store), _context())

    assert _measurements(entity) == {"context_entity_recall_llm": 0.5}
    assert _measurements(evidence) == {"evidence_recall_llm": 0.5}
    assert len(entity.judge_calls) == 2
    assert "reference_answer" in entity_judge.requests[0].messages[-1].content
    assert "context_index" not in entity_judge.requests[0].messages[-1].content
    assert "context_index" in entity_judge.requests[1].messages[-1].content
    assert [item.code for item in evidence.findings] == [
        "evidence_recall.supported",
        "evidence_recall.missing",
    ]
    assert evidence.findings[1].message == "B is missing"


def test_missing_context_verdict_is_failed_provider_output(tmp_path: Path) -> None:
    """test_missing_context_verdict_is_failed_provider_output."""
    store = _store()
    judge = ScriptedJudge(
        (
            ContextPrecisionOutput(
                verdicts=(ContextPrecisionVerdict(context_index=0, relevant=True, reason="only one"),)
            ),
        )
    )
    draft = ContextPrecisionEvaluator(
        RetrievalArtifactMaterializer(store),
        judge=judge,
        prompt=_content("context_precision_prompt"),
        rubric=_content("context_precision_rubric"),
        clock=lambda: NOW,
    ).evaluate(_input(store), _context())

    assert draft.status is EvaluationRecordStatus.FAILED
    assert draft.measurements == ()
    assert draft.failure is not None
    assert draft.failure.code == "incomplete_context_verdicts"
