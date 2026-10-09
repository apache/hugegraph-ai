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

from typing import Any

from pydantic import BaseModel, Field


class RAGResponse(BaseModel):
    status_code: int = -1
    message: str = ""


class ThinAPIError(BaseModel):
    type: str
    message: str
    suggestion: str | None = None
    retryable: bool = False
    source: str = "hugegraph-llm"
    details: dict[str, Any] = Field(default_factory=dict)


class ThinAPIMeta(BaseModel):
    request_id: str
    duration_ms: float = 0.0


class ThinAPIResponse(BaseModel):
    ok: bool
    data: Any = None
    error: ThinAPIError | None = None
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    meta: ThinAPIMeta
