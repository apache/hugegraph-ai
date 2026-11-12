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

"""Nominal identifiers and structured references."""

import re
import uuid
from typing import ClassVar, Self

from pydantic import Field, field_validator

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.contracts.digests import ContentDigest

_TOKEN_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,126}$")
_ID_SUFFIX_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,254}$")


class OpaqueId(StrictModel):
    """Nominal string ID base; concrete subclasses own a stable prefix."""

    prefix: ClassVar[str]
    value: str

    @field_validator("value")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not value.startswith(cls.prefix):
            msg = f"identifier must start with {cls.prefix!r}"
            raise ValueError(msg)
        suffix = value.removeprefix(cls.prefix)
        if not _ID_SUFFIX_RE.fullmatch(suffix):
            msg = "identifier suffix contains unsupported characters"
            raise ValueError(msg)
        return value


class GeneratedId(OpaqueId):
    @classmethod
    def new(cls) -> Self:
        return cls(value=f"{cls.prefix}{uuid.uuid4().hex}")


class ContentAddressedId(OpaqueId):
    @classmethod
    def from_digest(cls, digest: ContentDigest) -> Self:
        return cls(value=f"{cls.prefix}{digest.value}")


class ArtifactId(ContentAddressedId):
    prefix = "artifact:"


class EvaluationInputId(ContentAddressedId):
    prefix = "evaluation-input:"


class EvaluationRunId(GeneratedId):
    prefix = "evaluation-run:"


class EvaluationRecordId(GeneratedId):
    prefix = "evaluation-record:"


class SchemaRef(StrictModel):
    namespace: str
    name: str
    version: int = Field(ge=1)

    @field_validator("namespace", "name")
    @classmethod
    def _validate_token(cls, value: str) -> str:
        if not _TOKEN_RE.fullmatch(value):
            msg = "reference segments must be stable tokens"
            raise ValueError(msg)
        return value

    def __str__(self) -> str:
        return f"{self.namespace}/{self.name}@v{self.version}"


class ComponentRef(StrictModel):
    namespace: str
    name: str
    revision: str

    @field_validator("namespace", "name", "revision")
    @classmethod
    def _validate_token(cls, value: str) -> str:
        if not _TOKEN_RE.fullmatch(value):
            msg = "reference segments must be stable tokens"
            raise ValueError(msg)
        return value

    def __str__(self) -> str:
        return f"{self.namespace}/{self.name}@{self.revision}"


class EvaluatorRef(ComponentRef):
    """Versioned semantic identity for one Evaluator implementation contract."""
