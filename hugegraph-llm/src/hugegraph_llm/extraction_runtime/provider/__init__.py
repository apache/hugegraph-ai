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

"""Experimental provider-neutral seam; no production transport is wired."""

from hugegraph_llm.extraction_runtime.provider.contracts import (
    AdaptationAction,
    AdaptationDecisionV1,
    AdaptationRecordV1,
    EffectiveRequestV1,
    ProviderAdapterV1,
    ProviderCapabilitiesV1,
    ProviderMessageV1,
    ProviderNeutralRequestV1,
    ProviderResponseV1,
    ProviderTransportV1,
    RetryPolicyV1,
    UnsupportedProviderParameterError,
)
from hugegraph_llm.extraction_runtime.provider.dialect import ProviderDialectV1
from hugegraph_llm.extraction_runtime.provider.replay import (
    ReplayEntryV1,
    ReplayExhaustedError,
    ReplayMismatchError,
    ReplayProvider,
    ReplayProviderError,
)

__all__ = [
    "AdaptationAction",
    "AdaptationDecisionV1",
    "AdaptationRecordV1",
    "EffectiveRequestV1",
    "ProviderAdapterV1",
    "ProviderCapabilitiesV1",
    "ProviderDialectV1",
    "ProviderMessageV1",
    "ProviderNeutralRequestV1",
    "ProviderResponseV1",
    "ProviderTransportV1",
    "ReplayEntryV1",
    "ReplayExhaustedError",
    "ReplayMismatchError",
    "ReplayProvider",
    "ReplayProviderError",
    "RetryPolicyV1",
    "UnsupportedProviderParameterError",
]
