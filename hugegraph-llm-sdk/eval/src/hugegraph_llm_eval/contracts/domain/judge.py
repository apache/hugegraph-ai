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

"""Persisted provider usage, attempts, and Judge provenance."""

import math
from enum import StrEnum

from pydantic import Field, model_validator

from hugegraph_llm_eval.contracts.base import VersionedModel
from hugegraph_llm_eval.contracts.digests import ContentDigest
from hugegraph_llm_eval.contracts.errors import FailureDetail
from hugegraph_llm_eval.contracts.identity import ComponentRef


class ProviderUsage(VersionedModel):
    provider: str = Field(min_length=1, max_length=127)
    model: str = Field(min_length=1, max_length=255)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    reported: bool = True

    @model_validator(mode="after")
    def _validate_total(self) -> "ProviderUsage":
        if self.total_tokens != self.input_tokens + self.output_tokens:
            msg = "total_tokens must equal input_tokens + output_tokens"
            raise ValueError(msg)
        if self.cost_usd is not None and not math.isfinite(self.cost_usd):
            msg = "cost_usd must be finite"
            raise ValueError(msg)
        if not self.reported and (self.total_tokens != 0 or self.cost_usd is not None):
            msg = "unreported usage cannot invent token counts or cost"
            raise ValueError(msg)
        return self


class ProviderAttemptStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class JudgeContentRef(VersionedModel):
    component: ComponentRef
    content_digest: ContentDigest


class ProviderAttempt(VersionedModel):
    attempt_index: int = Field(ge=1)
    provider: str = Field(min_length=1, max_length=127)
    model: str = Field(min_length=1, max_length=255)
    status: ProviderAttemptStatus
    latency_ms: int = Field(ge=0)
    usage: ProviderUsage | None = None
    failure: FailureDetail | None = None

    @model_validator(mode="after")
    def _validate_status(self) -> "ProviderAttempt":
        if self.status is ProviderAttemptStatus.COMPLETED and self.failure is not None:
            msg = "completed provider attempt cannot contain failure"
            raise ValueError(msg)
        if self.status is ProviderAttemptStatus.FAILED and self.failure is None:
            msg = "failed provider attempt requires failure"
            raise ValueError(msg)
        return self


class JudgeProvenance(VersionedModel):
    provider: str = Field(min_length=1, max_length=127)
    model: str = Field(min_length=1, max_length=255)
    configuration_digest: ContentDigest
    prompt: JudgeContentRef
    rubric: JudgeContentRef
    attempts: tuple[ProviderAttempt, ...] = Field(min_length=1)
    response_id: str | None = Field(default=None, max_length=255)
    response_model: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _validate_attempts(self) -> "JudgeProvenance":
        indices = tuple(attempt.attempt_index for attempt in self.attempts)
        if indices != tuple(range(1, len(indices) + 1)):
            msg = "provider attempt indices must be contiguous and one-based"
            raise ValueError(msg)
        if any(attempt.provider != self.provider or attempt.model != self.model for attempt in self.attempts):
            msg = "provider attempts must match judge provider and model"
            raise ValueError(msg)
        return self


class JudgeCallStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class JudgeCallRecord(VersionedModel):
    call_index: int = Field(ge=1)
    call_key: str = Field(min_length=1, max_length=127, pattern=r"^[a-z][a-z0-9_.-]*$")
    status: JudgeCallStatus
    provenance: JudgeProvenance
    usage: ProviderUsage | None = None
    failure: FailureDetail | None = None

    @model_validator(mode="after")
    def _validate_status(self) -> "JudgeCallRecord":
        if self.status is JudgeCallStatus.COMPLETED:
            if self.failure is not None or self.usage is None:
                msg = "completed judge call requires usage and cannot contain failure"
                raise ValueError(msg)
            if self.provenance.attempts[-1].status is not ProviderAttemptStatus.COMPLETED:
                msg = "completed judge call requires a completed final provider attempt"
                raise ValueError(msg)
        elif self.failure is None:
            msg = "failed judge call requires failure"
            raise ValueError(msg)
        if self.usage is not None and (
            self.usage.provider != self.provenance.provider or self.usage.model != self.provenance.model
        ):
            msg = "judge call usage must match provenance provider and model"
            raise ValueError(msg)
        return self


def judge_call_cost_is_unknown(call: JudgeCallRecord) -> bool:
    """Report whether any provider attempt lacks a reported cost."""
    return any(
        attempt.usage is None or not attempt.usage.reported or attempt.usage.cost_usd is None
        for attempt in call.provenance.attempts
    )
