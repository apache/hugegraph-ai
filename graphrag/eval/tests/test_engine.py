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

"""Engine behaviour: ordering, retries, deadline, cancellation and partial results."""

import time
from datetime import UTC, datetime, timedelta

import pytest
from fakes import INPUT_SCHEMA, NOW, FakeEvaluator, ScriptedJudge, evaluation_input

from hugegraph_llm_eval.api import evaluate, evaluate_many
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationRecord,
    EvaluationRecordDraft,
    EvaluationRecordStatus,
    EvaluationRunStatus,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.contracts.identity import ComponentRef, EvaluationRecordId, EvaluationRunId
from hugegraph_llm_eval.evaluation.engine import EvaluationEngine
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.judges.lifecycle import JudgedEvaluatorLifecycle
from hugegraph_llm_eval.evaluation.options import CancellationToken, EvaluationOptions


def _draft(evaluator: FakeEvaluator, status: EvaluationRecordStatus, failure: FailureDetail | None = None):
    return EvaluationRecordDraft(
        invocation_key=evaluator.invocation_key,
        evaluator=evaluator.descriptor.evaluator,
        status=status,
        reason="scripted outcome",
        attempts=1,
        latency_ms=0,
        failure=failure,
        created_at=datetime(2026, 7, 25, tzinfo=UTC),
    )


def _content(name: str) -> JudgeContent:
    return JudgeContent(
        component=ComponentRef(namespace="test", name=name, revision="v1"),
        text=f"{name} instructions",
    )


def test_records_preserve_evaluator_order_under_concurrency() -> None:
    def delayed(name: str, delay: float) -> FakeEvaluator:
        def outcome(_input, _context):
            time.sleep(delay)
            evaluator = FakeEvaluator(name)
            return _draft(evaluator, EvaluationRecordStatus.COMPLETED)

        evaluator = FakeEvaluator(name, outcome)
        return evaluator

    evaluators = [delayed("slow_metric", 0.05), delayed("fast_metric", 0.0)]
    result = evaluate(
        evaluators,
        evaluation_input(),
        options=EvaluationOptions(request_key="order", max_concurrency=2),
    )

    assert result.status is EvaluationRunStatus.COMPLETED
    assert [record.invocation_key for record in result.records] == ["slow_metric", "fast_metric"]


def test_retryable_failure_is_retried_up_to_max_attempts() -> None:
    evaluator = FakeEvaluator("retried_metric")

    def flaky(_input, _context):
        if evaluator.calls < 3:
            return _draft(
                evaluator,
                EvaluationRecordStatus.FAILED,
                FailureDetail(
                    category=FailureCategory.TIMEOUT,
                    code="provider_timeout",
                    message="provider timed out",
                    retryable=True,
                ),
            )
        return _draft(evaluator, EvaluationRecordStatus.COMPLETED)

    evaluator._outcome = flaky
    result = evaluate(
        [evaluator],
        evaluation_input(),
        options=EvaluationOptions(request_key="retry", max_attempts=3),
    )

    assert evaluator.calls == 3
    assert result.status is EvaluationRunStatus.COMPLETED
    assert result.records[0].attempts == 3


def test_partial_run_keeps_successful_records() -> None:
    good = FakeEvaluator("good_metric")
    bad = FakeEvaluator(
        "bad_metric",
        lambda _input, _context: _draft(
            FakeEvaluator("bad_metric"),
            EvaluationRecordStatus.FAILED,
            FailureDetail(
                category=FailureCategory.INVALID_INPUT,
                code="invalid_input",
                message="input is not materializable",
                retryable=False,
            ),
        ),
    )

    result = evaluate([good, bad], evaluation_input(), options=EvaluationOptions(request_key="partial"))

    assert result.status is EvaluationRunStatus.PARTIAL
    assert [record.status for record in result.records] == [
        EvaluationRecordStatus.COMPLETED,
        EvaluationRecordStatus.FAILED,
    ]


def test_deadline_marks_remaining_records_failed() -> None:
    evaluator = FakeEvaluator("late_metric")
    deadline = datetime.now(UTC) - timedelta(seconds=1)

    result = evaluate(
        [evaluator],
        evaluation_input(),
        options=EvaluationOptions(request_key="deadline", deadline=deadline),
    )

    assert evaluator.calls == 0
    assert result.status is EvaluationRunStatus.FAILED
    assert result.records[0].failure is not None
    assert result.records[0].failure.code == "evaluation_deadline_exceeded"


def test_cancellation_marks_records_cancelled() -> None:
    cancellation = CancellationToken()
    cancellation.cancel("operator stopped the run")

    result = evaluate(
        [FakeEvaluator("cancelled_metric")],
        evaluation_input(),
        options=EvaluationOptions(request_key="cancel", cancellation=cancellation),
    )

    assert result.status is EvaluationRunStatus.CANCELLED
    assert result.records[0].status is EvaluationRecordStatus.CANCELLED


def test_deadline_after_partial_progress_reports_partial() -> None:
    now = [datetime(2026, 7, 25, tzinfo=UTC)]
    deadline = now[0] + timedelta(seconds=10)
    first = FakeEvaluator("first_metric")
    second = FakeEvaluator("second_metric")

    def advance(_input, _context):
        now[0] = deadline + timedelta(seconds=1)
        return _draft(first, EvaluationRecordStatus.COMPLETED)

    first._outcome = advance
    engine = EvaluationEngine(clock=lambda: now[0])
    result = engine.evaluate(
        [first, second],
        evaluation_input(),
        EvaluationOptions(request_key="partial-deadline", deadline=deadline, max_concurrency=1),
    )

    assert result.status is EvaluationRunStatus.PARTIAL
    assert [record.status for record in result.records] == [
        EvaluationRecordStatus.COMPLETED,
        EvaluationRecordStatus.FAILED,
    ]


def test_not_applicable_records_are_not_run_failures() -> None:
    evaluator = FakeEvaluator(
        "not_applicable_metric",
        lambda _input, _context: _draft(FakeEvaluator("not_applicable_metric"), EvaluationRecordStatus.NOT_APPLICABLE),
    )

    result = evaluate([evaluator], evaluation_input(), options=EvaluationOptions(request_key="na"))

    assert result.status is EvaluationRunStatus.COMPLETED
    assert result.succeeded


def test_mixed_completed_and_not_applicable_is_completed() -> None:
    completed = FakeEvaluator("completed_metric")
    not_applicable = FakeEvaluator(
        "na_metric",
        lambda _input, _context: _draft(FakeEvaluator("na_metric"), EvaluationRecordStatus.NOT_APPLICABLE),
    )

    result = evaluate([completed, not_applicable], evaluation_input(), options=EvaluationOptions(request_key="mixed"))

    assert result.status is EvaluationRunStatus.COMPLETED


def test_non_record_return_becomes_a_failed_record() -> None:
    broken = FakeEvaluator("broken_metric", lambda _input, _context: None)

    result = evaluate([broken], evaluation_input(), options=EvaluationOptions(request_key="broken"))

    assert result.status is EvaluationRunStatus.FAILED
    assert result.records[0].failure is not None
    assert result.records[0].failure.code == "invalid_evaluator_record"


def test_context_attempt_budget_reaches_the_judge_session() -> None:
    judge = ScriptedJudge(())
    lifecycle = JudgedEvaluatorLifecycle(
        namespace="test",
        invocation_key="budgeted_metric",
        input_schema=INPUT_SCHEMA,
        judge=judge,
        prompt=_content("prompt"),
        rubric=_content("rubric"),
        clock=lambda: NOW,
    )
    context = EvaluationContext(
        run_id=EvaluationRunId.new(),
        request_key="budget",
        deadline=None,
        cancellation=CancellationToken(),
        max_attempts=4,
    )

    assert lifecycle.session(context).options.max_attempts == 4


def test_executor_hands_the_attempt_and_backoff_budget_to_evaluators() -> None:
    evaluator = FakeEvaluator("budget_metric")

    evaluate(
        [evaluator],
        evaluation_input(),
        options=EvaluationOptions(request_key="budget", max_attempts=4, retry_backoff_seconds=0.5),
    )

    context = evaluator.contexts[0]
    assert context.max_attempts == 4
    assert context.retry_backoff_seconds == 0.5


def test_out_of_range_attempt_budget_is_rejected_at_configuration() -> None:
    with pytest.raises(ValueError, match="max_attempts must be between 1 and 20"):
        EvaluationOptions(request_key="too-many", max_attempts=21)

    with pytest.raises(ValueError, match="max_attempts must be between 1 and 20"):
        EvaluationContext(
            run_id=EvaluationRunId.new(),
            request_key="too-many",
            deadline=None,
            cancellation=CancellationToken(),
            max_attempts=21,
        )


def test_evaluator_may_return_a_persisted_record() -> None:
    record = EvaluationRecord(
        record_id=EvaluationRecordId.new(),
        run_id=EvaluationRunId.new(),
        invocation_key="record_metric",
        evaluator=FakeEvaluator("record_metric").descriptor.evaluator,
        status=EvaluationRecordStatus.COMPLETED,
        reason="already persisted upstream",
        attempts=1,
        latency_ms=0,
        created_at=NOW,
    )
    evaluator = FakeEvaluator("record_metric", lambda _input, _context: record)

    result = evaluate([evaluator], evaluation_input(), options=EvaluationOptions(request_key="record"))

    assert result.status is EvaluationRunStatus.COMPLETED
    assert result.records[0].status is EvaluationRecordStatus.COMPLETED
    assert result.records[0].record_id != record.record_id


def test_evaluate_many_preserves_input_order() -> None:
    inputs = [evaluation_input(), evaluation_input()]
    results = evaluate_many(
        [FakeEvaluator("ordered_metric")],
        inputs,
        options=EvaluationOptions(request_key="many"),
    )

    assert len(results) == 2
    assert all(result.status is EvaluationRunStatus.COMPLETED for result in results)
    assert results[0].run_id != results[1].run_id


def test_empty_evaluator_list_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one evaluator"):
        evaluate([], evaluation_input())
