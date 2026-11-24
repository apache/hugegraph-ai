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

"""Score retrieval, answers and graphs with every metric the SDK ships.

    uv add --editable /absolute/path/hugegraph-ai/graphrag/eval --extra graph --extra rouge
    python examples/all_metrics.py

Without ``EVAL_JUDGE_MODEL`` the judged metrics use a deterministic stand-in.
Point them at a real model to see real scores:

    export EVAL_JUDGE_MODEL=<model>
    export EVAL_JUDGE_API_KEY=<key>
    # export EVAL_JUDGE_BASE_URL=<gateway>
    # export EVAL_JUDGE_PROVIDER=<provider>
"""

import os

from _stand_in_judge import StandInJudge

from hugegraph_llm_eval import (
    AnswerCorrectnessEvaluator,
    AnswerFaithfulnessEvaluator,
    ContextEntityRecallEvaluator,
    ContextPrecisionEvaluator,
    ContextRelevancyEvaluator,
    EvaluationInput,
    EvaluationOptions,
    EvaluationResult,
    EvidenceRecallEvaluator,
    FactualCorrectnessEvaluator,
    GraphFaithfulnessEvaluator,
    HitAtKEvaluator,
    InMemoryArtifactStore,
    JudgeContent,
    MRREvaluator,
    NoiseSensitivityEvaluator,
    RecallAtKEvaluator,
    RougeLEvaluator,
    SchemaValidityEvaluator,
    SemanticEntityEvaluator,
    SemanticTripleEvaluator,
    answer_input,
    evaluate,
    evaluate_many,
    graph_extraction_input,
    graph_review_input,
    openai_judge,
    retrieval_input,
)
from hugegraph_llm_eval.contracts.identity import ComponentRef
from hugegraph_llm_eval.integrations.answer.materializers import AnswerArtifactMaterializer
from hugegraph_llm_eval.integrations.graph_extraction.materializers import GraphArtifactMaterializer
from hugegraph_llm_eval.integrations.retrieval.materializers import RetrievalArtifactMaterializer
from hugegraph_llm_eval.prompt import (
    graph_judge_prompt,
    graph_judge_rubric,
    retrieval_judge_prompt,
    semantic_verdict_prompt,
)
from hugegraph_llm_eval.utils.clock import utc_now

QUESTION = "How often does the auth service rotate tokens?"
ANSWER = "The auth service rotates OAuth tokens every 24 hours."
REFERENCE = "Auth tokens rotate every 24 hours."
CONTEXTS = ("The auth service issues OAuth 2.0 tokens.", "Tokens rotate every 24 hours.")
EVIDENCE = ("Tokens rotate every 24 hours.",)

SCHEMA = {
    "vertexlabels": [
        {"name": "Service", "primary_keys": ["name"]},
        {"name": "Specification", "primary_keys": ["name"]},
    ],
    "edgelabels": [{"name": "HAS_SPEC", "source_label": "Service", "target_label": "Specification"}],
}
CANDIDATE_GRAPH = {
    "vertices": [
        {"label": "Service", "name": "auth", "properties": {"name": "auth"}},
        {"label": "Specification", "name": "24h rotation", "properties": {"name": "24h rotation"}},
    ],
    "edges": [
        {
            "label": "HAS_SPEC",
            "outVLabel": "Service",
            "outV": "auth",
            "inVLabel": "Specification",
            "inV": "24h rotation",
            "properties": {},
        }
    ],
}
REFERENCE_GRAPH = {
    "vertices": [
        {"label": "Service", "name": "auth service", "properties": {"name": "auth service"}},
        {"label": "Specification", "name": "rotate every 24 hours", "properties": {}},
    ],
    "edges": [
        {
            "label": "HAS_SPEC",
            "outVLabel": "Service",
            "outV": "auth service",
            "inVLabel": "Specification",
            "inV": "rotate every 24 hours",
            "properties": {},
        }
    ],
}


def main() -> None:
    judge = _judge()
    store = InMemoryArtifactStore()

    retrieval = _retrieval_input(store)
    _report(
        "retrieval",
        evaluate(
            [
                RecallAtKEvaluator(RetrievalArtifactMaterializer(store), k_values=(1, 2), clock=utc_now),
                HitAtKEvaluator(RetrievalArtifactMaterializer(store), k_values=(1, 2), clock=utc_now),
                MRREvaluator(RetrievalArtifactMaterializer(store), clock=utc_now),
                ContextPrecisionEvaluator(
                    RetrievalArtifactMaterializer(store),
                    judge=judge,
                    prompt=_content("context_precision_prompt", retrieval_judge_prompt("context_precision", "en")),
                    rubric=_content("context_precision_rubric"),
                    clock=utc_now,
                ),
                ContextRelevancyEvaluator(
                    RetrievalArtifactMaterializer(store),
                    judge=judge,
                    prompt=_content("context_relevancy_prompt", retrieval_judge_prompt("context_relevancy", "en")),
                    rubric=_content("context_relevancy_rubric"),
                    clock=utc_now,
                ),
                ContextEntityRecallEvaluator(
                    RetrievalArtifactMaterializer(store),
                    judge=judge,
                    prompt=_content("context_entity_recall_prompt"),
                    rubric=_content("context_entity_recall_rubric"),
                    clock=utc_now,
                ),
                EvidenceRecallEvaluator(
                    RetrievalArtifactMaterializer(store),
                    judge=judge,
                    prompt=_content("evidence_recall_prompt", retrieval_judge_prompt("evidence_recall", "en")),
                    rubric=_content("evidence_recall_rubric"),
                    clock=utc_now,
                ),
            ],
            retrieval,
            options=_options("retrieval"),
        ),
    )

    _report(
        "answers",
        evaluate(
            [
                RougeLEvaluator(AnswerArtifactMaterializer(store), clock=utc_now),
                AnswerCorrectnessEvaluator(
                    AnswerArtifactMaterializer(store),
                    judge=judge,
                    prompt=_content("answer_correctness_prompt"),
                    rubric=_content("answer_correctness_rubric"),
                    clock=utc_now,
                    use_default_task_prompts=True,
                ),
                FactualCorrectnessEvaluator(
                    AnswerArtifactMaterializer(store),
                    judge=judge,
                    prompt=_content("factual_correctness_prompt"),
                    rubric=_content("factual_correctness_rubric"),
                    clock=utc_now,
                    use_default_task_prompts=True,
                ),
                AnswerFaithfulnessEvaluator(
                    AnswerArtifactMaterializer(store),
                    judge=judge,
                    prompt=_content("answer_faithfulness_prompt"),
                    rubric=_content("answer_faithfulness_rubric"),
                    clock=utc_now,
                    use_default_task_prompts=True,
                ),
                NoiseSensitivityEvaluator(
                    AnswerArtifactMaterializer(store),
                    judge=judge,
                    prompt=_content("noise_sensitivity_prompt"),
                    rubric=_content("noise_sensitivity_rubric"),
                    clock=utc_now,
                    use_default_task_prompts=True,
                ),
            ],
            answer_input(
                store,
                question=QUESTION,
                answer=ANSWER,
                references=[REFERENCE],
                contexts=CONTEXTS,
            ),
            options=_options("answers"),
        ),
    )

    _report(
        "graph review",
        evaluate(
            [
                SchemaValidityEvaluator(GraphArtifactMaterializer(store), clock=utc_now),
                GraphFaithfulnessEvaluator(
                    GraphArtifactMaterializer(store),
                    judge=judge,
                    prompt=_content("graph_faithfulness_prompt", graph_judge_prompt("faithfulness", "en")),
                    rubric=_content("graph_faithfulness_rubric", graph_judge_rubric("faithfulness", "en")),
                    clock=utc_now,
                ),
            ],
            graph_review_input(
                store,
                candidate=CANDIDATE_GRAPH,
                source_text=" ".join(CONTEXTS),
                schema=SCHEMA,
            ),
            options=_options("graph-review"),
        ),
    )

    comparison = graph_extraction_input(
        store,
        candidate=CANDIDATE_GRAPH,
        reference=REFERENCE_GRAPH,
        source_text=" ".join(CONTEXTS),
        schema=SCHEMA,
    )
    _report(
        "graph extraction",
        evaluate(
            [
                SemanticEntityEvaluator(
                    GraphArtifactMaterializer(store),
                    judge=judge,
                    prompt=_content("semantic_entity_prompt", semantic_verdict_prompt("entity", "en")),
                    rubric=_content("semantic_entity_rubric"),
                    clock=utc_now,
                ),
                SemanticTripleEvaluator(
                    GraphArtifactMaterializer(store),
                    judge=judge,
                    prompt=_content("semantic_triple_prompt", semantic_verdict_prompt("triple", "en")),
                    rubric=_content("semantic_triple_rubric"),
                    clock=utc_now,
                ),
            ],
            comparison,
            options=_options("graph-comparison"),
        ),
    )

    batch = evaluate_many(
        [MRREvaluator(RetrievalArtifactMaterializer(store), clock=utc_now)],
        [retrieval, _retrieval_input(store, question="Which service issues tokens?")],
        options=EvaluationOptions(request_key="batch", max_samples=2, max_concurrency=2),
    )
    print(f"batch: {len(batch)} samples, statuses={[result.status.value for result in batch]}")


def _judge():
    model = os.environ.get("EVAL_JUDGE_MODEL")
    if not model:
        print("EVAL_JUDGE_MODEL is not set; judged metrics use the deterministic stand-in.\n")
        return StandInJudge()
    return openai_judge(
        model=model,
        api_key=os.environ.get("EVAL_JUDGE_API_KEY"),
        base_url=os.environ.get("EVAL_JUDGE_BASE_URL"),
        provider=os.environ.get("EVAL_JUDGE_PROVIDER", "openai"),
    )


def _options(request_key: str) -> EvaluationOptions:
    return EvaluationOptions(request_key=request_key, max_concurrency=4, max_attempts=2)


def _retrieval_input(store: InMemoryArtifactStore, question: str = QUESTION) -> EvaluationInput:
    return retrieval_input(
        store,
        candidate_doc_ids=["doc-b", "doc-a"],
        reference_doc_ids=["doc-a"],
        question=question,
        candidate_contexts=CONTEXTS,
        reference_evidence=EVIDENCE,
        reference_answer=REFERENCE,
    )


def _content(name: str, text: str = "") -> JudgeContent:
    return JudgeContent(
        component=ComponentRef(namespace="example", name=name, revision="v1"),
        text=text or f"{name} instructions",
    )


def _report(title: str, result: EvaluationResult) -> None:
    print(f"{title}: {result.status.value}")
    for record in result.records:
        measurements = ", ".join(f"{item.name}={item.value}" for item in record.measurements)
        print(f"  {record.invocation_key:<28} {record.status.value:<13} {measurements}")
        if record.failure is not None:
            print(f"    failure {record.failure.code}: {record.failure.message}")
        for finding in record.findings:
            print(f"    {finding.code}: {finding.message}")
    print()


if __name__ == "__main__":
    main()
