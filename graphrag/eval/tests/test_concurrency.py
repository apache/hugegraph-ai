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

"""Sample-level and metric-level concurrency stay bounded and interruptible."""

import asyncio
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeEvaluator, evaluation_input

from hugegraph_llm_eval.api import aevaluate, evaluate, evaluate_many
from hugegraph_llm_eval.contracts.digests import ContentDigest
from hugegraph_llm_eval.contracts.domain.evaluation import (
    MAX_CONCURRENCY,
    MAX_SAMPLES,
    EvaluationRecordDraft,
    EvaluationRecordStatus,
)
from hugegraph_llm_eval.contracts.domain.judge import (
    JudgeCallRecord,
    JudgeCallStatus,
    JudgeProvenance,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderUsage,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory
from hugegraph_llm_eval.contracts.identity import ComponentRef
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.limits import CostBudget, RunLimits
from hugegraph_llm_eval.evaluation.options import CancellationToken, EvaluationOptions


class _Probe:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def __enter__(self) -> "_Probe":
        with self.lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
        return self

    def __exit__(self, *_exc: object) -> None:
        with self.lock:
            self.current -= 1


def _draft(name: str) -> EvaluationRecordDraft:
    evaluator = FakeEvaluator(name)
    return EvaluationRecordDraft(
        invocation_key=evaluator.invocation_key,
        evaluator=evaluator.descriptor.evaluator,
        status=EvaluationRecordStatus.COMPLETED,
        reason="scripted outcome",
        attempts=1,
        latency_ms=0,
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )


def _sleeper(probe: _Probe, delay: float) -> FakeEvaluator:
    def outcome(_input, _context):
        with probe:
            time.sleep(delay)
        return _draft("metric")

    return FakeEvaluator("metric", outcome)


def test_samples_run_in_parallel_only_when_max_samples_allows_it() -> None:
    serial_probe = _Probe()
    serial_inputs = [evaluation_input() for _ in range(4)]
    serial_started = time.perf_counter()
    evaluate_many([_sleeper(serial_probe, 0.1)], serial_inputs, options=EvaluationOptions(request_key="serial"))
    serial_elapsed = time.perf_counter() - serial_started

    parallel_probe = _Probe()
    parallel_inputs = [evaluation_input() for _ in range(4)]
    parallel_started = time.perf_counter()
    evaluate_many(
        [_sleeper(parallel_probe, 0.1)],
        parallel_inputs,
        options=EvaluationOptions(request_key="parallel", max_samples=4),
    )
    parallel_elapsed = time.perf_counter() - parallel_started

    assert serial_probe.peak == 1
    assert parallel_probe.peak == 4
    assert parallel_elapsed < serial_elapsed / 2


def test_cancellation_between_metrics_cancels_the_remaining_records() -> None:
    token = CancellationToken()

    def cancelling(_input, _context):
        token.cancel("operator stopped the run")
        return _draft("first")

    result = evaluate(
        [FakeEvaluator("first", cancelling), FakeEvaluator("second")],
        evaluation_input(),
        options=EvaluationOptions(request_key="cancel", cancellation=token),
    )

    assert [record.status for record in result.records] == [
        EvaluationRecordStatus.COMPLETED,
        EvaluationRecordStatus.CANCELLED,
    ]
    assert result.records[1].failure is not None
    assert result.records[1].failure.category is FailureCategory.CANCELLED


def test_deadline_between_metrics_fails_the_remaining_records() -> None:
    def slow(_input, _context):
        time.sleep(0.1)
        return _draft("slow")

    result = evaluate(
        [FakeEvaluator("slow", slow), FakeEvaluator("later")],
        evaluation_input(),
        options=EvaluationOptions(
            request_key="deadline",
            deadline=datetime.now(UTC) + timedelta(milliseconds=50),
        ),
    )

    assert result.records[0].status is EvaluationRecordStatus.COMPLETED
    assert result.records[1].status is EvaluationRecordStatus.FAILED
    assert result.records[1].failure is not None
    assert result.records[1].failure.code == "evaluation_deadline_exceeded"


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_concurrency": 0},
        {"max_concurrency": MAX_CONCURRENCY + 1},
        {"max_samples": 0},
        {"max_samples": MAX_SAMPLES + 1},
    ],
)
def test_concurrency_bounds_fail_at_construction(overrides: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        EvaluationOptions(request_key="bounds", **overrides)


def test_run_limits_cap_the_product_of_both_knobs() -> None:
    options = EvaluationOptions(request_key="limits", max_samples=2, max_concurrency=4)

    assert RunLimits.for_options(options, samples=4).limiter.capacity == 8
    assert RunLimits.for_options(options).limiter.capacity == 4


def _judge_call(cost_usd: float | None) -> JudgeCallRecord:
    usage = ProviderUsage(
        provider="test",
        model="judge",
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        cost_usd=cost_usd,
    )
    content = JudgeContent(component=ComponentRef(namespace="test", name="prompt", revision="v1"), text="judge")
    return JudgeCallRecord(
        call_index=1,
        call_key="call",
        status=JudgeCallStatus.COMPLETED,
        provenance=JudgeProvenance(
            provider="test",
            model="judge",
            configuration_digest=ContentDigest(value="sha256:" + "a" * 64),
            prompt=content.reference,
            rubric=content.reference,
            attempts=(
                ProviderAttempt(
                    attempt_index=1,
                    provider="test",
                    model="judge",
                    status=ProviderAttemptStatus.COMPLETED,
                    latency_ms=0,
                    usage=usage,
                ),
            ),
        ),
        usage=usage,
    )


def test_cost_budget_accumulates_across_samples() -> None:
    budget = CostBudget(1.0)

    budget.charge([_judge_call(0.6)])
    assert not budget.exhausted()
    assert not budget.exceeded()

    budget.charge([_judge_call(0.6)])
    assert budget.exhausted()
    assert budget.exceeded()


def test_cost_budget_reports_unpriced_spend_as_unverifiable() -> None:
    budget = CostBudget(1.0)

    budget.charge([_judge_call(None)])

    assert budget.unverifiable()
    assert not budget.exceeded()


def test_aevaluate_cancellation_reaches_the_run_token() -> None:
    token = CancellationToken()
    options = EvaluationOptions(request_key="async-cancel", cancellation=token)

    async def run() -> None:
        task = asyncio.create_task(aevaluate([_sleeper(_Probe(), 0.3)], evaluation_input(), options=options))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert token.is_cancelled
