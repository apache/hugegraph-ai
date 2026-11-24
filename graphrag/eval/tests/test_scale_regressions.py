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
from test_business_boundary_regressions import CONTENT, CapacityJudge, graph_sample

from hugegraph_llm_eval import (
    AnswerFaithfulnessEvaluator,
    BatchingOptions,
    ContextEntityRecallEvaluator,
    ContextPrecisionEvaluator,
    ContextRelevancyEvaluator,
    EvaluationOptions,
    GraphFaithfulnessEvaluator,
    InMemoryArtifactStore,
    SchemaValidityEvaluator,
    SemanticEntityEvaluator,
    answer_input,
    evaluate,
    graph_extraction_input,
    graph_review_input,
    retrieval_input,
)
from hugegraph_llm_eval.evaluation.options import CancellationToken
from hugegraph_llm_eval.integrations.answer.materializers import AnswerArtifactMaterializer
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.faithfulness_output import FaithfulnessJudgeOutput
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.semantic import SemanticVerdictOutput
from hugegraph_llm_eval.integrations.graph_extraction.materializers import GraphArtifactMaterializer
from hugegraph_llm_eval.integrations.retrieval.materializers import RetrievalArtifactMaterializer


class IndexedJudge(ScriptedJudge):
    def judge(self, request, options):
        payload = json.loads(request.messages[-1].content)
        name = request.response_type.__name__
        if name == "SemanticVerdictOutput":
            assert len(payload["candidates"]) <= 256
            assert len(payload["references"]) <= 256
            by_name = {item["name"]: item["candidate_index"] for item in payload["candidates"]}
            verdicts = []
            for reference in payload["references"]:
                candidate = by_name.get(reference["name"])
                verdicts.append(
                    {
                        "reference_index": reference["reference_index"],
                        "candidate_index": candidate,
                        "match_score": 100 if candidate is not None else None,
                        "match_issues": [] if candidate is not None else ["no_semantic_match"],
                        "reason": "Synthetic exact-identity oracle.",
                    }
                )
            output = {"verdicts": verdicts}
        else:
            assert len(payload["contexts"]) <= 256
            output = {
                "verdicts": [
                    {
                        "context_index": item["context_index"],
                        "reason": "synthetic",
                        **(
                            {"relevant": item["context_index"] % 2 == 0}
                            if name == "ContextPrecisionOutput"
                            else {"score": item["context_index"] % 3}
                        ),
                    }
                    for item in payload["contexts"]
                ]
            }
        self._outputs.append(request.response_type.model_validate(output))
        return super().judge(request, options)


def test_large_reference_graph_is_windowed_as_well_as_candidates():
    pytest.importorskip("networkx")
    store = InMemoryArtifactStore()
    judge = IndexedJudge(())
    graph = {"vertices": [{"label": "Person", "name": f"p-{index}"} for index in range(300)]}
    sample = graph_extraction_input(store, candidate=graph, reference=graph, source_text="", schema={})
    evaluator = SemanticEntityEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=CONTENT,
        rubric=CONTENT,
        clock=lambda: NOW,
    )
    result = evaluate([evaluator], sample)
    assert result.succeeded
    assert {m.name: m.value for m in result.records[0].measurements}["semantic_entity_recall"] == 1
    assert len(judge.requests) == 4


@pytest.mark.parametrize("evaluator_type", (ContextPrecisionEvaluator, ContextRelevancyEvaluator))
def test_many_contexts_are_aggregated_over_the_original_ranking(evaluator_type):
    store = InMemoryArtifactStore()
    judge = IndexedJudge(())
    sample = retrieval_input(
        store,
        candidate_doc_ids=(),
        reference_doc_ids=(),
        question="Synthetic question",
        candidate_contexts=tuple(f"context-{i}" for i in range(600)),
    )
    evaluator = evaluator_type(
        RetrievalArtifactMaterializer(store),
        judge=judge,
        prompt=CONTENT,
        rubric=CONTENT,
        clock=lambda: NOW,
    )
    record = evaluate([evaluator], sample).records[0]
    assert record.status.value == "completed"
    assert len(judge.requests) == 3
    assert len(record.findings) == 600
    if evaluator_type is ContextPrecisionEvaluator:
        expected = round(sum((i // 2 + 1) / (i + 1) for i in range(0, 600, 2)) / 300, 4)
    else:
        expected = 0.5
    assert record.measurements[0].value == expected


class OmittingEntityJudge(ScriptedJudge):
    def judge(self, request, options):
        if request.response_type.__name__ == "ReferenceEntitiesOutput":
            payload = json.loads(request.messages[-1].content)
            assert "contexts" not in payload
            output = {"entities": ["Alice", "Bob"]}
        else:
            output = {
                "has_reference_entities": True,
                "verdicts": [
                    {"entity_index": 0, "entity": "Alice", "covered": True, "reason": "present"},
                ],
            }
        self._outputs.append(request.response_type.model_validate(output))
        return super().judge(request, options)


def test_omitted_reference_entity_cannot_silently_produce_perfect_recall():
    store = InMemoryArtifactStore()
    judge = OmittingEntityJudge(())
    sample = retrieval_input(
        store,
        candidate_doc_ids=(),
        reference_doc_ids=(),
        question="Who?",
        reference_answer="Alice and Bob",
        candidate_contexts=("Alice",),
    )
    evaluator = ContextEntityRecallEvaluator(
        RetrievalArtifactMaterializer(store),
        judge=judge,
        prompt=CONTENT,
        rubric=CONTENT,
        clock=lambda: NOW,
    )
    record = evaluate([evaluator], sample).records[0]
    assert record.status.value == "failed"
    assert record.failure.code == "incomplete_context_entity_verdicts"
    assert not record.measurements


def make_graph_evaluator(store, judge, **kwargs):
    return GraphFaithfulnessEvaluator(
        GraphArtifactMaterializer(store), judge=judge, prompt=CONTENT, rubric=CONTENT, clock=lambda: NOW, **kwargs
    )


def test_five_thousand_graph_items_keep_vertex_and_edge_namespaces():
    store = InMemoryArtifactStore()
    judge = CapacityJudge(())
    sample = graph_review_input(
        store,
        candidate={
            "vertices": [{"label": "Person", "name": f"p-{i}"} for i in range(2_000)],
            "edges": [
                {"label": "KNOWS", "outV": f"p-{i % 2_000}", "inV": f"p-{(i + 1) % 2_000}"} for i in range(3_000)
            ],
        },
        source_text="Synthetic workload; this tests scheduling, not semantic quality.",
        schema={},
    )
    record = evaluate([make_graph_evaluator(store, judge)], sample).records[0]
    assert record.status.value == "completed"
    assert len(record.judge_calls) == 20
    assert len(record.findings) == 5_000
    assert {finding.evidence[0].locator for finding in record.findings} == (
        {f"vertices[{i}]" for i in range(2_000)} | {f"edges[{i}]" for i in range(3_000)}
    )
    assert sum(call.usage.cost_usd for call in record.judge_calls) == pytest.approx(0.02)


def test_payload_budget_counts_utf8_bytes_and_never_truncates_evidence():
    store = InMemoryArtifactStore()
    judge = CapacityJudge(())
    source = "原文证据。" * 10
    sample = graph_review_input(
        store,
        candidate={"vertices": [{"label": "Person", "name": f"甲乙丙{i}"} for i in range(30)]},
        source_text=source,
        schema={},
    )
    record = evaluate(
        [make_graph_evaluator(store, judge, batching=BatchingOptions(max_payload_bytes=600))], sample
    ).records[0]
    assert record.status.value == "completed"
    assert len(judge.requests) > 1
    for request in judge.requests:
        message = request.messages[-1].content
        assert len(message.encode("utf-8")) <= 600
        assert json.loads(message)["source_text"] == source
    assert len(record.findings) == 30


def test_oversized_shared_source_fails_before_spending_provider_calls():
    store = InMemoryArtifactStore()
    judge = ScriptedJudge(())
    sample = graph_review_input(
        store, candidate={"vertices": [{"label": "Person", "name": "Alice"}]}, source_text="x" * 1_000, schema={}
    )
    record = evaluate(
        [make_graph_evaluator(store, judge, batching=BatchingOptions(max_payload_bytes=500))], sample
    ).records[0]
    assert record.status.value == "failed"
    assert record.failure.code == "evaluation_payload_too_large"
    assert not record.measurements and not record.judge_calls and not judge.requests


def test_later_invalid_batch_preserves_prior_usage_without_partial_full_score():
    store = InMemoryArtifactStore()
    judge = ScriptedJudge((FaithfulnessJudgeOutput(supported_vertex_indices=(0,)), FaithfulnessJudgeOutput()))
    record = evaluate(
        [make_graph_evaluator(store, judge, batching=BatchingOptions(max_items=1))], graph_sample(store, 3)
    ).records[0]
    assert record.status.value == "failed"
    assert record.failure.code == "incomplete_faithfulness_verdicts"
    assert not record.measurements
    assert len(judge.requests) == len(record.judge_calls) == 2
    assert sum(call.usage.cost_usd for call in record.judge_calls) == pytest.approx(0.002)


def test_graph_batches_honor_shared_cancellation():
    cancellation = CancellationToken()

    class CancellingJudge(CapacityJudge):
        def judge(self, request, options):
            result = super().judge(request, options)
            cancellation.cancel("synthetic cancellation")
            return result

    store = InMemoryArtifactStore()
    judge = CancellingJudge(())
    record = evaluate(
        [make_graph_evaluator(store, judge, batching=BatchingOptions(max_items=1))],
        graph_sample(store, 10),
        options=EvaluationOptions(request_key="cancel", cancellation=cancellation),
    ).records[0]
    assert record.status.value == "cancelled"
    assert len(judge.requests) == 1
    assert record.judge_calls[0].usage.cost_usd == pytest.approx(0.001)
    assert not record.measurements


@pytest.mark.parametrize("entities", (("Alice", "Bob"), ()))
def test_supplied_entity_inventory_skips_extraction_and_preserves_denominator(entities):
    store = InMemoryArtifactStore()
    judge = ScriptedJudge(())
    if entities:
        from hugegraph_llm_eval.integrations.retrieval.evaluators.coverage import ContextEntityRecallOutput

        judge._outputs.append(
            ContextEntityRecallOutput.model_validate(
                {
                    "has_reference_entities": True,
                    "verdicts": [
                        {"entity_index": i, "entity": name, "covered": i == 0, "reason": "synthetic"}
                        for i, name in enumerate(entities)
                    ],
                }
            )
        )
    sample = retrieval_input(
        store,
        candidate_doc_ids=(),
        reference_doc_ids=(),
        question="Who?",
        reference_entities=entities,
        candidate_contexts=("Alice",),
    )
    evaluator = ContextEntityRecallEvaluator(
        RetrievalArtifactMaterializer(store),
        judge=judge,
        prompt=CONTENT,
        rubric=CONTENT,
        clock=lambda: NOW,
    )
    record = evaluate([evaluator], sample).records[0]
    if entities:
        assert record.status.value == "completed" and record.measurements[0].value == 0.5
        assert len(judge.requests) == 1
        assert [f.evidence[0].locator for f in record.findings] == ["entities[0]", "entities[1]"]
        assert [f.evidence[0].description for f in record.findings] == list(entities)
    else:
        assert record.status.value == "not_applicable"
        assert not judge.requests and not record.measurements


@pytest.mark.parametrize(
    "second", ({"tenant": "b", "name": "Alice"}, {"tenant": "a", "name": "alice"}, {"tenant": "a", "name": "Alice"})
)
def test_composite_primary_keys_preserve_value_case_and_key_scope(second):
    store = InMemoryArtifactStore()
    schema = {"vertexlabels": [{"name": "Person", "primary_keys": ["tenant", "name"]}]}
    sample = graph_review_input(
        store,
        schema=schema,
        source_text="",
        candidate={
            "vertices": [
                {"label": "Person", "name": "first", "properties": {"tenant": "a", "name": "Alice"}},
                {"label": "Person", "name": "second", "properties": second},
            ]
        },
    )
    evaluator = SchemaValidityEvaluator(GraphArtifactMaterializer(store), clock=lambda: NOW)
    record = evaluate([evaluator], sample).records[0]
    duplicate = second == {"tenant": "a", "name": "Alice"}
    assert record.status.value == "completed"
    assert bool(record.findings) is duplicate
    if duplicate:
        assert {link.locator for link in record.findings[0].evidence} == {"vertices[0]", "vertices[1]"}


@pytest.mark.parametrize("strategy, expected", (("max_weight", 0.5), ("max_cardinality", 1.0)))
def test_matching_strategy_is_explicit_and_defaults_to_maximum_weight(strategy, expected):
    pytest.importorskip("networkx")
    store = InMemoryArtifactStore()
    graph = {"vertices": [{"label": "Person", "name": f"p-{i}"} for i in range(2)]}
    sample = graph_extraction_input(store, candidate=graph, reference=graph, source_text="", schema={})
    output = SemanticVerdictOutput.model_validate(
        {
            "verdicts": [
                {
                    "candidate_index": c,
                    "reference_index": r,
                    "match_score": score,
                    "match_issues": [],
                    "reason": "synthetic",
                }
                for c, r, score in ((0, 0, 100), (0, 1, 49), (1, 0, 49))
            ]
        }
    )
    judge = ScriptedJudge((output,))
    evaluator = SemanticEntityEvaluator(
        GraphArtifactMaterializer(store),
        judge=judge,
        prompt=CONTENT,
        rubric=CONTENT,
        clock=lambda: NOW,
        matching_strategy=strategy,
    )
    record = evaluate([evaluator], sample).records[0]
    assert record.status.value == "completed"
    assert {m.name: m.value for m in record.measurements}["semantic_entity_recall"] == expected
    default = SemanticEntityEvaluator(
        GraphArtifactMaterializer(store), judge=judge, prompt=CONTENT, rubric=CONTENT, clock=lambda: NOW
    )
    assert (default.descriptor.implementation_digest == evaluator.descriptor.implementation_digest) is (
        strategy == "max_weight"
    )


class ClaimsJudge(ScriptedJudge):
    def judge(self, request, options):
        if request.response_type.__name__ == "ClaimDecompositionOutput":
            output = {"claims": [f"claim-{i}" for i in range(600)]}
        else:
            payload = json.loads(request.messages[-1].content)
            assert len(payload["statements"]) <= 256
            output = {
                "verdicts": [
                    {"statement_index": item["statement_index"], "entailed": True, "reason": "synthetic"}
                    for item in payload["statements"]
                ]
            }
        self._outputs.append(request.response_type.model_validate(output))
        return super().judge(request, options)


def test_answer_nli_batches_preserve_all_claims_and_provider_usage():
    store = InMemoryArtifactStore()
    judge = ClaimsJudge(())
    sample = answer_input(
        store,
        question="Q?",
        answer="Synthetic answer",
        references=("Synthetic reference",),
        contexts=("Synthetic evidence",),
    )
    evaluator = AnswerFaithfulnessEvaluator(
        AnswerArtifactMaterializer(store), judge=judge, prompt=CONTENT, rubric=CONTENT, clock=lambda: NOW
    )
    record = evaluate([evaluator], sample).records[0]
    assert record.status.value == "completed"
    assert record.measurements[0].value == 1
    assert len(record.judge_calls) == 4
    assert len(record.findings) == 600
    assert record.findings[-1].evidence[0].description == "claim-599"
