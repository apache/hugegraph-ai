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

"""Semantic pair proposals survive candidate-window boundaries."""

import json

import pytest
from fakes import NOW, ScriptedJudge
from pydantic import ValidationError
from test_graph_evaluators import _content

from hugegraph_llm_eval import InMemoryArtifactStore, evaluate, graph_extraction_input
from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationRecordStatus
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.semantic import (
    SemanticEntityEvaluator,
    SemanticTripleEvaluator,
    SemanticVerdict,
    SemanticVerdictOutput,
)
from hugegraph_llm_eval.integrations.graph_extraction.materializers import GraphArtifactMaterializer
from hugegraph_llm_eval.prompt import semantic_verdict_prompt

pytest.importorskip("networkx", reason="semantic matching requires the graph extra")

PAIR_SCORES = {("flexible", "r0"): 100, ("flexible", "r1"): 99, ("exclusive", "r0"): 98}


def _verdict(reference: int, candidate: int | None, score: float | None = 100) -> SemanticVerdict:
    return SemanticVerdict(
        reference_index=reference,
        candidate_index=candidate,
        match_score=score if candidate is not None else None,
        match_issues=() if candidate is not None else ("no_semantic_match",),
        reason="Deterministic semantic-pair oracle.",
    )


def test_semantic_proposals_allow_alternatives_on_both_sides() -> None:
    output = SemanticVerdictOutput(verdicts=(_verdict(0, 0), _verdict(0, 1), _verdict(1, 0)))
    assert len(output.verdicts) == 3


@pytest.mark.parametrize(
    "items",
    [
        (_verdict(0, 0), _verdict(0, 0)),
        (_verdict(0, None), _verdict(0, None)),
        (_verdict(0, None), _verdict(0, 1)),
        (_verdict(0, 1), _verdict(0, None)),
    ],
)
def test_semantic_proposals_reject_duplicate_or_contradictory_pairs(items) -> None:
    with pytest.raises(ValidationError):
        SemanticVerdictOutput(verdicts=items)


class _PairProposalJudge(ScriptedJudge):
    """Return all accepted pairs; the production solver owns the assignment."""

    def judge(self, request, options):
        payload = json.loads(request.messages[-1].content)
        name_field = "name" if payload["item_kind"] == "entity" else "in_v"
        verdicts = []
        for reference in payload["references"]:
            alternatives = [
                _verdict(reference["reference_index"], candidate["candidate_index"], score)
                for candidate in payload["candidates"]
                if (score := PAIR_SCORES.get((candidate[name_field], reference[name_field]))) is not None
            ]
            verdicts.extend(alternatives or [_verdict(reference["reference_index"], None)])
        self._outputs.append(SemanticVerdictOutput(verdicts=tuple(verdicts)))
        return super().judge(request, options)


def _graph(names, kind):
    if kind == "entity":
        return {"vertices": [{"label": "Entity", "name": name} for name in names]}
    return {"edges": [{"label": "REL", "outV": "source", "inV": name} for name in names]}


@pytest.mark.parametrize("kind", ["entity", "triple"])
def test_semantic_matching_keeps_alternatives_across_real_candidate_windows(kind) -> None:
    distractors = [f"distractor-{index}" for index in range(255)]
    measurements = []
    for names in (["flexible", "exclusive", *distractors], ["flexible", *distractors, "exclusive"]):
        store = InMemoryArtifactStore(clock=lambda: NOW)
        judge = _PairProposalJudge(())
        evaluator_type = SemanticEntityEvaluator if kind == "entity" else SemanticTripleEvaluator
        evaluator = evaluator_type(
            GraphArtifactMaterializer(store),
            judge=judge,
            prompt=_content("pair_proposals", semantic_verdict_prompt(kind)),
            rubric=_content("pair_rubric", "Return every semantically valid pair without a local assignment."),
            clock=lambda: NOW,
        )
        sample = graph_extraction_input(
            store,
            candidate=_graph(names, kind),
            reference=_graph(("r0", "r1"), kind),
            source_text="",
            schema={"vertexlabels": [{"name": "Entity"}], "edgelabels": []},
        )
        record = evaluate([evaluator], sample).records[0]
        assert record.status is EvaluationRecordStatus.COMPLETED
        scores = {item.name: item.value for item in record.measurements}
        assert scores[f"semantic_{kind}_recall"] == 1.0
        assert len(judge.requests) == 2
        accepted = [finding for finding in record.findings if finding.code == f"semantic_{kind}.matched"]
        assert len(accepted) == 2
        assert len({finding.evidence[0].locator for finding in accepted}) == 2
        assert len({finding.evidence[1].locator for finding in accepted}) == 2
        measurements.append(scores)
    assert measurements[0] == measurements[1]
