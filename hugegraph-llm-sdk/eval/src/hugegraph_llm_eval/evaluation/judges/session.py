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

"""Ordered Judge calls made during one Evaluator invocation."""

from collections.abc import Callable
from datetime import datetime
from typing import NoReturn

from hugegraph_llm_eval.contracts.domain.evaluation import CancellationProbe, ConcurrencyLimiter
from hugegraph_llm_eval.contracts.domain.judge import (
    JudgeCallRecord,
    JudgeCallStatus,
    JudgeProvenance,
    ProviderAttempt,
    ProviderAttemptStatus,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.evaluation.judges.base import (
    Judge,
    JudgeCallError,
    JudgeOptions,
    JudgeRequest,
    OutputT,
)
from hugegraph_llm_eval.utils.clock import utc_now


class JudgeSession:
    def __init__(
        self,
        judge: Judge,
        options: JudgeOptions,
        *,
        cancellation: CancellationProbe | None = None,
        limiter: ConcurrencyLimiter | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._judge = judge
        self._options = options
        self._cancellation = cancellation
        self._limiter = limiter
        self._clock = clock
        self._calls: list[JudgeCallRecord] = []

    @property
    def options(self) -> JudgeOptions:
        return self._options

    @property
    def calls(self) -> tuple[JudgeCallRecord, ...]:
        return tuple(self._calls)

    @property
    def latency_ms(self) -> int:
        return sum(attempt.latency_ms for call in self._calls for attempt in call.provenance.attempts)

    def call(self, call_key: str, request: JudgeRequest[OutputT]) -> OutputT:
        if any(call.call_key == call_key for call in self._calls):
            raise ValueError(f"judge call key already used: {call_key}")
        call_index = len(self._calls) + 1
        if self._limiter is None:
            return self._invoke(call_index, call_key, request)
        failure = self._limiter.acquire(self._abort_failure)
        if failure is not None:
            self._abort(call_index, call_key, request, failure)
        try:
            return self._invoke(call_index, call_key, request)
        finally:
            self._limiter.release()

    def _invoke(self, call_index: int, call_key: str, request: JudgeRequest[OutputT]) -> OutputT:
        failure = self._abort_failure()
        if failure is not None:
            self._abort(call_index, call_key, request, failure)
        try:
            result = self._judge.judge(request, self._options)
        except JudgeCallError as exc:
            self._calls.append(
                JudgeCallRecord(
                    call_index=call_index,
                    call_key=call_key,
                    status=JudgeCallStatus.FAILED,
                    provenance=exc.provenance,
                    failure=exc.failure,
                )
            )
            raise
        self._calls.append(
            JudgeCallRecord(
                call_index=call_index,
                call_key=call_key,
                status=JudgeCallStatus.COMPLETED,
                provenance=result.provenance,
                usage=result.usage,
            )
        )
        return result.output

    def _abort(
        self,
        call_index: int,
        call_key: str,
        request: JudgeRequest[OutputT],
        failure: FailureDetail,
    ) -> NoReturn:
        provenance = self._aborted_provenance(request, failure)
        self._calls.append(
            JudgeCallRecord(
                call_index=call_index,
                call_key=call_key,
                status=JudgeCallStatus.FAILED,
                provenance=provenance,
                failure=failure,
            )
        )
        raise JudgeCallError(failure, provenance)

    def _aborted_provenance(self, request: JudgeRequest[OutputT], failure: FailureDetail) -> JudgeProvenance:
        descriptor = self._judge.descriptor
        return JudgeProvenance(
            provider=descriptor.provider,
            model=descriptor.model,
            configuration_digest=descriptor.configuration_digest,
            prompt=request.prompt,
            rubric=request.rubric,
            attempts=(
                ProviderAttempt(
                    attempt_index=1,
                    provider=descriptor.provider,
                    model=descriptor.model,
                    status=ProviderAttemptStatus.FAILED,
                    latency_ms=0,
                    failure=failure,
                ),
            ),
        )

    def _abort_failure(self) -> FailureDetail | None:
        if self._cancellation is not None and self._cancellation.is_cancelled:
            return FailureDetail(
                category=FailureCategory.CANCELLED,
                code="evaluation_cancelled",
                message=self._cancellation.reason or "evaluation cancelled",
                retryable=False,
            )
        if self._options.deadline is not None and self._clock() >= self._options.deadline:
            return FailureDetail(
                category=FailureCategory.TIMEOUT,
                code="judge_deadline_exceeded",
                message="judge deadline exceeded",
                retryable=False,
            )
        return None
