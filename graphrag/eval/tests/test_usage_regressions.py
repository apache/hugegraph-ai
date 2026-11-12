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

"""Reported provider usage survives output failures and is charged once per attempt."""

import pytest

pytest.importorskip("openai", reason="install hugegraph-llm-eval[openai] to run provider contracts")

from openai import LengthFinishReasonError
from test_judge import FakeCompletions, _judge, _request, _response

from hugegraph_llm_eval.evaluation.judges.base import JudgeCallError, JudgeOptions
from hugegraph_llm_eval.evaluation.judges.session import JudgeSession
from hugegraph_llm_eval.evaluation.limits import CostBudget


@pytest.mark.parametrize("failure_kind", ["length", "length_exception", "invalid_output", "refusal"])
def test_failed_response_usage_survives_and_is_charged(failure_kind: str) -> None:
    response = _response()
    if failure_kind in {"length", "length_exception"}:
        response.choices[0].finish_reason = "length"
    elif failure_kind == "invalid_output":
        response.choices[0].message.parsed = None
    else:
        response.choices[0].message.refusal = "refused"
    first = LengthFinishReasonError(completion=response) if failure_kind == "length_exception" else response
    session = JudgeSession(_judge(FakeCompletions(first, _response())), JudgeOptions(max_attempts=2))

    if failure_kind == "refusal":
        with pytest.raises(JudgeCallError):
            session.call("score", _request())
        expected_attempts = 1
    else:
        session.call("score", _request())
        expected_attempts = 2

    call = session.calls[0]
    assert len(call.provenance.attempts) == expected_attempts
    assert call.provenance.attempts[0].usage is not None
    assert call.provenance.attempts[0].usage.total_tokens == 120
    budget = CostBudget(0.01)
    budget.charge(session.calls)
    assert budget.spent == pytest.approx(expected_attempts * 0.00036)
    assert not budget.unverifiable()
    if call.usage is not None:
        # The call-level field remains the final response, not the aggregate of retries.
        assert call.usage.cost_usd == pytest.approx(0.00036)


def test_exhausted_invalid_responses_preserve_every_billed_attempt() -> None:
    first, second = _response(), _response()
    first.choices[0].finish_reason = second.choices[0].finish_reason = "length"
    session = JudgeSession(_judge(FakeCompletions(first, second)), JudgeOptions(max_attempts=2))

    with pytest.raises(JudgeCallError):
        session.call("score", _request())

    budget = CostBudget(0.0005)
    budget.charge(session.calls)
    assert budget.spent == pytest.approx(0.00072)
    assert budget.exceeded()
    assert not budget.unverifiable()


def test_unknown_attempt_keeps_known_cost_without_claiming_complete_usage() -> None:
    session = JudgeSession(
        _judge(FakeCompletions(TimeoutError("no response"), _response())),
        JudgeOptions(max_attempts=2),
    )
    session.call("score", _request())

    budget = CostBudget(0.01)
    budget.charge(session.calls)
    assert budget.spent == pytest.approx(0.00036)
    assert budget.unverifiable()
