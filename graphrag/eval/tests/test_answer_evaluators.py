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

"""Typed answer inputs preserve lexical metric behavior and language handling."""

import importlib.util
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
from hugegraph_llm_eval.integrations.answer.evaluators.judged import (
    AnswerCorrectnessEvaluator,
    ClaimDecompositionOutput,
    CorrectnessMatch,
    CorrectnessOutput,
    FactualCorrectnessEvaluator,
    FaithfulnessEvaluator,
    NLIVerdict,
    NLIVerdictsOutput,
    NoiseSensitivityEvaluator,
    UnmatchedClaim,
)
from hugegraph_llm_eval.integrations.answer.evaluators.lexical import (
    RougeLEvaluator,
)
from hugegraph_llm_eval.integrations.answer.materializers import (
    ANSWER_COMPARISON_INPUT_SCHEMA,
    AnswerArtifactMaterializer,
)

NOW = datetime(2026, 7, 25, tzinfo=UTC)

requires_rouge = pytest.mark.skipif(
    importlib.util.find_spec("rouge_score") is None,
    reason="install hugegraph-llm-eval[rouge] to run ROUGE-L contracts",
)


def _store() -> InMemoryArtifactStore:
    return InMemoryArtifactStore(clock=lambda: NOW)


def _put(store: InMemoryArtifactStore, name: str, payload: bytes):
    """_put."""
    return store.put(
        payload,
        ArtifactDescriptor(
            media_type="application/json",
            schema_ref=SchemaRef(namespace="answer", name=name, version=1),
            sensitivity=ArtifactSensitivity.INTERNAL,
            retention=ArtifactRetention.STANDARD,
        ),
    )


def _input(
    store: InMemoryArtifactStore,
    *,
    candidate: str = "Paris is the capital of France",
    references: tuple[str, ...] = ("The capital of France is Paris", "Paris"),
    contexts: tuple[str, ...] = ("Paris is in France",),
    language: str = "en",
) -> EvaluationInput:
    """_input."""
    candidate_artifact = _put(store, "candidate", ('{"text":' + _json_string(candidate) + "}").encode())
    reference_artifact = _put(
        store,
        "reference",
        ('{"answers":' + _json_array(references) + "}").encode(),
    )
    source_artifact = _put(
        store,
        "source",
        (
            '{"question":"What is France capital?","contexts":'
            + _json_array(contexts)
            + ',"language":'
            + _json_string(language)
            + "}"
        ).encode(),
    )
    return EvaluationInput.create(
        schema_ref=ANSWER_COMPARISON_INPUT_SCHEMA,
        subjects=(
            EvaluationSubject(port=PortName(value="answer_candidate"), artifact=candidate_artifact),
            EvaluationSubject(port=PortName(value="answer_reference"), artifact=reference_artifact),
            EvaluationSubject(port=PortName(value="answer_source"), artifact=source_artifact),
        ),
    )


def _json_string(value: str) -> str:
    """_json_string."""
    import json

    return json.dumps(value, ensure_ascii=False)


def _json_array(values: tuple[str, ...]) -> str:
    """_json_array."""
    import json

    return json.dumps(values, ensure_ascii=False)


def _context() -> EvaluationContext:
    """_context."""
    return EvaluationContext(
        run_id=EvaluationRunId.new(),
        request_key="answer:case-1",
        deadline=None,
        cancellation=CancellationToken(),
    )


def _content(name: str) -> JudgeContent:
    """_content."""
    return JudgeContent(
        component=ComponentRef(namespace="answer", name=name, revision="v1"),
        text=f"Apply the {name} instructions to every supplied indexed claim.",
    )


def _claims(*claims: str) -> ClaimDecompositionOutput:
    """_claims."""
    return ClaimDecompositionOutput(claims=claims)


def _nli(*verdicts: tuple[int, bool, str]) -> NLIVerdictsOutput:
    """_nli."""
    return NLIVerdictsOutput(
        verdicts=tuple(
            NLIVerdict(statement_index=index, entailed=entailed, reason=reason) for index, entailed, reason in verdicts
        )
    )


def _measurements(draft) -> dict[str, float]:
    """_measurements."""
    return {measurement.name: measurement.value for measurement in draft.measurements}


def test_answer_materializer_preserves_multiple_references_and_contexts(tmp_path: Path) -> None:
    """test_answer_materializer_preserves_multiple_references_and_contexts."""
    store = _store()
    materialized = AnswerArtifactMaterializer(store).comparison(_input(store))

    assert materialized.candidate.text.startswith("Paris")
    assert materialized.reference.answers == ("The capital of France is Paris", "Paris")
    assert materialized.source.contexts == ("Paris is in France",)


@requires_rouge
def test_rouge_l_evaluator_chooses_best_reference_and_emits_typed_measurements(tmp_path: Path) -> None:
    """test_rouge_l_evaluator_chooses_best_reference_and_emits_typed_measurements."""
    store = _store()
    materializer = AnswerArtifactMaterializer(store)
    draft = RougeLEvaluator(materializer, clock=lambda: NOW).evaluate(_input(store, candidate="Paris"), _context())

    assert draft.status is EvaluationRecordStatus.COMPLETED
    assert _measurements(draft) == {
        "rouge_l_precision": 1.0,
        "rouge_l_recall": 1.0,
        "rouge_l_f1": 1.0,
    }


@requires_rouge
def test_empty_candidate_and_reference_keep_v1_vacuous_match_semantics(tmp_path: Path) -> None:
    """test_empty_candidate_and_reference_keep_v1_vacuous_match_semantics."""
    store = _store()
    materializer = AnswerArtifactMaterializer(store)
    evaluation_input = _input(store, candidate="", references=("",))

    rouge = RougeLEvaluator(materializer, clock=lambda: NOW).evaluate(evaluation_input, _context())

    assert _measurements(rouge)["rouge_l_f1"] == 1.0


@requires_rouge
def test_chinese_rouge_keeps_non_ascii_text(tmp_path: Path) -> None:
    """test_chinese_rouge_keeps_non_ascii_text."""
    store = _store()
    draft = RougeLEvaluator(AnswerArtifactMaterializer(store), clock=lambda: NOW).evaluate(
        _input(store, candidate="巴黎是法国首都", references=("法国首都是巴黎",), language="zh"),
        _context(),
    )

    assert 0 < _measurements(draft)["rouge_l_f1"] <= 1


def test_answer_correctness_preserves_matches_false_positives_and_false_negatives(tmp_path: Path) -> None:
    """test_answer_correctness_preserves_matches_false_positives_and_false_negatives."""
    store = _store()
    judge = ScriptedJudge(
        (
            _claims("Paris is the capital", "France is in Europe"),
            _claims("Paris is the capital"),
            CorrectnessOutput(
                matches=(CorrectnessMatch(candidate_index=0, reference_index=0, reason="same fact"),),
                false_positives=(UnmatchedClaim(statement_index=1, reason="not in reference"),),
                false_negatives=(),
            ),
        )
    )
    draft = AnswerCorrectnessEvaluator(
        AnswerArtifactMaterializer(store),
        judge=judge,
        prompt=_content("answer_correctness_prompt"),
        rubric=_content("answer_correctness_rubric"),
        clock=lambda: NOW,
    ).evaluate(_input(store), _context())

    assert draft.status is EvaluationRecordStatus.COMPLETED
    assert _measurements(draft) == {
        "answer_correctness": 0.6667,
        "answer_tp": 1.0,
        "answer_fp": 1.0,
        "answer_fn": 0.0,
    }
    assert len(draft.judge_calls) == 3
    assert [item.code for item in draft.findings] == [
        "answer_correctness.tp",
        "answer_correctness.fp",
    ]
    assert [[link.description for link in item.evidence] for item in draft.findings] == [
        ["Paris is the capital", "Paris is the capital"],
        ["France is in Europe"],
    ]
    assert "Apply the answer_correctness_prompt instructions" in judge.requests[0].messages[0].content
    assert "Apply the answer_correctness_prompt instructions" in judge.requests[2].messages[0].content


def test_default_answer_task_prompts_use_chinese_few_shots(tmp_path: Path) -> None:
    """The builtin path opts into Chinese task prompts without overriding injected prompts."""
    store = _store()
    judge = ScriptedJudge(
        (
            _claims("Paris is the capital"),
            _claims("Paris is the capital"),
            CorrectnessOutput(
                matches=(CorrectnessMatch(candidate_index=0, reference_index=0, reason="same fact"),),
                false_positives=(),
                false_negatives=(),
            ),
        )
    )
    draft = AnswerCorrectnessEvaluator(
        AnswerArtifactMaterializer(store),
        judge=judge,
        prompt=_content("answer_correctness_prompt"),
        rubric=_content("answer_correctness_rubric"),
        clock=lambda: NOW,
        use_default_task_prompts=True,
    ).evaluate(_input(store), _context())

    assert draft.status is EvaluationRecordStatus.COMPLETED
    assert "给定一个问题和一个回答" in judge.requests[0].messages[0].content
    assert '"claims"' in judge.requests[0].messages[0].content
    assert "给定标准答案和候选答案中的若干陈述" in judge.requests[2].messages[0].content
    assert '"matches"' in judge.requests[2].messages[0].content


def test_factual_correctness_runs_bidirectional_claim_verification(tmp_path: Path) -> None:
    """test_factual_correctness_runs_bidirectional_claim_verification."""
    store = _store()
    judge = ScriptedJudge(
        (
            _claims("Paris is the capital", "France is in Europe"),
            _nli((1, False, "not entailed"), (0, True, "entailed")),
            _claims("Paris is the capital"),
            _nli((0, True, "covered")),
        )
    )
    draft = FactualCorrectnessEvaluator(
        AnswerArtifactMaterializer(store),
        judge=judge,
        prompt=_content("factual_correctness_prompt"),
        rubric=_content("factual_correctness_rubric"),
        clock=lambda: NOW,
    ).evaluate(_input(store), _context())

    assert _measurements(draft) == {
        "factual_correctness": 0.6667,
        "factual_correctness_tp": 1.0,
        "factual_correctness_fp": 1.0,
        "factual_correctness_fn": 0.0,
    }
    assert len(draft.judge_calls) == 4
    assert len(draft.findings) == 3
    assert [item.evidence[0].description for item in draft.findings] == [
        "Paris is the capital",
        "France is in Europe",
        "Paris is the capital",
    ]
    assert "Apply the factual_correctness_prompt instructions" in judge.requests[1].messages[0].content


def test_answer_faithfulness_keeps_every_claim_verdict(tmp_path: Path) -> None:
    """test_answer_faithfulness_keeps_every_claim_verdict."""
    store = _store()
    judge = ScriptedJudge(
        (
            _claims("Paris is the capital", "France is in Europe"),
            _nli((1, False, "unsupported"), (0, True, "supported")),
        )
    )
    draft = FaithfulnessEvaluator(
        AnswerArtifactMaterializer(store),
        judge=judge,
        prompt=_content("faithfulness_prompt"),
        rubric=_content("faithfulness_rubric"),
        clock=lambda: NOW,
    ).evaluate(_input(store), _context())

    assert _measurements(draft) == {"faithfulness": 0.5}
    assert len(draft.judge_calls) == 2
    assert [item.code for item in draft.findings] == [
        "answer_faithfulness.supported",
        "answer_faithfulness.unsupported",
    ]
    assert [item.evidence[0].description for item in draft.findings] == [
        "Paris is the capital",
        "France is in Europe",
    ]


def test_noise_sensitivity_attributes_wrong_claim_to_relevant_context(tmp_path: Path) -> None:
    """test_noise_sensitivity_attributes_wrong_claim_to_relevant_context."""
    store = _store()
    judge = ScriptedJudge(
        (
            _claims("Paris is the capital"),
            _claims("Paris is the capital", "France is in Europe"),
            _nli((0, True, "reference supported by context 0")),
            _nli((0, True, "supported"), (1, True, "noise also supports this")),
            _nli((0, False, "reference absent from context 1")),
            _nli((0, False, "absent"), (1, True, "supported")),
            _nli((1, False, "incorrect"), (0, True, "correct")),
        )
    )
    draft = NoiseSensitivityEvaluator(
        AnswerArtifactMaterializer(store),
        judge=judge,
        prompt=_content("noise_sensitivity_prompt"),
        rubric=_content("noise_sensitivity_rubric"),
        clock=lambda: NOW,
    ).evaluate(
        _input(store, contexts=("Paris and Europe context", "Europe-only context")),
        _context(),
    )

    assert _measurements(draft) == {"noise_sensitivity": 0.5}
    assert draft.measurements[0].direction.value == "lower_is_better"
    assert len(draft.judge_calls) == 7
    assert draft.findings[1].code == "noise_sensitivity.caused_error"
    assert [item.evidence[0].description for item in draft.findings] == [
        "Paris is the capital",
        "France is in Europe",
    ]


def test_correctness_claim_evidence_uses_match_indices_and_retains_missing_claims() -> None:
    store = _store()
    judge = ScriptedJudge(
        (
            _claims("Alice lives in Paris", "Bob lives in Rome"),
            _claims("Bob is based in Rome", "Alice is based in Paris", "Carol lives in Lyon"),
            CorrectnessOutput(
                matches=(
                    CorrectnessMatch(candidate_index=1, reference_index=0, reason="same fact"),
                    CorrectnessMatch(candidate_index=0, reference_index=1, reason="same fact"),
                ),
                false_positives=(),
                false_negatives=(UnmatchedClaim(statement_index=2, reason="missing fact"),),
            ),
        )
    )
    draft = AnswerCorrectnessEvaluator(
        AnswerArtifactMaterializer(store),
        judge=judge,
        prompt=_content("correctness_prompt"),
        rubric=_content("correctness_rubric"),
        clock=lambda: NOW,
    ).evaluate(
        _input(
            store,
            candidate="Alice lives in Paris. Bob lives in Rome.",
            references=("Bob is based in Rome. Alice is based in Paris. Carol lives in Lyon.",),
        ),
        _context(),
    )

    assert draft.status is EvaluationRecordStatus.COMPLETED
    assert [[link.description for link in item.evidence] for item in draft.findings] == [
        ["Bob lives in Rome", "Bob is based in Rome"],
        ["Alice lives in Paris", "Alice is based in Paris"],
        ["Carol lives in Lyon"],
    ]


@pytest.mark.parametrize("claim_length", (2_000, 2_001, 10_000))
def test_claim_evidence_keeps_valid_results_and_marks_truncated_previews(claim_length) -> None:
    store = _store()
    claim = "Fact: " + "x" * (claim_length - 6)
    judge = ScriptedJudge((_claims(claim), _nli((0, True, "supported"))))
    draft = FaithfulnessEvaluator(
        AnswerArtifactMaterializer(store),
        judge=judge,
        prompt=_content("faithfulness_prompt"),
        rubric=_content("faithfulness_rubric"),
        clock=lambda: NOW,
    ).evaluate(_input(store, candidate=claim), _context())

    assert draft.status is EvaluationRecordStatus.COMPLETED
    description = draft.findings[0].evidence[0].description
    assert isinstance(description, str)
    if claim_length <= 2_000:
        assert description == claim
    else:
        assert len(description) <= 2_000
        assert description.startswith(claim[:100])
        assert description.endswith("… [truncated]")


def test_default_task_prompt_flag_changes_evaluator_identity() -> None:
    """A prompt-selection switch that changes the request must change the digest."""
    store = _store()
    common = {
        "judge": ScriptedJudge(()),
        "prompt": _content("correctness_prompt"),
        "rubric": _content("correctness_rubric"),
        "clock": lambda: NOW,
    }
    injected = AnswerCorrectnessEvaluator(AnswerArtifactMaterializer(store), use_default_task_prompts=False, **common)
    defaulted = AnswerCorrectnessEvaluator(AnswerArtifactMaterializer(store), use_default_task_prompts=True, **common)

    assert injected.descriptor.implementation_digest != defaulted.descriptor.implementation_digest
