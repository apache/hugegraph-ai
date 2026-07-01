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

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class GraphExtractError(BaseModel):
    code: str
    message: str
    phase: str
    job_id: Optional[str] = None


class GraphExtractResponse(BaseModel):
    status: Literal["succeeded"] = "succeeded"
    result: Dict[str, Any]
    warnings: List[str] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)


class GraphExtractJobCreateResponse(BaseModel):
    job_id: str
    status: str
    result_url: str
    created_at: str
    updated_at: str


class GraphExtractJobStatusResponse(BaseModel):
    job_id: str
    status: str
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    expires_at: Optional[str] = None
    error: Optional[GraphExtractError] = None


class GraphImportResponse(BaseModel):
    status: str = "succeeded"
    vertex_count: int = 0
    edge_count: int = 0
    triple_count: int = 0
    updated_embeddings: bool = False
    warnings: List[str] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)


class GraphExtractAndImportResponse(BaseModel):
    status: str = "succeeded"
    extract_result: GraphExtractResponse
    import_result: GraphImportResponse
