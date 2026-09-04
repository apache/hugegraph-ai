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

"""Narrow protocol for a future backend-enforced property CAS primitive.

This module defines an integration boundary only.  ``GraphManager`` does not
implement it because HugeGraph 1.7 has no server endpoint with these semantics.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class PropertyCASStatus(str, Enum):
    """Evidence-backed result of one atomic property replacement."""

    APPLIED = "APPLIED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PropertyCASReceipt:
    """Receipt returned by a backend, preserving operation identity."""

    operation_id: str
    status: PropertyCASStatus
    observed_properties: Mapping[str, Any] | None = None
    reason_code: str | None = None


@runtime_checkable
class PropertyCASAdapter(Protocol):
    """Atomic expected-state to desired-state property replacement."""

    def replace_properties_if_match(
        self,
        *,
        target_type: str,
        target_id: Any,
        expected_properties: Mapping[str, Any],
        desired_properties: Mapping[str, Any],
        operation_id: str,
    ) -> PropertyCASReceipt:
        """Replace all target properties only when expected state matches."""
