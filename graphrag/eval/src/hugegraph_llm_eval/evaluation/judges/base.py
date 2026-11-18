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

"""Provider-neutral structured-output Judge request and result boundary."""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, Field, JsonValue, field_validator

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.contracts.digests import ContentDigest, canonical_digest
from hugegraph_llm_eval.contracts.domain.judge import (
    JudgeContentRef as JudgeContentRef,
)
from hugegraph_llm_eval.contracts.domain.judge import (
    JudgeProvenance,
    ProviderUsage,
)
from hugegraph_llm_eval.contracts.errors import FailureDetail


class JudgeDescriptor(StrictModel):
    provider: str = Field(min_length=1, max_length=127)
    model: str = Field(min_length=1, max_length=255)
    configuration_digest: ContentDigest

    @classmethod
    def create(
        cls,
        *,
        provider: str,
        model: str,
        configuration: JsonValue,
    ) -> "JudgeDescriptor":
        return cls(
            provider=provider,
            model=model,
            configuration_digest=canonical_digest(
                {"provider": provider, "model": model, "configuration": configuration}
            ),
        )


class JudgeMessage(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=1_000_000)


class JudgeOptions(StrictModel):
    max_attempts: int = Field(default=3, ge=1, le=20)
    deadline: datetime | None = None
    initial_backoff_seconds: float = Field(default=0, ge=0)
    max_backoff_seconds: float = Field(default=30, ge=0)

    @field_validator("deadline")
    @classmethod
    def _validate_deadline(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            msg = "deadline must include a timezone"
            raise ValueError(msg)
        return value

    @field_validator("initial_backoff_seconds", "max_backoff_seconds")
    @classmethod
    def _validate_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "backoff must be finite"
            raise ValueError(msg)
        return value


OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class JudgeRequest[OutputT: BaseModel]:
    messages: tuple[JudgeMessage, ...]
    response_type: type[OutputT]
    prompt: JudgeContentRef
    rubric: JudgeContentRef

    def __post_init__(self) -> None:
        if not self.messages:
            msg = "judge request requires at least one message"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class JudgeResult[OutputT: BaseModel]:
    output: OutputT
    provenance: JudgeProvenance
    usage: ProviderUsage


class JudgeCallError(RuntimeError):
    def __init__(self, failure: FailureDetail, provenance: JudgeProvenance) -> None:
        super().__init__(failure.message)
        self.failure = failure
        self.provenance = provenance


class Judge(Protocol):
    descriptor: JudgeDescriptor

    def judge(self, request: JudgeRequest[OutputT], options: JudgeOptions) -> JudgeResult[OutputT]: ...
