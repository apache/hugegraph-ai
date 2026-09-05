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

import pytest

from hugegraph_llm.extraction_runtime.provider import (
    AdaptationAction,
    ProviderCapabilitiesV1,
    ProviderDialectV1,
    ProviderMessageV1,
    ProviderNeutralRequestV1,
    RetryPolicyV1,
    UnsupportedProviderParameterError,
)

pytestmark = pytest.mark.contract


def _request() -> ProviderNeutralRequestV1:
    return ProviderNeutralRequestV1(
        stage="extract",
        model="inventory-replay",
        messages=(ProviderMessageV1(role="user", content="extract two bolts"),),
        max_output_tokens=512,
        temperature=0.0,
        reasoning_effort="high",
        thinking={"type": "enabled", "budget_tokens": 256},
        tools=(
            {
                "type": "function",
                "function": {
                    "name": "emit_graph",
                    "parameters": {"type": "object", "properties": {"items": {"type": "array"}}},
                },
            },
        ),
        response_schema={"type": "object", "required": ["items"]},
        strict_schema=True,
        parallel_tool_calls=False,
        optional_parameters={"seed": 7, "service_tier": "default"},
        timeout_seconds=30.0,
        retry_policy=RetryPolicyV1(max_attempts=2, backoff_seconds=0.5),
    )


def test_supported_parameters_are_preserved_in_credential_free_payload() -> None:
    effective = ProviderDialectV1().plan(
        _request(),
        ProviderCapabilitiesV1(
            reasoning_effort=True,
            thinking=True,
            structured_tools=True,
            strict_schema=True,
            parallel_tool_calls=True,
            optional_parameters=("seed", "service_tier"),
        ),
    )

    assert effective.payload["reasoning_effort"] == "high"
    assert effective.payload["thinking"] == {"type": "enabled", "budget_tokens": 256}
    assert effective.payload["strict_schema"] is True
    assert effective.payload["parallel_tool_calls"] is False
    assert effective.payload["seed"] == 7
    assert effective.payload["service_tier"] == "default"
    assert "api_key" not in effective.payload
    assert "authorization" not in effective.payload
    assert all(decision.action is AdaptationAction.KEPT for decision in effective.adaptation.decisions)
    assert effective.adaptation.effective_digest
    assert effective.adaptation.requested_digest


def test_unsupported_optional_parameters_are_recorded_and_removed() -> None:
    effective = ProviderDialectV1().plan(
        _request(),
        ProviderCapabilitiesV1(structured_tools=True),
    )

    assert "reasoning_effort" not in effective.payload
    assert "thinking" not in effective.payload
    assert effective.payload["strict_schema"] is False
    assert "parallel_tool_calls" not in effective.payload
    assert "seed" not in effective.payload
    assert "service_tier" not in effective.payload
    decisions = {decision.parameter: decision for decision in effective.adaptation.decisions}
    assert decisions["reasoning_effort"].action is AdaptationAction.DROPPED
    assert decisions["thinking"].reason_code == "unsupported_optional_parameter"
    assert decisions["strict_schema"].action is AdaptationAction.DOWNGRADED
    assert decisions["parallel_tool_calls"].action is AdaptationAction.DROPPED
    assert decisions["seed"].action is AdaptationAction.DROPPED


def test_structured_tools_fail_closed_when_provider_cannot_execute_them() -> None:
    with pytest.raises(UnsupportedProviderParameterError, match="structured_tools"):
        ProviderDialectV1().plan(_request(), ProviderCapabilitiesV1())


@pytest.mark.parametrize("name", ["api_key", "authorization", "password", "access_token", "cookie"])
def test_request_rejects_credential_shaped_optional_parameters(name: str) -> None:
    with pytest.raises(ValueError, match="credential"):
        ProviderNeutralRequestV1(
            stage="extract",
            model="replay",
            messages=(ProviderMessageV1(role="user", content="hello"),),
            optional_parameters={name: "secret"},
        )


def test_optional_parameters_cannot_override_typed_request_fields() -> None:
    with pytest.raises(ValueError, match="collides"):
        ProviderNeutralRequestV1(
            stage="extract",
            model="replay",
            messages=(ProviderMessageV1(role="user", content="hello"),),
            optional_parameters={"model": "different-model"},
        )
