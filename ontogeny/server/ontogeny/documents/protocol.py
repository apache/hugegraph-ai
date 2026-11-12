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

"""The extractor capability contract.

The core never imports an extractor implementation: an extension registers a
factory on ``sc.document_extractor_factory`` (same pattern as the graph store).
Everything crossing the boundary is plain JSON-able data, so the adapter can be
in-process today and a subprocess tomorrow without touching the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class DocInput:
    """One document handed to an extractor.

    Text files carry ``text``; binary files (PDF/DOCX) carry ``content_b64`` so
    an external agent can parse them itself -- the platform does not take a
    parser dependency just to feed the extractor.
    """

    doc_id: str
    path: str
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    name: str = ""
    media_type: str | None = None
    content_b64: str | None = None


@dataclass
class ExtractOptions:
    #: hints for the external agent; it owns chunking and prompting
    split: str = "paragraph"
    language: str = "zh"
    max_chunks_per_doc: int = 200
    instructions: str | None = None


@dataclass
class ExtractRequest:
    schema: dict[str, Any]
    docs: list[DocInput]
    options: ExtractOptions


@dataclass
class ChunkResult:
    """One chunk's extraction, with the original text kept for the review UI."""

    doc_id: str
    index: int
    text: str
    graph: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    status: str = "final"  # final | candidate | blocked | failed
    reason: str | None = None


@runtime_checkable
class DocumentExtractor(Protocol):
    async def extract(self, request: ExtractRequest) -> list[ChunkResult]: ...

    async def read(self, path: Path) -> str: ...

    async def health(self) -> dict[str, Any]: ...
