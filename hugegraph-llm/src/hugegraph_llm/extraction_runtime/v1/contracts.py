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

"""Inputs and per-chunk results for reviewed extraction."""

from dataclasses import asdict, dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExtractionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_reviews: int = Field(default=2, ge=0, le=5, strict=True)
    max_fixes: int = Field(default=1, ge=0, le=3, strict=True)
    max_workers: int = Field(default=4, ge=1, le=8, strict=True)


@dataclass
class ChunkInput:
    index: int
    text: str


@dataclass
class Issue:
    path: str
    message: str
    evidence: str | None = None


@dataclass
class ReviewResult:
    decision: Literal["pass", "fix", "block"]
    issues: list[Issue] = field(default_factory=list)


@dataclass
class ChunkResult:
    index: int
    status: Literal["final", "candidate", "blocked", "failed"]
    graph: dict | None
    issues: list[Issue]
    reason: str
    stage: str | None
    reviews_used: int
    fixes_used: int
    llm_calls: int

    def as_dict(self) -> dict:
        return asdict(self)
