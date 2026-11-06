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

import json

import pytest
from fakes import NOW, ScriptedJudge

from hugegraph_llm_eval import (
    ContextEntityRecallEvaluator,
    GraphFaithfulnessEvaluator,
    InMemoryArtifactStore,
    JudgeContent,
    SchemaValidityEvaluator,
    evaluate,
    graph_review_input,
    retrieval_input,
)
from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationRecordStatus
from hugegraph_llm_eval.contracts.identity import ComponentRef
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.faithfulness_output import (
    FaithfulnessIssueGroup,
    FaithfulnessJudgeOutput,
)
from hugegraph_llm_eval.integrations.graph_extraction.materializers import GraphArtifactMaterializer
from hugegraph_llm_eval.integrations.retrieval.evaluators.coverage import (
    ContextEntityRecallOutput,
    ContextEntityVerdict,
)
from hugegraph_llm_eval.integrations.retrieval.materializers import RetrievalArtifactMaterializer

SCHEMA = {"vertexlabels": [{"name": "Person", "primary_keys": ["name"]}], "edgelabels": []}
CONTENT = JudgeContent(
    component=ComponentRef(namespace="test", name="business_boundary", revision="v1"),
    text="Evaluate every supplied item, preserving its index.",
)


def graph_sample(store, count=1):
    return graph_review_input(
        store,
        candidate={
            "vertices": [
                {"label": "Person", "name": f"person-{index}", "properties": {"name": f"person-{index}"}}
                for index in range(count)
            ]
        },
        source_text="A synthetic source document.",
        schema=SCHEMA,
    )


def graph_evaluator(store, judge):
    return GraphFaithfulnessEvaluator(
        GraphArtifactMaterializer(store), judge=judge, prompt=CONTENT, rubric=CONTENT, clock=lambda: NOW
    )


@pytest.mark.parametrize("length", (2_000, 2_001, 20_000))
def test_valid_long_graph_evidence_preserves_the_record_and_usage(length):
    store = InMemoryArtifactStore()
    quote = "x" * length
    judge = ScriptedJudge(
        (
            FaithfulnessJudgeOutput(
                unsupported_vertex_groups=(
                    FaithfulnessIssueGroup(
                        item_indices=(0,),
                        error_categories=("unsupported_claim",),
                        error_reason="Unsupported synthetic claim.",
                        evidence_quote=quote,
                    ),
                ),
            ),
        )
    )
    record = evaluate([graph_evaluator(store, judge)], graph_sample(store)).records[0]
    assert record.status is EvaluationRecordStatus.COMPLETED
    assert len(record.judge_calls) == 1
    assert record.judge_calls[0].usage.cost_usd == pytest.approx(0.001)
    description = record.findings[0].evidence[0].description
    assert len(description) <= 2_000
    assert description == quote if length <= 2_000 else description.endswith("… [truncated]")


def test_long_entity_and_reason_are_valid_individually_and_together():
    store = InMemoryArtifactStore()
    judge = ScriptedJudge(
        (
            ContextEntityRecallOutput(
                has_reference_entities=True,
                verdicts=(ContextEntityVerdict(entity_index=0, entity="e" * 4_000, covered=False, reason="r" * 4_000),),
            ),
        )
    )
    evaluator = ContextEntityRecallEvaluator(
        RetrievalArtifactMaterializer(store), judge=judge, prompt=CONTENT, rubric=CONTENT, clock=lambda: NOW
    )
    sample = retrieval_input(
        store, candidate_doc_ids=(), reference_doc_ids=(), question="Which entity?", reference_answer="e" * 4_000
    )
    record = evaluate([evaluator], sample).records[0]
    assert record.status is EvaluationRecordStatus.COMPLETED
    assert len(record.judge_calls) == 1
    assert len(record.findings[0].message) <= 4_000
    assert record.findings[0].evidence[0].description


def test_duplicate_primary_keys_are_reported_without_rejecting_the_input():
    store = InMemoryArtifactStore()
    sample = graph_review_input(
        store,
        candidate={
            "vertices": [
                {"label": "Person", "name": "Alice", "properties": {"name": "Alice"}},
                {"label": "Person", "name": "Alice-copy", "properties": {"name": "Alice"}},
            ]
        },
        source_text="Alice is one person.",
        schema=SCHEMA,
    )
    evaluator = SchemaValidityEvaluator(GraphArtifactMaterializer(store), clock=lambda: NOW)
    record = evaluate([evaluator], sample).records[0]
    assert record.status is EvaluationRecordStatus.COMPLETED
    scores = {item.name: item.value for item in record.measurements}
    assert scores["schema_validity"] == 0
    assert any(item.code == "schema.duplicate_primary_key" for item in record.findings)


class CapacityJudge(ScriptedJudge):
    def judge(self, request, options):
        payload = json.loads(request.messages[-1].content)
        assert len(payload["items"]) <= 256, "synthetic provider item limit exceeded"
        self._outputs.append(
            FaithfulnessJudgeOutput(
                supported_vertex_indices=tuple(
                    item["item_index"] for item in payload["items"] if item["item_kind"] == "vertex"
                ),
                supported_edge_indices=tuple(
                    item["item_index"] for item in payload["items"] if item["item_kind"] == "edge"
                ),
            )
        )
        return super().judge(request, options)


def test_graph_faithfulness_batches_large_graphs_and_keeps_global_indices():
    store = InMemoryArtifactStore()
    judge = CapacityJudge(())
    record = evaluate([graph_evaluator(store, judge)], graph_sample(store, 600)).records[0]
    assert record.status is EvaluationRecordStatus.COMPLETED
    assert {item.name: item.value for item in record.measurements}["faithfulness"] == 1
    assert len(record.judge_calls) >= 3
    assert {item.evidence[0].locator for item in record.findings} == {f"vertices[{i}]" for i in range(600)}
