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

"""Provider capability planning without transport or credentials."""

from __future__ import annotations

from hugegraph_llm.extraction_runtime.provider.contracts import (
    AdaptationAction,
    AdaptationDecisionV1,
    AdaptationRecordV1,
    EffectiveRequestV1,
    ProviderCapabilitiesV1,
    ProviderNeutralRequestV1,
    UnsupportedProviderParameterError,
)
from hugegraph_llm.extraction_runtime.v1.json_value import JsonObject, digest_json, freeze_json_object


class ProviderDialectV1:
    """Plan a credential-free effective request from explicit capabilities."""

    contract = "provider-dialect/v1"

    def plan(
        self,
        request: ProviderNeutralRequestV1,
        capabilities: ProviderCapabilitiesV1,
    ) -> EffectiveRequestV1:
        payload: dict[str, object] = {
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content, "name": message.name} for message in request.messages
            ],
            "max_output_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "timeout_seconds": request.timeout_seconds,
            "retry_policy": {
                "max_attempts": request.retry_policy.max_attempts,
                "backoff_seconds": request.retry_policy.backoff_seconds,
            },
        }
        decisions: list[AdaptationDecisionV1] = []

        self._optional(
            payload,
            decisions,
            parameter="reasoning_effort",
            value=request.reasoning_effort,
            supported=capabilities.reasoning_effort,
        )
        self._optional(
            payload,
            decisions,
            parameter="thinking",
            value=request.thinking,
            supported=capabilities.thinking,
        )

        if request.tools or request.response_schema is not None:
            if not capabilities.structured_tools:
                raise UnsupportedProviderParameterError("structured_tools are required by this request")
            if request.tools:
                payload["tools"] = list(request.tools)
            if request.response_schema is not None:
                payload["response_schema"] = request.response_schema
            decisions.append(self._kept("structured_tools", "object"))

        if request.strict_schema:
            if capabilities.strict_schema:
                payload["strict_schema"] = True
                decisions.append(self._kept("strict_schema", "boolean"))
            else:
                payload["strict_schema"] = False
                decisions.append(
                    AdaptationDecisionV1(
                        parameter="strict_schema",
                        action=AdaptationAction.DOWNGRADED,
                        reason_code="unsupported_strict_schema",
                        requested_category="true",
                        effective_category="false",
                    )
                )

        self._optional(
            payload,
            decisions,
            parameter="parallel_tool_calls",
            value=request.parallel_tool_calls,
            supported=capabilities.parallel_tool_calls,
        )

        supported_optional = set(capabilities.optional_parameters)
        for name in sorted(request.optional_parameters):
            self._optional(
                payload,
                decisions,
                parameter=name,
                value=request.optional_parameters[name],
                supported=name in supported_optional,
            )

        effective_payload: JsonObject = freeze_json_object(payload)
        effective_digest = digest_json(effective_payload)
        record = AdaptationRecordV1(
            adapter_contract=self.contract,
            requested_digest=digest_json(request.as_evidence_payload()),
            effective_digest=effective_digest,
            decisions=tuple(decisions),
        )
        return EffectiveRequestV1(payload=effective_payload, adaptation=record)

    @staticmethod
    def _optional(
        payload: dict[str, object],
        decisions: list[AdaptationDecisionV1],
        *,
        parameter: str,
        value: object,
        supported: bool,
    ) -> None:
        if value is None:
            return
        category = ProviderDialectV1._category(value)
        if supported:
            payload[parameter] = value
            decisions.append(ProviderDialectV1._kept(parameter, category))
            return
        decisions.append(
            AdaptationDecisionV1(
                parameter=parameter,
                action=AdaptationAction.DROPPED,
                reason_code="unsupported_optional_parameter",
                requested_category=category,
                effective_category="absent",
            )
        )

    @staticmethod
    def _kept(parameter: str, category: str) -> AdaptationDecisionV1:
        return AdaptationDecisionV1(
            parameter=parameter,
            action=AdaptationAction.KEPT,
            reason_code="provider_supports_parameter",
            requested_category=category,
            effective_category=category,
        )

    @staticmethod
    def _category(value: object) -> str:
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, str):
            return "string"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, tuple | list):
            return "array"
        if isinstance(value, dict) or hasattr(value, "items"):
            return "object"
        return type(value).__name__
