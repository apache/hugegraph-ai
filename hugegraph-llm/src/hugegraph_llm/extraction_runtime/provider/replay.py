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

"""Credential-free deterministic provider transcript replay."""

from __future__ import annotations

from dataclasses import dataclass

from hugegraph_llm.extraction_runtime.provider.contracts import EffectiveRequestV1, ProviderResponseV1
from hugegraph_llm.extraction_runtime.v1.json_value import digest_json


class ReplayProviderError(RuntimeError):
    """Base replay transcript error."""


class ReplayMismatchError(ReplayProviderError):
    """Raised when the next transcript request is not the effective request."""


class ReplayExhaustedError(ReplayProviderError):
    """Raised when execution exceeds the frozen transcript."""


@dataclass(frozen=True)
class ReplayEntryV1:
    requested_request_digest: str
    effective_request_digest: str
    response: ProviderResponseV1


class ReplayProvider:
    """Execute an ordered immutable transcript with exact request matching."""

    def __init__(self, entries: tuple[ReplayEntryV1, ...]) -> None:
        self._entries = entries
        self._position = 0
        self._effective_requests: tuple[EffectiveRequestV1, ...] = ()

    @property
    def effective_requests(self) -> tuple[EffectiveRequestV1, ...]:
        return self._effective_requests

    @property
    def remaining(self) -> int:
        return len(self._entries) - self._position

    def execute(self, request: EffectiveRequestV1) -> ProviderResponseV1:
        if self._position >= len(self._entries):
            raise ReplayExhaustedError("replay transcript is exhausted")
        actual_digest = digest_json(request.payload)
        if actual_digest != request.adaptation.effective_digest:
            raise ReplayMismatchError("effective request payload no longer matches its adaptation record")
        entry = self._entries[self._position]
        if entry.requested_request_digest != request.adaptation.requested_digest:
            raise ReplayMismatchError("provider-neutral request digest does not match the next replay entry")
        if entry.effective_request_digest != actual_digest:
            raise ReplayMismatchError("effective request digest does not match the next replay entry")
        self._effective_requests += (request,)
        self._position += 1
        return entry.response
