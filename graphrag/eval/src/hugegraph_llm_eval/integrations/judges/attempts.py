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

"""Attempt loop shared by Judge adapters: deadline, retries, backoff and provenance."""

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from pydantic import BaseModel

from hugegraph_llm_eval.contracts.domain.judge import (
    JudgeProvenance,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderUsage,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.evaluation.judges.base import (
    JudgeCallError,
    JudgeDescriptor,
    JudgeOptions,
    JudgeRequest,
    JudgeResult,
    OutputT,
)


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    output: BaseModel
    usage: ProviderUsage
    response_id: str | None = None
    response_model: str | None = None


class AttemptFailureError(RuntimeError):
    def __init__(self, failure: FailureDetail, *, usage: ProviderUsage | None = None) -> None:
        super().__init__(failure.message)
        self.failure = failure
        self.usage = usage


def failure(category: FailureCategory, code: str, retryable: bool) -> FailureDetail:
    return FailureDetail(
        category=category,
        code=code,
        message=f"judge provider failure: {code}",
        retryable=retryable,
    )


def _backoff(options: JudgeOptions, attempt_index: int) -> float:
    return min(options.max_backoff_seconds, options.initial_backoff_seconds * (2.0 ** (attempt_index - 1)))


class AttemptLoopJudge(ABC):
    """Runs provider attempts under one JudgeOptions budget and records each of them."""

    descriptor: JudgeDescriptor

    def __init__(
        self,
        *,
        descriptor: JudgeDescriptor,
        clock: Callable[[], datetime],
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.descriptor = descriptor
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep

    @abstractmethod
    def _attempt(self, request: JudgeRequest[OutputT], timeout: float | None) -> AttemptOutcome:
        """Run one provider call; raise on any failure. ``timeout`` is seconds left before the deadline."""

    @abstractmethod
    def _classify(self, error: Exception) -> FailureDetail:
        """Classify a provider or transport exception that is not an AttemptFailureError."""

    def _billed_usage(self, error: Exception) -> ProviderUsage | None:
        """Usage the provider reported for a response that was then rejected."""
        return error.usage if isinstance(error, AttemptFailureError) else None

    def _usage_from_tokens(self, input_tokens: int, output_tokens: int) -> ProviderUsage:
        return ProviderUsage(
            provider=self.descriptor.provider,
            model=self.descriptor.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    def _unreported_usage(self) -> ProviderUsage:
        return ProviderUsage(
            provider=self.descriptor.provider,
            model=self.descriptor.model,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            reported=False,
        )

    def judge(self, request: JudgeRequest[OutputT], options: JudgeOptions) -> JudgeResult[OutputT]:
        attempts: list[ProviderAttempt] = []
        for attempt_index in range(1, options.max_attempts + 1):
            timeout = self._remaining_seconds(options)
            if timeout is not None and timeout <= 0:
                failure_detail = failure(FailureCategory.TIMEOUT, "judge_deadline_exceeded", True)
                attempts.append(self._failed_attempt(attempt_index, 0, failure_detail))
                self._raise(request, attempts, failure_detail)
            started = self._monotonic()
            try:
                outcome = self._attempt(request, timeout)
            except Exception as exc:
                failure_detail = exc.failure if isinstance(exc, AttemptFailureError) else self._classify(exc)
                attempts.append(
                    self._failed_attempt(
                        attempt_index,
                        self._latency_ms(started),
                        failure_detail,
                        usage=self._billed_usage(exc),
                    )
                )
                if not failure_detail.retryable or attempt_index == options.max_attempts:
                    self._raise(request, attempts, failure_detail)
                delay = _backoff(options, attempt_index)
                remaining = self._remaining_seconds(options)
                self._sleep(delay if remaining is None else min(delay, max(0, remaining)))
                continue
            attempts.append(
                ProviderAttempt(
                    attempt_index=attempt_index,
                    provider=self.descriptor.provider,
                    model=self.descriptor.model,
                    status=ProviderAttemptStatus.COMPLETED,
                    latency_ms=self._latency_ms(started),
                    usage=outcome.usage,
                )
            )
            return JudgeResult(
                output=request.response_type.model_validate(outcome.output),
                provenance=self._provenance(request, attempts, outcome.response_id, outcome.response_model),
                usage=outcome.usage,
            )
        raise AssertionError("positive max_attempts guarantees a result or JudgeCallError")

    def _failed_attempt(
        self,
        attempt_index: int,
        latency_ms: int,
        failure: FailureDetail,
        *,
        usage: ProviderUsage | None = None,
    ) -> ProviderAttempt:
        return ProviderAttempt(
            attempt_index=attempt_index,
            provider=self.descriptor.provider,
            model=self.descriptor.model,
            status=ProviderAttemptStatus.FAILED,
            latency_ms=latency_ms,
            usage=usage,
            failure=failure,
        )

    def _provenance(
        self,
        request: JudgeRequest[OutputT],
        attempts: list[ProviderAttempt],
        response_id: str | None,
        response_model: str | None,
    ) -> JudgeProvenance:
        return JudgeProvenance(
            provider=self.descriptor.provider,
            model=self.descriptor.model,
            configuration_digest=self.descriptor.configuration_digest,
            prompt=request.prompt,
            rubric=request.rubric,
            attempts=tuple(attempts),
            response_id=response_id,
            response_model=response_model,
        )

    def _raise(
        self,
        request: JudgeRequest[OutputT],
        attempts: list[ProviderAttempt],
        failure: FailureDetail,
    ) -> NoReturn:
        raise JudgeCallError(failure, self._provenance(request, attempts, None, None))

    def _remaining_seconds(self, options: JudgeOptions) -> float | None:
        if options.deadline is None:
            return None
        return (options.deadline - self._clock()).total_seconds()

    def _latency_ms(self, started: float) -> int:
        return max(0, round((self._monotonic() - started) * 1_000))
