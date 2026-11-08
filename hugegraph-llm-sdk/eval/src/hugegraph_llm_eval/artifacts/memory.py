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

"""Default in-process artifact storage for callers without persistence."""

from collections.abc import Callable
from datetime import datetime

from pydantic import JsonValue

from hugegraph_llm_eval.contracts.digests import ContentDigest, canonical_json_bytes
from hugegraph_llm_eval.contracts.domain.artifacts import (
    ArtifactDescriptor,
    ArtifactRef,
    ArtifactRetention,
    ArtifactSensitivity,
    ArtifactVerification,
    ArtifactVerificationStatus,
)
from hugegraph_llm_eval.contracts.identity import SchemaRef
from hugegraph_llm_eval.utils.clock import utc_now


class InMemoryArtifactStore:
    """Keep artifact bytes in memory, keyed by content digest.

    The store satisfies the ``ArtifactStore`` port so evaluators can run without a
    database or filesystem. Process lifetime bounds retention: content is dropped
    when the store is garbage collected, which keeps evaluation inputs out of any
    implicit on-disk cache.
    """

    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock
        self._content: dict[str, bytes] = {}
        self._refs: dict[str, ArtifactRef] = {}

    def put(self, content: bytes, descriptor: ArtifactDescriptor) -> ArtifactRef:
        """Store ``content`` and return the content-addressed reference."""
        ref = ArtifactRef.from_content(bytes(content), descriptor, created_at=self._clock())
        self._content[ref.artifact_id.value] = bytes(content)
        self._refs[ref.artifact_id.value] = ref
        return ref

    def put_json(
        self,
        payload: JsonValue,
        *,
        schema_namespace: str,
        schema_name: str,
        schema_version: int = 1,
        sensitivity: ArtifactSensitivity = ArtifactSensitivity.INTERNAL,
        retention: ArtifactRetention = ArtifactRetention.STANDARD,
    ) -> ArtifactRef:
        """Store a JSON-compatible payload under a declared input schema."""
        descriptor = ArtifactDescriptor(
            media_type="application/json",
            schema_ref=SchemaRef(namespace=schema_namespace, name=schema_name, version=schema_version),
            sensitivity=sensitivity,
            retention=retention,
        )
        return self.put(canonical_json_bytes(payload), descriptor)

    def put_text(
        self,
        text: str,
        *,
        schema_namespace: str = "document",
        schema_name: str = "source_text",
    ) -> ArtifactRef:
        """Store plain text under the schema the review inputs expect."""
        descriptor = ArtifactDescriptor(
            media_type="text/plain",
            schema_ref=SchemaRef(namespace=schema_namespace, name=schema_name, version=1),
            sensitivity=ArtifactSensitivity.INTERNAL,
            retention=ArtifactRetention.STANDARD,
        )
        return self.put(text.encode(), descriptor)

    def read(self, ref: ArtifactRef) -> bytes:
        """Return stored bytes or raise ``KeyError`` when the artifact is unknown."""
        try:
            return self._content[ref.artifact_id.value]
        except KeyError as exc:
            msg = f"artifact {ref.artifact_id.value} is not stored"
            raise KeyError(msg) from exc

    def verify(self, ref: ArtifactRef) -> ArtifactVerification:
        """Recompute the digest and report whether the artifact is intact."""
        content = self._content.get(ref.artifact_id.value)
        if content is None:
            return ArtifactVerification(
                artifact=ref,
                status=ArtifactVerificationStatus.MISSING,
                reason="artifact is not stored",
            )
        actual = ContentDigest.from_bytes(content)
        if actual != ref.digest:
            return ArtifactVerification(
                artifact=ref,
                status=ArtifactVerificationStatus.CORRUPT,
                actual_digest=actual,
                reason="content digest mismatch",
            )
        return ArtifactVerification(
            artifact=ref,
            status=ArtifactVerificationStatus.VERIFIED,
            actual_digest=actual,
        )
