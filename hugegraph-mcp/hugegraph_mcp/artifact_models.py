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

"""Models for immutable, owner-bound MCP artifact manifests and bounded parts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ArtifactManifest:
    artifact_id: str
    owner_key: str
    tenant: str
    target_graph: dict[str, Any]
    kind: str
    media_type: str
    sha256: str
    size_bytes: int
    part_count: int
    part_size_bytes: int
    created_at: float
    expires_at: float
    pinned: bool = False
    schema_fingerprint: str | None = None
    request_id: str | None = None
    part_sha256s: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["part_sha256s"] = list(self.part_sha256s)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactManifest:
        normalized = dict(data)
        if "part_sha256s" in normalized and normalized["part_sha256s"] is not None:
            normalized["part_sha256s"] = tuple(normalized["part_sha256s"])
        return cls(**normalized)


@dataclass(frozen=True)
class ArtifactPart:
    artifact_id: str
    part_id: int
    content: str
    sha256: str
    size_bytes: int
