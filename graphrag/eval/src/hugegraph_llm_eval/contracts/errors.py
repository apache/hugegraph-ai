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

"""Cross-boundary failure taxonomy without score semantics."""

from enum import StrEnum

from pydantic import Field

from hugegraph_llm_eval.contracts.base import VersionedModel


class FailureCategory(StrEnum):
    INVALID_INPUT = "invalid_input"
    USER_CODE = "user_code"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_REFUSAL = "provider_refusal"
    INVALID_PROVIDER_OUTPUT = "invalid_provider_output"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    STORAGE_CONFLICT = "storage_conflict"
    STORAGE_CORRUPT = "storage_corrupt"
    INTERNAL = "internal"


class FailureDetail(VersionedModel):
    category: FailureCategory
    code: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1, max_length=2_000)
    retryable: bool
