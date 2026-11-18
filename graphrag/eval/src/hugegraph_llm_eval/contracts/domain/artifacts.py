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

"""Content-addressed Artifact contracts and storage port."""

from enum import StrEnum
from typing import Protocol

from pydantic import Field, JsonValue, field_validator, model_validator

from hugegraph_llm_eval.contracts.base import AwareDatetime, VersionedModel
from hugegraph_llm_eval.contracts.digests import ContentDigest, canonical_json_bytes
from hugegraph_llm_eval.contracts.identity import ArtifactId, SchemaRef


class ArtifactSensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ArtifactRetention(StrEnum):
    EPHEMERAL = "ephemeral"
    STANDARD = "standard"
    LONG_TERM = "long_term"
    LEGAL_HOLD = "legal_hold"


class ArtifactDescriptor(VersionedModel):
    media_type: str = Field(min_length=3, max_length=255)
    schema_ref: SchemaRef
    sensitivity: ArtifactSensitivity
    retention: ArtifactRetention

    @field_validator("media_type")
    @classmethod
    def _validate_media_type(cls, value: str) -> str:
        if "/" not in value or any(char.isspace() for char in value):
            msg = "media_type must be an IANA-style type/subtype"
            raise ValueError(msg)
        return value.lower()


class ArtifactRef(VersionedModel):
    artifact_id: ArtifactId
    digest: ContentDigest
    descriptor: ArtifactDescriptor
    size_bytes: int = Field(ge=0)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _validate_identity(self) -> "ArtifactRef":
        if self.artifact_id != ArtifactId.from_digest(self.digest):
            msg = "artifact_id must be derived from digest"
            raise ValueError(msg)
        return self

    @classmethod
    def from_content(
        cls,
        content: bytes,
        descriptor: ArtifactDescriptor,
        *,
        created_at: AwareDatetime,
    ) -> "ArtifactRef":
        digest = ContentDigest.from_bytes(content)
        return cls(
            artifact_id=ArtifactId.from_digest(digest),
            digest=digest,
            descriptor=descriptor,
            size_bytes=len(content),
            created_at=created_at,
        )

    @classmethod
    def from_json(
        cls,
        payload: JsonValue,
        *,
        schema_namespace: str,
        schema_name: str,
        created_at: AwareDatetime,
        schema_version: int = 1,
        sensitivity: ArtifactSensitivity = ArtifactSensitivity.INTERNAL,
        retention: ArtifactRetention = ArtifactRetention.STANDARD,
    ) -> "ArtifactRef":
        descriptor = ArtifactDescriptor(
            media_type="application/json",
            schema_ref=SchemaRef(namespace=schema_namespace, name=schema_name, version=schema_version),
            sensitivity=sensitivity,
            retention=retention,
        )
        return cls.from_content(canonical_json_bytes(payload), descriptor, created_at=created_at)


class ArtifactVerificationStatus(StrEnum):
    VERIFIED = "verified"
    MISSING = "missing"
    CORRUPT = "corrupt"
    METADATA_CONFLICT = "metadata_conflict"


class ArtifactVerification(VersionedModel):
    artifact: ArtifactRef
    status: ArtifactVerificationStatus
    actual_digest: ContentDigest | None = None
    reason: str | None = Field(default=None, max_length=2_000)


class ArtifactStore(Protocol):
    def put(self, content: bytes, descriptor: ArtifactDescriptor) -> ArtifactRef: ...

    def read(self, ref: ArtifactRef) -> bytes: ...

    def verify(self, ref: ArtifactRef) -> ArtifactVerification: ...
