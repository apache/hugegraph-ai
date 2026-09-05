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
    ProviderCapabilitiesV1,
    ProviderDialectV1,
    ProviderMessageV1,
    ProviderNeutralRequestV1,
    ProviderResponseV1,
    ReplayEntryV1,
    ReplayExhaustedError,
    ReplayMismatchError,
    ReplayProvider,
)

pytestmark = pytest.mark.unit


def _effective(prompt: str = "extract two bolts"):
    return ProviderDialectV1().plan(
        ProviderNeutralRequestV1(
            stage="extract",
            model="inventory-replay",
            messages=(ProviderMessageV1(role="user", content=prompt),),
            temperature=0.0,
        ),
        ProviderCapabilitiesV1(),
    )


def test_replay_provider_matches_effective_payload_and_captures_evidence() -> None:
    effective = _effective()
    response = ProviderResponseV1(
        output={"items": [{"sku": "A", "count": 2}]},
        model="inventory-replay",
        model_revision="fixture-1",
        usage={"input_tokens": 3, "output_tokens": 8},
    )
    provider = ReplayProvider(
        (
            ReplayEntryV1(
                effective.adaptation.requested_digest,
                effective.adaptation.effective_digest,
                response,
            ),
        )
    )

    actual = provider.execute(effective)

    assert actual == response
    assert actual.response_digest
    assert provider.effective_requests == (effective,)
    assert provider.remaining == 0
    assert provider.effective_requests[0].payload == effective.payload

    with pytest.raises(ReplayExhaustedError):
        provider.execute(effective)


def test_replay_provider_fails_closed_on_effective_request_mismatch() -> None:
    expected = _effective()
    actual = _effective("extract three nuts")
    provider = ReplayProvider(
        (
            ReplayEntryV1(
                expected.adaptation.requested_digest,
                expected.adaptation.effective_digest,
                ProviderResponseV1(output={"items": []}, model="inventory-replay"),
            ),
        )
    )

    with pytest.raises(ReplayMismatchError, match="request digest"):
        provider.execute(actual)
    assert provider.remaining == 1
    assert provider.effective_requests == ()
