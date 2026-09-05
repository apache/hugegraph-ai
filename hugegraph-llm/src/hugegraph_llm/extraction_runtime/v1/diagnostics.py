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

"""Stable, credential-free runtime diagnostic envelopes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from hugegraph_llm.extraction_runtime.v1.json_value import JsonObject, ensure_credential_free, freeze_json_object


class DiagnosticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class DiagnosticV1:
    code: str
    stage: str
    severity: DiagnosticSeverity
    details: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("diagnostic code must not be empty")
        if not self.stage:
            raise ValueError("diagnostic stage must not be empty")
        details = freeze_json_object(self.details)
        ensure_credential_free(details, path="$.details")
        object.__setattr__(self, "details", details)
