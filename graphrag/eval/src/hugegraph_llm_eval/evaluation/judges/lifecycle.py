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

"""Reusable request and EvaluationRecord lifecycle for judged Evaluators."""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel, JsonValue

from hugegraph_llm_eval.contracts.digests import canonical_digest, canonical_json_bytes
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationInput,
    EvaluationRecordDraft,
    EvaluationRecordStatus,
    EvaluatorDescriptor,
    Finding,
    Measurement,
)
from hugegraph_llm_eval.contracts.domain.judge import JudgeCallRecord
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.contracts.identity import EvaluatorRef, SchemaRef
from hugegraph_llm_eval.evaluation.judges.base import (
    Judge,
    JudgeCallError,
    JudgeMessage,
    JudgeOptions,
    JudgeRequest,
)
from hugegraph_llm_eval.evaluation.judges.batching import BatchingOptions, BatchInputError, BatchOutputError
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.judges.session import JudgeSession

OutputT = TypeVar("OutputT", bound=BaseModel)


class JudgedEvaluatorLifecycle:
    input_type = EvaluationInput

    def __init__(
        self,
        *,
        namespace: str,
        invocation_key: str,
        input_schema: SchemaRef,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
        implementation: Mapping[str, JsonValue] | None = None,
        batching: BatchingOptions | None = None,
    ) -> None:
        self._batching = batching or BatchingOptions()
        self._invocation_key = invocation_key
        self._judge = judge
        self._prompt = prompt
        self._rubric = rubric
        self._clock = clock
        self.descriptor = EvaluatorDescriptor(
            evaluator=EvaluatorRef(namespace=namespace, name=invocation_key, revision="v2"),
            implementation_digest=canonical_digest(
                {
                    "algorithm": invocation_key,
                    "version": 3,
                    "batching": self._batching.model_dump(mode="json"),
                    "judge": judge.descriptor.model_dump(mode="json"),
                    "prompt": prompt.reference.model_dump(mode="json"),
                    "rubric": rubric.reference.model_dump(mode="json"),
                    **(implementation or {}),
                }
            ),
            input_schema=input_schema,
            output_schema=SchemaRef(namespace=namespace, name=f"{invocation_key}_record", version=1),
        )

    def session(self, context: EvaluationContext) -> JudgeSession:
        return JudgeSession(
            self._judge,
            JudgeOptions(
                deadline=context.deadline,
                max_attempts=context.max_attempts,
                initial_backoff_seconds=context.retry_backoff_seconds,
            ),
            cancellation=context.cancellation,
            limiter=context.limiter,
            clock=self._clock,
        )

    @property
    def invocation_key(self) -> str:
        return self._invocation_key

    def request(
        self,
        output_type: type[OutputT],
        payload: JsonValue,
        *,
        prompt: JudgeContent | None = None,
        rubric: JudgeContent | None = None,
    ) -> JudgeRequest[OutputT]:
        encoded = canonical_json_bytes(payload)
        if len(encoded) > self._batching.max_payload_bytes:
            raise BatchInputError(
                f"Judge payload needs {len(encoded)} bytes; configured limit is {self._batching.max_payload_bytes}. "
                "Reduce the input or raise the explicit limit; shared evidence is never truncated."
            )
        selected_prompt = prompt or self._prompt
        selected_rubric = rubric or self._rubric
        return JudgeRequest(
            messages=(
                JudgeMessage(role="system", content=f"{selected_prompt.text}\n\nRubric:\n{selected_rubric.text}"),
                JudgeMessage(role="user", content=encoded.decode()),
            ),
            response_type=output_type,
            prompt=selected_prompt.reference,
            rubric=selected_rubric.reference,
        )

    def completed_record(
        self,
        measurements: tuple[Measurement, ...],
        findings: tuple[Finding, ...],
        reason: str,
        session: JudgeSession,
    ) -> EvaluationRecordDraft:
        return self._record(
            status=EvaluationRecordStatus.COMPLETED,
            reason=reason,
            session=session,
            measurements=measurements,
            findings=findings,
        )

    def not_applicable_record(self, reason: str, session: JudgeSession) -> EvaluationRecordDraft:
        return self._record(status=EvaluationRecordStatus.NOT_APPLICABLE, reason=reason, session=session)

    def failure(
        self,
        code: str,
        message: str,
        category: FailureCategory,
        *,
        retryable: bool = False,
        calls: tuple[JudgeCallRecord, ...] = (),
    ) -> EvaluationRecordDraft:
        return EvaluationRecordDraft(
            invocation_key=self._invocation_key,
            evaluator=self.descriptor.evaluator,
            status=_failure_status(category),
            reason=message,
            judge_calls=calls,
            attempts=1,
            latency_ms=_call_latency(calls),
            failure=FailureDetail(category=category, code=code, message=message, retryable=retryable),
            created_at=self._clock(),
        )

    def judge_failure(
        self, error: JudgeCallError | BatchInputError | BatchOutputError, session: JudgeSession
    ) -> EvaluationRecordDraft:
        if isinstance(error, BatchInputError):
            return self.failure(
                "evaluation_payload_too_large",
                str(error),
                FailureCategory.RESOURCE_EXHAUSTED,
                calls=session.calls,
            )
        if isinstance(error, BatchOutputError):
            return self.failure(
                "incomplete_batch_verdicts",
                str(error),
                FailureCategory.INVALID_PROVIDER_OUTPUT,
                calls=session.calls,
            )
        return self.failure(
            error.failure.code,
            error.failure.message,
            error.failure.category,
            retryable=error.failure.retryable,
            calls=session.calls,
        )

    def _record(
        self,
        *,
        status: EvaluationRecordStatus,
        reason: str,
        session: JudgeSession,
        measurements: tuple[Measurement, ...] = (),
        findings: tuple[Finding, ...] = (),
    ) -> EvaluationRecordDraft:
        return EvaluationRecordDraft(
            invocation_key=self._invocation_key,
            evaluator=self.descriptor.evaluator,
            status=status,
            measurements=measurements,
            findings=findings,
            reason=reason,
            judge_calls=session.calls,
            attempts=1,
            latency_ms=session.latency_ms,
            created_at=self._clock(),
        )


def _failure_status(category: FailureCategory) -> EvaluationRecordStatus:
    if category is FailureCategory.CANCELLED:
        return EvaluationRecordStatus.CANCELLED
    return EvaluationRecordStatus.FAILED


def _call_latency(calls: tuple[JudgeCallRecord, ...]) -> int:
    return sum(attempt.latency_ms for call in calls for attempt in call.provenance.attempts)
