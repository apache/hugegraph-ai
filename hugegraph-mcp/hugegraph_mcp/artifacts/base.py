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

"""Abstract ArtifactStore interface and exception types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from hugegraph_mcp.artifact_models import ArtifactManifest, ArtifactPart


class ArtifactNotFoundError(FileNotFoundError):
    """Raised when an artifact or part does not exist or has expired."""


class ArtifactAccessError(PermissionError):
    """Raised when an actor/tenant is not authorized to access an artifact."""


class ArtifactIntegrityError(ValueError):
    """Raised when an artifact fails SHA-256 verification."""


class ArtifactStore(ABC):
    @abstractmethod
    def put(
        self,
        payload: bytes | str,
        *,
        owner_key: str,
        tenant: str,
        target_graph: dict[str, Any],
        kind: str,
        media_type: str = "application/json",
        schema_fingerprint: str | None = None,
        request_id: str | None = None,
        ttl_seconds: float = 3600.0,
        part_size_bytes: int = 65_536,
    ) -> ArtifactManifest:
        """Persist an immutable artifact split into bounded parts."""

    @abstractmethod
    def get_manifest(self, artifact_id: str, *, owner_key: str) -> ArtifactManifest:
        """Load and authorize the artifact manifest."""

    @abstractmethod
    def read_part(self, artifact_id: str, part_id: int, *, owner_key: str) -> ArtifactPart:
        """Read and verify one bounded part of an artifact."""

    @abstractmethod
    def read_all(self, artifact_id: str, *, owner_key: str) -> bytes:
        """Reassemble and SHA-256 verify the full artifact payload."""

    @abstractmethod
    def pin(self, artifact_id: str, *, owner_key: str) -> ArtifactManifest:
        """Pin an artifact so TTL cleanup preserves it for pending review/plans."""
