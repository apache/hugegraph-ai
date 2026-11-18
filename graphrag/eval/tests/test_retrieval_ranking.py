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

"""Ranking metrics keep v1 normalization and rank semantics in the standalone SDK."""

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if not os.environ.get("HUGEGRAPH_LLM_EVAL_TEST_INSTALLED") and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hugegraph_llm_eval import (  # noqa: E402
    EvaluationContext,
    HitAtKEvaluator,
    InMemoryArtifactStore,
    MRREvaluator,
    RecallAtKEvaluator,
)
from hugegraph_llm_eval.contracts.domain.artifacts import (  # noqa: E402
    ArtifactDescriptor,
    ArtifactRetention,
    ArtifactSensitivity,
)
from hugegraph_llm_eval.contracts.domain.evaluation import (  # noqa: E402
    EvaluationInput,
    EvaluationRecordStatus,
    EvaluationSubject,
)
from hugegraph_llm_eval.contracts.domain.operation import PortName  # noqa: E402
from hugegraph_llm_eval.contracts.identity import EvaluationRunId, SchemaRef  # noqa: E402
from hugegraph_llm_eval.evaluation.options import CancellationToken  # noqa: E402
from hugegraph_llm_eval.integrations.retrieval.materializers import (  # noqa: E402
    RETRIEVAL_COMPARISON_INPUT_SCHEMA,
    RetrievalArtifactMaterializer,
    RetrievalMaterializationError,
)

NOW = datetime(2026, 7, 25, tzinfo=UTC)


def _store() -> InMemoryArtifactStore:
    return InMemoryArtifactStore(clock=lambda: NOW)


def _put(store: InMemoryArtifactStore, name: str, payload: bytes):
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
    return EvaluationContext(
        run_id=EvaluationRunId.new(),
        request_key="retrieval:case-1",
        deadline=None,
        cancellation=CancellationToken(),
    )


def _measurements(draft) -> dict[str, float]:
    return {measurement.name: measurement.value for measurement in draft.measurements}


def test_materializer_requires_candidate_reference_and_query() -> None:
    store = _store()
    materialized = RetrievalArtifactMaterializer(store).comparison(_input(store))

    assert materialized.query.question == "Where is the answer?"
    assert materialized.candidate.doc_ids == ("DOC A", "doc c", "DOC B")
    assert materialized.reference.answer == "answer"

    incomplete = EvaluationInput.create(
        schema_ref=RETRIEVAL_COMPARISON_INPUT_SCHEMA,
        subjects=_input(store).subjects[:2],
    )
    try:
        RetrievalArtifactMaterializer(store).comparison(incomplete)
    except RetrievalMaterializationError as exc:
        assert "missing required ports" in str(exc)
    else:  # pragma: no cover - the call must fail
        raise AssertionError("incomplete input must not materialize")


def test_recall_hit_and_mrr_preserve_normalization_and_rank_semantics() -> None:
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


def test_empty_gold_is_a_completed_zero_measurement_not_missing() -> None:
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
