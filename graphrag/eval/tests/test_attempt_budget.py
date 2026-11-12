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

"""Provider requests stay bounded by ``max_attempts`` and are never retried twice."""

from datetime import UTC, datetime

import pytest

pytest.importorskip("openai", reason="install hugegraph-llm-eval[openai] to run provider contracts")

from test_answer_evaluators import _content, _input, _store
from test_judge import FakeCompletions, _judge

from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationRecordStatus
from hugegraph_llm_eval.evaluation.engine import EvaluationEngine
from hugegraph_llm_eval.evaluation.options import EvaluationOptions
from hugegraph_llm_eval.integrations.answer.evaluators.correctness import (
    AnswerCorrectnessEvaluator,
)
from hugegraph_llm_eval.integrations.answer.materializers import AnswerArtifactMaterializer


def _evaluator(transport: FakeCompletions) -> tuple[AnswerCorrectnessEvaluator, object]:
    store = _store()
    evaluator = AnswerCorrectnessEvaluator(
        AnswerArtifactMaterializer(store),
        judge=_judge(transport),
        prompt=_content("correctness_prompt"),
        rubric=_content("correctness_rubric"),
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
    )
    return evaluator, store


def test_provider_attempts_are_bounded_and_not_multiplied_by_the_engine() -> None:
    transport = FakeCompletions(TimeoutError("first"), TimeoutError("second"), TimeoutError("third"))
    evaluator, store = _evaluator(transport)

    result = EvaluationEngine().evaluate(
        [evaluator],
        _input(store),
        EvaluationOptions(request_key="attempt-budget", max_attempts=2),
    )

    assert result.records[0].status is EvaluationRecordStatus.FAILED
    assert result.records[0].failure is not None
    assert result.records[0].failure.code == "provider_timeout"
    assert len(transport.calls) == 2


def test_a_spent_judge_call_is_not_replayed_by_the_engine() -> None:
    transport = FakeCompletions(TimeoutError("first"), TimeoutError("second"), TimeoutError("third"))
    evaluator, store = _evaluator(transport)

    EvaluationEngine().evaluate(
        [evaluator],
        _input(store),
        EvaluationOptions(request_key="no-replay", max_attempts=1),
    )

    assert len(transport.calls) == 1
