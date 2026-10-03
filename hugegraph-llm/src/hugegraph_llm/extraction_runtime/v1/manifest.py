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

"""Domain semantic resource manifest contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

from hugegraph_llm.extraction_runtime.v1.json_value import (
    JsonObject,
    digest_json,
    ensure_stable_provenance,
    freeze_json_object,
)


@dataclass(frozen=True)
class SemanticResourceV1:
    name: str
    content_digest: str
    media_type: str = "text/plain"

    @classmethod
    def from_text(cls, name: str, content: str, *, media_type: str = "text/plain") -> SemanticResourceV1:
        encoded = content.encode("utf-8")
        return cls(name=name, content_digest=f"sha256:{hashlib.sha256(encoded).hexdigest()}", media_type=media_type)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("semantic resource name must not be empty")
        if not self.content_digest.startswith("sha256:"):
            raise ValueError("semantic resource digest must use sha256")


@dataclass(frozen=True)
class DomainSemanticManifestV1:
    bundle_id: str
    bundle_version: str
    resources: tuple[SemanticResourceV1, ...]
    semantics: JsonObject = field(default_factory=dict)
    contract: Literal["domain-semantic-manifest/v1"] = "domain-semantic-manifest/v1"

    def __post_init__(self) -> None:
        if not self.bundle_id:
            raise ValueError("bundle_id must not be empty")
        if not self.bundle_version:
            raise ValueError("bundle_version must not be empty")
        if len({resource.name for resource in self.resources}) != len(self.resources):
            raise ValueError("semantic resource names must be unique")
        semantics = freeze_json_object(self.semantics)
        ensure_stable_provenance(semantics, path="$.semantics")
        object.__setattr__(self, "semantics", semantics)

    def as_digest_input(self) -> JsonObject:
        return freeze_json_object(
            {
                "contract": self.contract,
                "bundle_id": self.bundle_id,
                "bundle_version": self.bundle_version,
                "resources": [
                    {
                        "name": resource.name,
                        "content_digest": resource.content_digest,
                        "media_type": resource.media_type,
                    }
                    for resource in sorted(self.resources, key=lambda item: item.name)
                ],
                "semantics": self.semantics,
            }
        )

    @property
    def domain_semantic_digest(self) -> str:
        return digest_json(self.as_digest_input())
