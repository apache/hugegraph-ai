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

"""Semantic graph matching preserves global indices and complete coverage."""

import pytest
from fakes import NOW, ScriptedJudge
from pydantic import ValidationError
from support import extraction_input as _extraction_input
from support import make_store as _store
from test_graph_evaluators import _content, _context

from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationRecordStatus
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.semantic import (
    SemanticEntityEvaluator,
    SemanticTripleEvaluator,
    SemanticVerdict,
    SemanticVerdictOutput,
)
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.semantic_scoring import (
    MatchPair,
    global_optimal_matches,
)
from hugegraph_llm_eval.integrations.graph_extraction.materializers import GraphArtifactMaterializer
from hugegraph_llm_eval.prompt import semantic_verdict_prompt

pytest.importorskip("networkx", reason="install hugegraph-llm-eval[graph] to run semantic matching contracts")


def _graphs() -> tuple[dict[str, object], dict[str, object]]:
    """_graphs."""
    candidate = {
        "vertices": [
            {"label": "Person", "name": "Alice"},
            {"label": "Skill", "name": "graph traversal"},
            {"label": "Skill", "name": "graph traversal duplicate"},
        ],
        "edges": [
            {
                "label": "HAS_SKILL",
                "outVLabel": "Person",
                "outV": "Alice",
                "inVLabel": "Skill",
                "inV": "graph traversal",
            }
        ],
    }
    reference = {
        "vertices": [
            {"label": "Person", "name": "Alice"},
            {"label": "Skill", "name": "graph traversal"},
        ],
        "edges": [
            {
                "label": "HAS_SKILL",
                "outVLabel": "Person",
                "outV": "Alice",
                "inVLabel": "Skill",
                "inV": "graph traversal",
            }
        ],
    }
    return candidate, reference


def _verdicts(*items: tuple[int, int | None, str]) -> SemanticVerdictOutput:
    """Build one required verdict per reference item."""
    return SemanticVerdictOutput(
        verdicts=tuple(
            SemanticVerdict(
                reference_index=reference,
                candidate_index=candidate,
                match_score=100.0 if candidate is not None else None,
                match_issues=() if candidate is not None else ("no_semantic_match",),
                reason=reason,
            )
            for reference, candidate, reason in items
        )
    )


@pytest.mark.parametrize("language", ["zh", "en"])
def test_semantic_verdict_prompt_uses_one_protocol_and_preserves_alternatives(language) -> None:
    """Current examples and rules must agree before sending a model request."""
    entity = semantic_verdict_prompt("entity", language)
    triple = semantic_verdict_prompt("triple", language)

    for prompt in (entity, triple):
        assert '"matches"' not in prompt
        assert '"verdicts"' in prompt
        assert '"match_score"' in prompt
        assert '"reference_index": 0, "candidate_index": 12' in prompt
        assert '"reference_index": 0, "candidate_index": 13' in prompt
        assert '"reference_index": 1, "candidate_index": 12' in prompt
        assert "no_semantic_match" in prompt
    assert "auth service" in entity
    assert "label_mismatch" in entity
    assert "property_mismatch" in entity
    assert "DEPENDS_ON" in triple
    assert "relation_mismatch" in triple
    assert "endpoint_label_mismatch" in triple
    assert "direction_mismatch" in triple
    if language == "zh":
        assert "所有语义等价候选" in entity
        assert "不要在窗口内做一对一分配" in entity
        assert "反向边不得命中" in triple
    else:
        assert "ALL semantically valid candidate pairs" in entity
        assert "do not assign one-to-one within a window" in entity
        assert "direction must agree" in triple


def test_semantic_entity_matching_preserves_global_indices(tmp_path) -> None:
    """test_semantic_entity_matching_preserves_global_indices."""
    candidate, reference = _graphs()
    store = _store()
    judge = ScriptedJudge((_verdicts((0, 0, "same entity"), (1, 1, "synonym")),))
    evaluator = SemanticEntityEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=_content("semantic_entity_prompt", "Match semantically equivalent entities."),
        rubric=_content("semantic_entity_rubric", "Labels and meaning must agree."),
        clock=lambda: NOW,
    )

    draft = evaluator.evaluate(
        _extraction_input(store, candidate_payload=candidate, reference_payload=reference),
        _context(),
    )

    assert draft.status is EvaluationRecordStatus.COMPLETED
    assert {item.name: item.value for item in draft.measurements} == {
        "semantic_entity_precision": 2 / 3,
        "semantic_entity_recall": 1.0,
        "semantic_entity_f1": 0.8,
    }
    assert [call.call_key for call in draft.judge_calls] == ["candidate_batch_0"]
    prompts = tuple(request.messages[-1].content for request in judge.requests)
    assert '"candidate_index":2' in prompts[0]
    assert '"reference_index":1' in prompts[0]


def test_semantic_match_issues_become_machine_readable_findings(tmp_path) -> None:
    """Accepted semantic issues remain available after global matching."""
    candidate, reference = _graphs()
    store = _store()
    judge = ScriptedJudge(
        (
            SemanticVerdictOutput(
                verdicts=(
                    SemanticVerdict(
                        reference_index=0,
                        candidate_index=0,
                        match_score=88,
                        match_issues=("label_mismatch", "property_mismatch"),
                        reason="名称语义匹配，但类型和属性存在差异。",
                    ),
                    SemanticVerdict(
                        reference_index=1,
                        candidate_index=1,
                        match_score=100,
                        match_issues=(),
                        reason="类型和名称匹配。",
                    ),
                )
            ),
        )
    )
    evaluator = SemanticEntityEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=_content("semantic_entity_prompt", "Match semantically equivalent entities."),
        rubric=_content("semantic_entity_rubric", "Labels and meaning must agree."),
        clock=lambda: NOW,
    )

    draft = evaluator.evaluate(
        _extraction_input(store, candidate_payload=candidate, reference_payload=reference),
        _context(),
    )

    assert {item.code for item in draft.findings} >= {
        "semantic_entity.match_issue.label_mismatch",
        "semantic_entity.match_issue.property_mismatch",
    }


def test_semantic_triple_matching_keeps_direction_and_global_index(tmp_path) -> None:
    """test_semantic_triple_matching_keeps_direction_and_global_index."""
    candidate, reference = _graphs()
    store = _store()
    judge = ScriptedJudge(
        (
            SemanticVerdictOutput(
                verdicts=(
                    SemanticVerdict(
                        reference_index=0,
                        candidate_index=0,
                        match_score=92,
                        match_issues=("relation_mismatch", "endpoint_label_mismatch", "property_mismatch"),
                        reason="关系类型是同义表达；端点名称和方向一致；端点类型和属性存在差异，但不影响关系匹配。",
                    ),
                )
            ),
        )
    )
    evaluator = SemanticTripleEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=_content("semantic_triple_prompt", "Match semantically equivalent directed triples."),
        rubric=_content("semantic_triple_rubric", "Direction and relation meaning must agree."),
        clock=lambda: NOW,
    )

    draft = evaluator.evaluate(
        _extraction_input(store, candidate_payload=candidate, reference_payload=reference),
        _context(),
    )

    assert draft.status is EvaluationRecordStatus.COMPLETED
    assert {item.name: item.value for item in draft.measurements} == {
        "semantic_triple_precision": 1.0,
        "semantic_triple_recall": 1.0,
        "semantic_triple_f1": 1.0,
    }
    assert draft.findings[0].evidence[0].locator == "edges[0]"
    assert {item.code for item in draft.findings} >= {
        "semantic_triple.match_issue.relation_mismatch",
        "semantic_triple.match_issue.endpoint_label_mismatch",
        "semantic_triple.match_issue.property_mismatch",
    }
    request_payload = judge.requests[0].messages[-1].content
    assert '"out_v_label":"Person"' in request_payload
    assert '"in_v_label":"Skill"' in request_payload


def test_semantic_verdict_coverage_is_required(tmp_path) -> None:
    """Missing a reference verdict must not silently lower recall."""
    candidate, reference = _graphs()
    store = _store()
    judge = ScriptedJudge((_verdicts((0, 0, "same entity")),))
    evaluator = SemanticEntityEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=_content("semantic_entity_prompt", "Match semantically equivalent entities."),
        rubric=_content("semantic_entity_rubric", "Labels and meaning must agree."),
        clock=lambda: NOW,
    )

    draft = evaluator.evaluate(
        _extraction_input(store, candidate_payload=candidate, reference_payload=reference),
        _context(),
    )

    assert draft.status is EvaluationRecordStatus.FAILED
    assert draft.measurements == ()
    assert draft.failure is not None
    assert draft.failure.code == "incomplete_semantic_verdicts"
    assert len(draft.judge_calls) == 1


def test_semantic_verdict_match_score_is_required_only_for_positive_matches() -> None:
    """The typed output must carry a weight for every positive match."""
    with pytest.raises(ValidationError):
        SemanticVerdict(reference_index=0, candidate_index=1, reason="matched")
    with pytest.raises(ValidationError):
        SemanticVerdict(
            reference_index=0,
            candidate_index=None,
            match_score=80,
            match_issues=("no_semantic_match",),
            reason="not matched",
        )
    with pytest.raises(ValidationError):
        SemanticVerdict(
            reference_index=0,
            candidate_index=None,
            match_issues=(),
            reason="not matched",
        )
    with pytest.raises(ValidationError):
        SemanticVerdict(
            reference_index=0,
            candidate_index=1,
            match_score=80,
            match_issues=("name_mismatch",),
            reason="matched",
        )
    with pytest.raises(ValidationError):
        SemanticVerdict(
            reference_index=0,
            candidate_index=1,
            match_score=80,
            match_issues=("endpoint_mismatch",),
            reason="matched",
        )
    with pytest.raises(ValidationError):
        SemanticVerdict(
            reference_index=0,
            candidate_index=1,
            match_score=80,
            match_issues=("direction_mismatch",),
            reason="matched",
        )
    assert SemanticVerdict(
        reference_index=0,
        candidate_index=1,
        match_score=88,
        match_issues=("relation_mismatch", "endpoint_label_mismatch", "property_mismatch"),
        reason="端点名称匹配，但端点类型和属性存在差异",
    ).match_issues == ("relation_mismatch", "endpoint_label_mismatch", "property_mismatch")


def test_global_optimal_matching_beats_greedy_order() -> None:
    """The maximum-weight assignment can reject the first locally attractive edge."""
    accepted = global_optimal_matches(
        [
            MatchPair(0, 0, "locally highest", 100),
            MatchPair(0, 1, "global alternative", 99),
            MatchPair(1, 0, "global alternative", 98),
        ]
    )

    assert {(pair.candidate_index, pair.reference_index) for pair in accepted} == {(0, 1), (1, 0)}
    assert sum(pair.match_score for pair in accepted) == 197


def test_semantic_materialization_failure_reports_the_extraction_contract(tmp_path) -> None:
    """Missing offline evidence must not be reported as the retired comparison contract."""
    candidate, reference = _graphs()
    store = _store()
    evaluator = SemanticEntityEvaluator(
        GraphArtifactMaterializer(store),
        judge=ScriptedJudge(()),
        prompt=_content("semantic_entity_prompt", "Match semantically equivalent entities."),
        rubric=_content("semantic_entity_rubric", "Labels and meaning must agree."),
        clock=lambda: NOW,
    )
    complete = _extraction_input(store, candidate_payload=candidate, reference_payload=reference)
    incomplete = complete.model_copy(
        update={"subjects": tuple(item for item in complete.subjects if item.port.value != "source_text")}
    )

    draft = evaluator.evaluate(incomplete, _context())

    assert draft.status is EvaluationRecordStatus.FAILED
    assert draft.failure is not None
    assert draft.failure.code == "graph_extraction_materialization_failed"


def test_semantic_candidate_batches_keep_every_reference(tmp_path) -> None:
    """Candidate batching keeps the complete reference graph in every request."""
    candidate = {
        "vertices": [{"label": "Skill", "name": f"candidate {index}"} for index in range(257)],
        "edges": [],
    }
    reference = {
        "vertices": [{"label": "Skill", "name": f"gold {index}"} for index in range(17)],
        "edges": [],
    }
    judge = ScriptedJudge(
        (
            _verdicts(*((index, None, "not supported") for index in range(17))),
            _verdicts(*((index, None, "not supported") for index in range(17))),
        )
    )
    store = _store()
    evaluator = SemanticEntityEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=_content("semantic_entity_prompt", "Match semantically equivalent entities."),
        rubric=_content("semantic_entity_rubric", "Labels and meaning must agree."),
        clock=lambda: NOW,
    )

    draft = evaluator.evaluate(
        _extraction_input(store, candidate_payload=candidate, reference_payload=reference),
        _context(),
    )

    assert draft.status is EvaluationRecordStatus.COMPLETED
    assert [call.call_key for call in draft.judge_calls] == ["candidate_batch_0", "candidate_batch_1"]
    requests = tuple(request.messages[-1].content for request in judge.requests)
    assert all('"reference_index":0' in request and '"reference_index":16' in request for request in requests)
    assert '"candidate_index":0' in requests[0]
    assert '"candidate_index":255' in requests[0]
    assert '"candidate_index":256' not in requests[0]
    assert '"candidate_index":256' in requests[1]
    assert '"candidate_index":0' not in requests[1]


def test_semantic_match_uses_global_candidate_indices_across_batches(tmp_path) -> None:
    """Candidate batches preserve global indices while repeating the full reference graph."""
    candidate = {
        "vertices": [{"label": "Skill", "name": f"candidate {index}"} for index in range(257)],
        "edges": [],
    }
    reference = {"vertices": [{"label": "Skill", "name": "gold"}], "edges": []}
    judge = ScriptedJudge(
        (
            _verdicts((0, None, "not in the first candidate batch")),
            _verdicts((0, 256, "supported by the second candidate batch")),
        )
    )
    store = _store()
    evaluator = SemanticEntityEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=_content("semantic_entity_prompt", "Match semantically equivalent entities."),
        rubric=_content("semantic_entity_rubric", "Labels and meaning must agree."),
        clock=lambda: NOW,
    )

    draft = evaluator.evaluate(
        _extraction_input(store, candidate_payload=candidate, reference_payload=reference),
        _context(),
    )

    assert draft.status is EvaluationRecordStatus.COMPLETED
    assert {item.name: item.value for item in draft.measurements}["semantic_entity_recall"] == 1.0
    assert [call.call_key for call in draft.judge_calls] == ["candidate_batch_0", "candidate_batch_1"]
    first_request = judge.requests[0].messages[-1].content
    second_request = judge.requests[1].messages[-1].content
    assert '"candidate_index":0' in first_request
    assert '"candidate_index":256' not in first_request
    assert '"candidate_index":256' in second_request


def test_empty_candidate_skips_the_paid_judge_call() -> None:
    """An empty candidate window makes the score deterministic; no judge is needed."""
    _, reference = _graphs()
    store = _store()
    judge = ScriptedJudge(())
    evaluator = SemanticEntityEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=_content("semantic_entity_prompt", "Match semantically equivalent entities."),
        rubric=_content("semantic_entity_rubric", "Labels and meaning must agree."),
        clock=lambda: NOW,
    )

    draft = evaluator.evaluate(
        _extraction_input(
            store,
            candidate_payload={"vertices": [], "edges": []},
            reference_payload=reference,
        ),
        _context(),
    )

    assert draft.status is EvaluationRecordStatus.COMPLETED
    assert judge.requests == []
    assert {item.name: item.value for item in draft.measurements} == {
        "semantic_entity_precision": 0.0,
        "semantic_entity_recall": 0.0,
        "semantic_entity_f1": 0.0,
    }
