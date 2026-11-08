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

"""Bounded Evaluator invocation, retries, and operational preflight checks."""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationInput,
    EvaluationRecord,
    EvaluationRecordDraft,
    EvaluationRecordStatus,
    EvaluationRun,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.contracts.identity import EvaluationRecordId, EvaluationRunId
from hugegraph_llm_eval.evaluation.limits import RunLimits
from hugegraph_llm_eval.evaluation.options import EvaluationOptions
from hugegraph_llm_eval.evaluation.resolution import ResolvedEvaluator


@dataclass(frozen=True, slots=True)
class EvaluationExecution:
    records: tuple[EvaluationRecord, ...]
    terminal_failure: FailureDetail | None


class EvaluatorExecutor:
    """Runs resolved Evaluators while the engine remains persistence-focused."""

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    def execute(
        self,
        resolved: tuple[ResolvedEvaluator, ...],
        evaluation_input: EvaluationInput,
        run: EvaluationRun,
        options: EvaluationOptions,
        limits: RunLimits,
    ) -> EvaluationExecution:
        drafts: list[EvaluationRecordDraft] = []
        for offset in range(0, len(resolved), options.max_concurrency):
            batch = resolved[offset : offset + options.max_concurrency]
            failure = _preflight(options, limits, self._clock)
            if failure is not None:
                return self._finish(drafts, resolved[offset:], run.run_id, failure)
            outcomes = self._execute_batch(batch, evaluation_input, run, options, limits)
            drafts.extend(outcomes)
            failure = _preflight(options, limits, self._clock)
            if failure is not None:
                remaining = resolved[offset + len(batch) :]
                return self._finish(drafts, remaining, run.run_id, failure)
        return self._finish(drafts, (), run.run_id, None)

    def _execute_batch(
        self,
        batch: Sequence[ResolvedEvaluator],
        evaluation_input: EvaluationInput,
        run: EvaluationRun,
        options: EvaluationOptions,
        limits: RunLimits,
    ) -> tuple[EvaluationRecordDraft, ...]:
        context = EvaluationContext(
            run_id=run.run_id,
            request_key=run.request_key,
            deadline=options.deadline,
            cancellation=options.cancellation,
            max_concurrency=options.max_concurrency,
            max_attempts=options.max_attempts,
            retry_backoff_seconds=options.retry_backoff_seconds,
            limiter=limits.limiter,
        )
        if len(batch) == 1:
            return (self._invoke(batch[0], evaluation_input, context, options, limits),)
        with ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix="hugegraph-llm-eval-metric") as executor:
            futures = [
                executor.submit(self._invoke, item, evaluation_input, context, options, limits) for item in batch
            ]
            return tuple(future.result() for future in futures)

    def _invoke(
        self,
        resolved: ResolvedEvaluator,
        evaluation_input: EvaluationInput,
        context: EvaluationContext,
        options: EvaluationOptions,
        limits: RunLimits,
    ) -> EvaluationRecordDraft:
        for attempt in range(1, options.max_attempts + 1):
            failure = _preflight(options, limits, self._clock)
            if failure is not None:
                return _unavailable_draft(resolved, failure, self._clock, attempts=attempt - 1)
            draft = self._invoke_once(resolved, evaluation_input, context, attempt)
            limits.budget.charge(draft.judge_calls)
            if not _should_retry(draft, attempt, options.max_attempts):
                return draft.model_copy(update={"attempts": max(draft.attempts, attempt)})
            failure = _preflight(options, limits, self._clock)
            if failure is not None:
                return _unavailable_draft(resolved, failure, self._clock, attempts=attempt)
            if options.cancellation.wait(options.retry_backoff_seconds):
                cancelled = _preflight(options, limits, self._clock)
                assert cancelled is not None
                return _unavailable_draft(resolved, cancelled, self._clock, attempts=attempt)
        raise AssertionError("positive max_attempts guarantees an EvaluationRecordDraft")

    def _invoke_once(
        self,
        resolved: ResolvedEvaluator,
        evaluation_input: EvaluationInput,
        context: EvaluationContext,
        attempt: int,
    ) -> EvaluationRecordDraft:
        try:
            draft = resolved.evaluator.evaluate(evaluation_input, context)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # Evaluator is an external user-code boundary.
            failure = FailureDetail(
                category=FailureCategory.USER_CODE,
                code="evaluator_exception",
                message=f"evaluator raised {type(exc).__name__}",
                retryable=False,
            )
            return _unavailable_draft(resolved, failure, self._clock, attempts=attempt)
        if not isinstance(draft, EvaluationRecordDraft):
            invalid = _failure(
                FailureCategory.USER_CODE,
                "invalid_evaluator_record",
                "evaluator returned a value that is not an evaluation record",
                retryable=False,
            )
            return _unavailable_draft(resolved, invalid, self._clock, attempts=attempt)
        contract_failure = _draft_contract_failure(resolved, draft)
        if contract_failure is None:
            return draft
        return _unavailable_draft(resolved, contract_failure, self._clock, attempts=attempt)

    def _finish(
        self,
        drafts: list[EvaluationRecordDraft],
        remaining: Sequence[ResolvedEvaluator],
        run_id: EvaluationRunId,
        failure: FailureDetail | None,
    ) -> EvaluationExecution:
        if failure is not None:
            drafts.extend(_unavailable_draft(item, failure, self._clock) for item in remaining)
        records = tuple(_record(run_id, draft) for draft in drafts)
        return EvaluationExecution(records=records, terminal_failure=failure)


def _preflight(
    options: EvaluationOptions,
    limits: RunLimits,
    clock: Callable[[], datetime],
) -> FailureDetail | None:
    if options.cancellation.is_cancelled:
        return _failure(
            FailureCategory.CANCELLED,
            "evaluation_cancelled",
            options.cancellation.reason or "evaluation cancelled",
            retryable=False,
        )
    if options.deadline is not None and clock() >= options.deadline:
        return _failure(FailureCategory.TIMEOUT, "evaluation_deadline_exceeded", "evaluation deadline exceeded", True)
    if limits.budget.exhausted():
        return _failure(
            FailureCategory.BUDGET_EXHAUSTED,
            "evaluation_budget_exhausted",
            "evaluation cost budget exhausted",
            retryable=False,
        )
    if limits.budget.unverifiable():
        return _failure(
            FailureCategory.BUDGET_EXHAUSTED,
            "evaluation_budget_unverifiable",
            "evaluation cost budget cannot be verified because provider cost is unknown",
            retryable=False,
        )
    return None


def _failure(
    category: FailureCategory,
    code: str,
    message: str,
    retryable: bool,
) -> FailureDetail:
    return FailureDetail(category=category, code=code, message=message, retryable=retryable)


def _unavailable_draft(
    resolved: ResolvedEvaluator,
    failure: FailureDetail,
    clock: Callable[[], datetime],
    *,
    attempts: int = 0,
) -> EvaluationRecordDraft:
    status = (
        EvaluationRecordStatus.CANCELLED
        if failure.category is FailureCategory.CANCELLED
        else EvaluationRecordStatus.FAILED
    )
    return EvaluationRecordDraft(
        invocation_key=resolved.item.invocation_key,
        evaluator=resolved.item.evaluator,
        status=status,
        reason=failure.message,
        attempts=attempts,
        latency_ms=0,
        failure=failure,
        created_at=clock(),
    )


def _draft_contract_failure(
    resolved: ResolvedEvaluator,
    draft: EvaluationRecordDraft,
) -> FailureDetail | None:
    if draft.invocation_key == resolved.item.invocation_key and draft.evaluator == resolved.item.evaluator:
        return None
    return _failure(
        FailureCategory.USER_CODE,
        "invalid_evaluator_record",
        "evaluator returned a record for a different invocation or identity",
        retryable=False,
    )


def _should_retry(draft: EvaluationRecordDraft, attempt: int, max_attempts: int) -> bool:
    """Retry only failures that have not already spent the judge attempt budget."""
    return (
        draft.status is EvaluationRecordStatus.FAILED
        and draft.failure is not None
        and draft.failure.retryable
        and not draft.judge_calls
        and attempt < max_attempts
    )


def _record(run_id: EvaluationRunId, draft: EvaluationRecordDraft) -> EvaluationRecord:
    return EvaluationRecord(
        record_id=EvaluationRecordId.new(),
        run_id=run_id,
        **draft.model_dump(exclude={"record_id", "run_id"}),
    )
