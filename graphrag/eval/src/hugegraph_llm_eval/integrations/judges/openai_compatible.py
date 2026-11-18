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

"""OpenAI-compatible structured-output adapter with auditable attempts."""

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from pydantic import Field, JsonValue, field_validator

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.contracts.domain.judge import ProviderUsage
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.evaluation.judges.base import (
    JudgeDescriptor,
    JudgeRequest,
    OutputT,
)
from hugegraph_llm_eval.integrations.judges.attempts import (
    AttemptFailureError,
    AttemptLoopJudge,
    AttemptOutcome,
    failure,
)
from hugegraph_llm_eval.integrations.judges.openai_response import (
    OpenAIResponse,
    OpenAIResponseUsage,
    classify_exception,
    exception_usage,
    provider_outcome,
)


class OpenAIParseTransport(Protocol):
    def parse(self, **kwargs: object) -> object: ...


@dataclass(frozen=True, slots=True)
class OpenAICompatiblePricing:
    input_usd_per_million: float | None
    output_usd_per_million: float | None

    def __post_init__(self) -> None:
        values = (self.input_usd_per_million, self.output_usd_per_million)
        if any(value is not None and (not math.isfinite(value) or value < 0) for value in values):
            msg = "judge token pricing must be finite and non-negative"
            raise ValueError(msg)


class OpenAICompatibleSettings(StrictModel):
    temperature: float = Field(default=0, ge=0, le=2)
    seed: int | None = 42
    max_tokens: int = Field(default=131_072, ge=1)
    include_json_schema_instruction: bool = True
    extra_body: dict[str, JsonValue] | None = None

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "temperature must be finite"
            raise ValueError(msg)
        return value


def _configuration_payload(
    settings: OpenAICompatibleSettings,
    pricing: OpenAICompatiblePricing,
    transport: JsonValue = None,
) -> JsonValue:
    payload: dict[str, JsonValue] = {
        "generation": settings.model_dump(mode="json"),
        "pricing": {
            "input_usd_per_million": pricing.input_usd_per_million,
            "output_usd_per_million": pricing.output_usd_per_million,
        },
    }
    if transport is not None:
        payload["transport"] = transport
    return payload


def _structured_messages(
    request: JudgeRequest[OutputT],
    *,
    include_schema_instruction: bool,
) -> list[dict[str, object]]:
    messages = [message.model_dump(mode="json") for message in request.messages]
    if not include_schema_instruction:
        return messages
    schema = json.dumps(
        request.response_type.model_json_schema(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    instruction = {
        "role": "system",
        "content": f"Return only valid JSON matching this JSON Schema: {schema}",
    }
    return [instruction, *messages]


class OpenAICompatibleJudge(AttemptLoopJudge):
    """Adapts one chat-completions parse transport to the Judge port."""

    def __init__(
        self,
        *,
        transport: OpenAIParseTransport,
        descriptor: JudgeDescriptor,
        pricing: OpenAICompatiblePricing,
        settings: OpenAICompatibleSettings,
        clock: Callable[[], datetime],
        transport_configuration: JsonValue = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(descriptor=descriptor, clock=clock, monotonic=monotonic, sleep=sleep)
        self._transport = transport
        self._pricing = pricing
        self._settings = settings
        expected = JudgeDescriptor.create(
            provider=descriptor.provider,
            model=descriptor.model,
            configuration=_configuration_payload(settings, pricing, transport_configuration),
        )
        if descriptor.configuration_digest != expected.configuration_digest:
            msg = "JudgeDescriptor configuration digest does not match OpenAI-compatible settings"
            raise ValueError(msg)

    def _classify(self, error: Exception) -> FailureDetail:
        return classify_exception(error)

    def _billed_usage(self, error: Exception) -> ProviderUsage | None:
        return exception_usage(error, self._usage)

    def _attempt(self, request: JudgeRequest[OutputT], timeout: float | None) -> AttemptOutcome:
        kwargs: dict[str, object] = {
            "model": self.descriptor.model,
            "messages": _structured_messages(
                request,
                include_schema_instruction=self._settings.include_json_schema_instruction,
            ),
            "response_format": request.response_type,
            "temperature": self._settings.temperature,
            "max_tokens": self._settings.max_tokens,
        }
        if self._settings.seed is not None:
            kwargs["seed"] = self._settings.seed
        if self._settings.extra_body is not None:
            kwargs["extra_body"] = self._settings.extra_body
        if timeout is not None:
            kwargs["timeout"] = timeout
        response = cast(OpenAIResponse, self._transport.parse(**kwargs))
        return provider_outcome(request, response, self._usage)

    def _usage(self, raw: OpenAIResponseUsage | None) -> ProviderUsage:
        input_tokens = raw.prompt_tokens if raw is not None else 0
        output_tokens = raw.completion_tokens if raw is not None else 0
        if raw is not None and raw.total_tokens != input_tokens + output_tokens:
            failure_detail = failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "inconsistent_provider_usage", False)
            raise AttemptFailureError(failure_detail)
        cost = None
        rates = (self._pricing.input_usd_per_million, self._pricing.output_usd_per_million)
        if raw is not None and all(rate is not None for rate in rates):
            input_rate = cast(float, self._pricing.input_usd_per_million)
            output_rate = cast(float, self._pricing.output_usd_per_million)
            cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
        return ProviderUsage(
            provider=self.descriptor.provider,
            model=self.descriptor.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost,
            reported=raw is not None,
        )
