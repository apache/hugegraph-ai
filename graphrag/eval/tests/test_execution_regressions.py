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

"""Run limits hold across samples and mixed graph evaluators."""

import json
import threading

import pytest
from fakes import NOW, FakeEvaluator, evaluation_input
from support import extraction_input, make_store
from test_concurrency import _judge_call

from hugegraph_llm_eval.api import evaluate, evaluate_many
from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationRecordStatus
from hugegraph_llm_eval.contracts.identity import ComponentRef
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.options import EvaluationOptions
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.faithfulness import (
    FaithfulnessEvaluator,
    FaithfulnessJudgeOutput,
)
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.semantic import SemanticEntityEvaluator
from hugegraph_llm_eval.integrations.graph_extraction.materializers import (
    GRAPH_EXTRACTION_INPUT_SCHEMA,
    GraphArtifactMaterializer,
)


def test_unpriced_sample_stops_subsequent_budgeted_samples() -> None:
    evaluator = FakeEvaluator("unpriced_metric")

    def unpriced(value, context):
        return evaluator._completed(value, context).model_copy(update={"judge_calls": (_judge_call(None),)})

    evaluator._outcome = unpriced
    results = evaluate_many(
        [evaluator],
        [evaluation_input() for _ in range(3)],
        options=EvaluationOptions(request_key="unpriced-batch", budget_usd=0.01),
    )

    assert evaluator.calls == 1
    assert [result.records[0].status for result in results] == [
        EvaluationRecordStatus.COMPLETED,
        EvaluationRecordStatus.FAILED,
        EvaluationRecordStatus.FAILED,
    ]
    assert all(result.records[0].failure.code == "evaluation_budget_unverifiable" for result in results[1:])


def test_mixed_graph_metrics_share_the_provider_limit() -> None:
    pytest.importorskip("networkx")
    from test_semantic_concurrency import _CountingJudge, _result, _verdicts

    class MixedJudge(_CountingJudge):
        def __init__(self) -> None:
            super().__init__()
            self.all_started = threading.Event()

        def judge(self, request, options):
            del options
            with self.lock:
                self.calls += 1
                self.current += 1
                self.peak = max(self.peak, self.current)
                if self.current == 3:
                    self.all_started.set()
            try:
                # A broken limiter admits all three calls; a working one admits only two.
                self.all_started.wait(0.5)
                output = (
                    FaithfulnessJudgeOutput(
                        supported_vertex_indices=tuple(
                            item["item_index"] for item in json.loads(request.messages[-1].content)["items"]
                        )
                    )
                    if request.response_type is FaithfulnessJudgeOutput
                    else _verdicts(1)
                )
                return _result(request, output)
            finally:
                with self.lock:
                    self.current -= 1

    store = make_store()
    judge = MixedJudge()
    content = JudgeContent(component=ComponentRef(namespace="test", name="prompt", revision="v1"), text="judge")
    common = {"judge": judge, "prompt": content, "rubric": content, "clock": lambda: NOW}
    materializer = GraphArtifactMaterializer(store)
    candidate = {"vertices": [{"label": "Person", "name": f"p-{index}"} for index in range(300)], "edges": []}
    reference = {"vertices": [{"label": "Person", "name": "p-0"}, {"label": "Person", "name": "p-1"}], "edges": []}

    result = evaluate(
        [
            SemanticEntityEvaluator(materializer, **common),
            FaithfulnessEvaluator(materializer, input_schema=GRAPH_EXTRACTION_INPUT_SCHEMA, **common),
        ],
        extraction_input(store, candidate_payload=candidate, reference_payload=reference),
        options=EvaluationOptions(request_key="mixed-graph", max_concurrency=2),
    )

    assert result.succeeded
    assert judge.calls == 4
    assert judge.peak <= 2
