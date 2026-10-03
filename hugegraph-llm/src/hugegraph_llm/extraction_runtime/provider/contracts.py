# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Credential-free provider-neutral execution contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol

from hugegraph_llm.extraction_runtime.v1.json_value import JsonObject, digest_json, freeze_json_object

_CREDENTIAL_PARAMETER_NAMES = {
    "api_key",
    "authorization",
    "cookie",
    "cookies",
    "password",
    "secret",
    "token",
}
_RESERVED_PARAMETER_NAMES = {
    "max_output_tokens",
    "messages",
    "model",
    "parallel_tool_calls",
    "reasoning_effort",
    "response_schema",
    "retry_policy",
    "strict_schema",
    "thinking",
    "timeout_seconds",
    "tools",
}


class UnsupportedProviderParameterError(ValueError):
    """Raised when removing a parameter would change required semantics."""


class AdaptationAction(str, Enum):
    KEPT = "kept"
    DROPPED = "dropped"
    DOWNGRADED = "downgraded"


@dataclass(frozen=True)
class ProviderMessageV1:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("provider message content must not be empty")


@dataclass(frozen=True)
class RetryPolicyV1:
    max_attempts: int = 1
    backoff_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if not math.isfinite(self.backoff_seconds) or self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must be finite and non-negative")


@dataclass(frozen=True)
class ProviderNeutralRequestV1:
    stage: str
    model: str
    messages: tuple[ProviderMessageV1, ...]
    max_output_tokens: int = 1024
    temperature: float = 0.0
    reasoning_effort: str | None = None
    thinking: JsonObject | None = None
    tools: tuple[JsonObject, ...] = ()
    response_schema: JsonObject | None = None
    strict_schema: bool = False
    parallel_tool_calls: bool | None = None
    optional_parameters: JsonObject = field(default_factory=dict)
    timeout_seconds: float = 30.0
    retry_policy: RetryPolicyV1 = field(default_factory=RetryPolicyV1)
    contract: Literal["provider-neutral-request/v1"] = "provider-neutral-request/v1"

    def __post_init__(self) -> None:
        if not self.stage:
            raise ValueError("provider request stage must not be empty")
        if not self.model:
            raise ValueError("provider request model must not be empty")
        if not self.messages:
            raise ValueError("provider request must contain at least one message")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if not math.isfinite(self.temperature) or self.temperature < 0:
            raise ValueError("temperature must be finite and non-negative")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if self.strict_schema and not (self.tools or self.response_schema):
            raise ValueError("strict_schema requires tools or a response schema")
        if self.parallel_tool_calls is not None and not self.tools:
            raise ValueError("parallel_tool_calls requires tools")
        frozen_optional = freeze_json_object(self.optional_parameters)
        for name in frozen_optional:
            normalized = name.lower().replace("-", "_")
            if normalized in _CREDENTIAL_PARAMETER_NAMES or normalized.endswith("_token"):
                raise ValueError(f"credential parameter {name!r} is forbidden")
            if normalized in _RESERVED_PARAMETER_NAMES:
                raise ValueError(f"optional parameter {name!r} collides with a typed field")
        object.__setattr__(self, "optional_parameters", frozen_optional)
        object.__setattr__(self, "tools", tuple(freeze_json_object(tool) for tool in self.tools))
        if self.thinking is not None:
            object.__setattr__(self, "thinking", freeze_json_object(self.thinking))
        if self.response_schema is not None:
            object.__setattr__(self, "response_schema", freeze_json_object(self.response_schema))

    def as_evidence_payload(self) -> JsonObject:
        return freeze_json_object(
            {
                "contract": self.contract,
                "stage": self.stage,
                "model": self.model,
                "messages": [
                    {"role": message.role, "content": message.content, "name": message.name}
                    for message in self.messages
                ],
                "max_output_tokens": self.max_output_tokens,
                "temperature": self.temperature,
                "reasoning_effort": self.reasoning_effort,
                "thinking": self.thinking,
                "tools": list(self.tools),
                "response_schema": self.response_schema,
                "strict_schema": self.strict_schema,
                "parallel_tool_calls": self.parallel_tool_calls,
                "optional_parameters": self.optional_parameters,
                "timeout_seconds": self.timeout_seconds,
                "retry_policy": {
                    "max_attempts": self.retry_policy.max_attempts,
                    "backoff_seconds": self.retry_policy.backoff_seconds,
                },
            }
        )


@dataclass(frozen=True)
class ProviderCapabilitiesV1:
    reasoning_effort: bool = False
    thinking: bool = False
    structured_tools: bool = False
    strict_schema: bool = False
    parallel_tool_calls: bool = False
    optional_parameters: tuple[str, ...] = ()
    contract: Literal["provider-capabilities/v1"] = "provider-capabilities/v1"

    def __post_init__(self) -> None:
        if len(set(self.optional_parameters)) != len(self.optional_parameters):
            raise ValueError("provider optional capability names must be unique")


@dataclass(frozen=True)
class AdaptationDecisionV1:
    parameter: str
    action: AdaptationAction
    reason_code: str
    requested_category: str
    effective_category: str


@dataclass(frozen=True)
class AdaptationRecordV1:
    adapter_contract: str
    requested_digest: str
    effective_digest: str
    decisions: tuple[AdaptationDecisionV1, ...]


@dataclass(frozen=True)
class EffectiveRequestV1:
    payload: JsonObject
    adaptation: AdaptationRecordV1
    contract: Literal["provider-effective-request/v1"] = "provider-effective-request/v1"

    def __post_init__(self) -> None:
        frozen = freeze_json_object(self.payload)
        if digest_json(frozen) != self.adaptation.effective_digest:
            raise ValueError("adaptation effective_digest does not bind the effective payload")
        object.__setattr__(self, "payload", frozen)


@dataclass(frozen=True)
class ProviderResponseV1:
    output: JsonObject
    model: str
    model_revision: str | None = None
    usage: JsonObject = field(default_factory=dict)
    contract: Literal["provider-response/v1"] = "provider-response/v1"

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("provider response model must not be empty")
        object.__setattr__(self, "output", freeze_json_object(self.output))
        object.__setattr__(self, "usage", freeze_json_object(self.usage))

    @property
    def response_digest(self) -> str:
        return digest_json(
            {
                "contract": self.contract,
                "output": self.output,
                "model": self.model,
                "model_revision": self.model_revision,
                "usage": self.usage,
            }
        )


class ProviderAdapterV1(Protocol):
    def plan(
        self,
        request: ProviderNeutralRequestV1,
        capabilities: ProviderCapabilitiesV1,
    ) -> EffectiveRequestV1: ...


class ProviderTransportV1(Protocol):
    def execute(self, request: EffectiveRequestV1) -> ProviderResponseV1: ...
