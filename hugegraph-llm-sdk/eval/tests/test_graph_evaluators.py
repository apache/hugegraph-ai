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

"""Structured production graph Evaluators over candidate-only evidence."""

from dataclasses import dataclass

import pytest
from fakes import NOW
from pydantic import ValidationError
from support import graph_input as _input
from support import make_store as _store

from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationRecordStatus,
)
from hugegraph_llm_eval.contracts.domain.judge import (
    JudgeProvenance,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderUsage,
)
from hugegraph_llm_eval.contracts.identity import ComponentRef, EvaluationRunId, SchemaRef
from hugegraph_llm_eval.evaluation.judges.base import (
    JudgeDescriptor,
    JudgeOptions,
    JudgeRequest,
    JudgeResult,
)
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.options import CancellationToken
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.faithfulness import (
    FaithfulnessEvaluator,
    FaithfulnessIssueGroup,
    FaithfulnessItemKind,
    FaithfulnessJudgeOutput,
    FaithfulnessVerdict,
)
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.faithfulness_output import (
    FaithfulnessErrorCategory,
)
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.schema_validity import (
    SchemaValidityEvaluator,
)
from hugegraph_llm_eval.integrations.graph_extraction.materializers import (
    GraphArtifactMaterializer,
)


def _content(name: str, text: str) -> JudgeContent:
    """_content."""
    return JudgeContent(
        component=ComponentRef(namespace="graph", name=name, revision="v1"),
        text=text,
    )


def _context() -> EvaluationContext:
    """_context."""
    return EvaluationContext(
        run_id=EvaluationRunId.new(),
        request_key="review:chunk-1",
        deadline=None,
        cancellation=CancellationToken(),
    )


@dataclass
class StaticJudge:
    """StaticJudge."""

    output: FaithfulnessJudgeOutput

    def __post_init__(self) -> None:
        """__post_init__."""
        self.descriptor = JudgeDescriptor.create(
            provider="test",
            model="judge",
            configuration={"temperature": 0},
        )
        self.requests: list[JudgeRequest[FaithfulnessJudgeOutput]] = []

    def judge(
        self,
        request: JudgeRequest[FaithfulnessJudgeOutput],
        options: JudgeOptions,
    ) -> JudgeResult[FaithfulnessJudgeOutput]:
        """judge."""
        self.requests.append(request)
        usage = ProviderUsage(
            provider="test",
            model="judge",
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            cost_usd=0.001,
        )
        provenance = JudgeProvenance(
            provider="test",
            model="judge",
            configuration_digest=self.descriptor.configuration_digest,
            prompt=request.prompt,
            rubric=request.rubric,
            attempts=(
                ProviderAttempt(
                    attempt_index=1,
                    provider="test",
                    model="judge",
                    status=ProviderAttemptStatus.COMPLETED,
                    latency_ms=12,
                    usage=usage,
                ),
            ),
            response_id="response-1",
            response_model="judge",
        )
        return JudgeResult(output=self.output, provenance=provenance, usage=usage)


def _verdicts() -> tuple[FaithfulnessVerdict, ...]:
    """_verdicts."""
    return (
        FaithfulnessVerdict(
            item_kind=FaithfulnessItemKind.VERTEX,
            item_index=0,
            faithful=True,
            support_reason="Car A appears in the source.",
        ),
        FaithfulnessVerdict(
            item_kind=FaithfulnessItemKind.VERTEX,
            item_index=1,
            faithful=True,
            support_reason="GraphQL appears in the source.",
        ),
        FaithfulnessVerdict(
            item_kind=FaithfulnessItemKind.EDGE,
            item_index=0,
            faithful=False,
            error_categories=(FaithfulnessErrorCategory.UNSUPPORTED_CLAIM,),
            support_reason="The relation type and endpoints appear in the source.",
            error_reason="The precise relation is not explicit.",
        ),
    )


def test_schema_validity_emits_measurements_and_item_level_violations(tmp_path) -> None:
    """test_schema_validity_emits_measurements_and_item_level_violations."""
    store = _store()
    evaluator = SchemaValidityEvaluator(GraphArtifactMaterializer(store), clock=lambda: NOW)

    draft = evaluator.evaluate(_input(store), _context())

    assert draft.status is EvaluationRecordStatus.COMPLETED
    assert {item.name: item.value for item in draft.measurements} == {
        "schema_validity": 1.0,
        "type_constraint_pass": 1.0,
        "required_property_fill": 1.0,
        "illegal_edge_rate": 0.0,
    }
    assert draft.findings == ()


@pytest.mark.parametrize("evaluator_type", (FaithfulnessEvaluator, SchemaValidityEvaluator))
def test_graph_quality_evaluators_reject_unsupported_input_schema(tmp_path, evaluator_type) -> None:
    """Descriptor input schemas must be executable, rather than silently falling back to review."""
    store = _store()
    unsupported = SchemaRef(namespace="graph", name="unsupported", version=1)
    common = {"clock": lambda: NOW, "input_schema": unsupported}
    if evaluator_type is FaithfulnessEvaluator:
        common.update(
            judge=StaticJudge(FaithfulnessJudgeOutput.from_verdicts(_verdicts())),
            prompt=_content("faithfulness_prompt", "Judge each item."),
            rubric=_content("faithfulness_rubric", "Require explicit source support."),
        )

    with pytest.raises(ValueError, match=r"candidate_review.*extraction"):
        evaluator_type(GraphArtifactMaterializer(store), **common)


def test_schema_validity_preserves_every_violation_and_denominator(tmp_path) -> None:
    """test_schema_validity_preserves_every_violation_and_denominator."""
    store = _store()
    candidate = {
        "vertices": [
            {"label": "Unknown", "name": "mystery"},
            {"label": "Person", "name": "Alice", "properties": {}},
        ],
        "edges": [
            {
                "label": "HAS_SKILL",
                "outV": "mystery",
                "outVLabel": "Unknown",
                "inV": "Alice",
                "inVLabel": "Person",
            }
        ],
    }
    evaluator = SchemaValidityEvaluator(GraphArtifactMaterializer(store), clock=lambda: NOW)

    draft = evaluator.evaluate(_input(store, candidate_payload=candidate), _context())

    assert {item.name: item.value for item in draft.measurements} == {
        "schema_validity": 0.0,
        "type_constraint_pass": 0.5,
        "required_property_fill": 0.0,
        "illegal_edge_rate": 1.0,
    }
    assert [item.code for item in draft.findings] == [
        "schema.unknown_vertex_label",
        "schema.missing_required_property",
        "schema.illegal_edge",
    ]
    assert [item.evidence[0].locator for item in draft.findings] == [
        "vertices[0]",
        "vertices[1]",
        "edges[0]",
    ]


def test_faithfulness_preserves_every_item_verdict_and_complete_prompt(tmp_path) -> None:
    """test_faithfulness_preserves_every_item_verdict_and_complete_prompt."""
    store = _store()
    judge_output = FaithfulnessJudgeOutput.from_verdicts(_verdicts())
    judge = StaticJudge(judge_output)
    prompt = _content("faithfulness_prompt", "Judge each item.")
    rubric = _content("faithfulness_rubric", "Require explicit source support.")
    evaluator = FaithfulnessEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=prompt,
        rubric=rubric,
        clock=lambda: NOW,
    )

    draft = evaluator.evaluate(_input(store), _context())

    assert draft.status is EvaluationRecordStatus.COMPLETED
    assert {item.name: item.value for item in draft.measurements} == {
        "faithfulness": 2 / 3,
        "faithfulness_vertex": 1.0,
        "faithfulness_edge": 0.0,
    }
    assert len(draft.findings) == 5
    assert draft.findings[-1].code == "faithfulness.unsupported"
    assert draft.findings[-2].code == "faithfulness.issue.unsupported_claim"
    assert draft.findings[-3].code == "faithfulness.supported_part"
    assert judge_output.model_dump(mode="json") == {
        "supported_vertex_indices": [0, 1],
        "supported_edge_indices": [],
        "unsupported_vertex_groups": [],
        "unsupported_edge_groups": [
            {
                "item_indices": [0],
                "error_categories": ["unsupported_claim"],
                "support_reason": "The relation type and endpoints appear in the source.",
                "error_reason": "The precise relation is not explicit.",
                "evidence_quote": None,
            }
        ],
    }
    message = judge.requests[0].messages[-1].content
    assert '"item_index":0' in message
    assert '"item_kind":"edge"' in message
    assert '"out_v_label":"Person"' in message
    assert '"in_v_label":"Skill"' in message
    assert "HAS_SKILL" in message
    system_message = judge.requests[0].messages[0].content
    assert "Judge each item." in system_message
    assert "Require explicit source support." in system_message
    assert judge.requests[0].prompt == prompt.reference
    assert judge.requests[0].rubric == rubric.reference


def test_faithfulness_empty_candidate_is_not_applicable(tmp_path) -> None:
    """An empty graph has no claims, so its faithfulness ratio is undefined."""
    store = _store()
    judge = StaticJudge(FaithfulnessJudgeOutput.from_verdicts(_verdicts()))
    evaluator = FaithfulnessEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=_content("faithfulness_prompt", "Judge each item."),
        rubric=_content("faithfulness_rubric", "Require explicit source support."),
        clock=lambda: NOW,
    )

    draft = evaluator.evaluate(_input(store, candidate_payload={"vertices": [], "edges": []}), _context())

    assert draft.status is EvaluationRecordStatus.NOT_APPLICABLE
    assert draft.measurements == ()
    assert draft.attempts == 0
    assert draft.judge_calls == ()
    assert draft.findings[0].code == "faithfulness.empty_candidate"
    assert len(judge.requests) == 0


def test_faithfulness_missing_verdict_is_failure_not_zero_score(tmp_path) -> None:
    """test_faithfulness_missing_verdict_is_failure_not_zero_score."""
    store = _store()
    judge = StaticJudge(FaithfulnessJudgeOutput.from_verdicts(_verdicts()[:-1]))
    evaluator = FaithfulnessEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=_content("faithfulness_prompt", "Judge each item."),
        rubric=_content("faithfulness_rubric", "Require explicit source support."),
        clock=lambda: NOW,
    )

    draft = evaluator.evaluate(_input(store), _context())

    assert draft.status is EvaluationRecordStatus.FAILED
    assert draft.measurements == ()
    assert draft.failure is not None
    assert draft.failure.code == "incomplete_faithfulness_verdicts"
    assert len(draft.judge_calls) == 1
    assert draft.judge_calls[0].call_key == "evaluate_items"


def test_faithfulness_judge_output_is_compact_and_still_partitions_every_item() -> None:
    """test_faithfulness_judge_output_is_compact_and_still_partitions_every_item."""
    output = FaithfulnessJudgeOutput(
        supported_vertex_indices=tuple(range(123)),
        supported_edge_indices=tuple(range(120)),
    )

    assert len(output.verdicts()) == 243
    assert len(output.model_dump_json()) < 2_000
    with pytest.raises(ValidationError, match="must not overlap"):
        FaithfulnessJudgeOutput(
            supported_vertex_indices=(0,),
            unsupported_vertex_groups=(
                FaithfulnessIssueGroup(
                    item_indices=(0,),
                    error_categories=(FaithfulnessErrorCategory.UNSUPPORTED_CLAIM,),
                    support_reason=None,
                    error_reason="unsupported",
                ),
            ),
        )


def test_faithfulness_requires_error_categories_for_unsupported_items() -> None:
    """Unsupported claims must be classifiable for downstream attribution."""
    with pytest.raises(ValidationError, match="error categories"):
        FaithfulnessVerdict(
            item_kind=FaithfulnessItemKind.VERTEX,
            item_index=0,
            faithful=False,
            support_reason=None,
            error_reason="The value is not supported.",
        )
