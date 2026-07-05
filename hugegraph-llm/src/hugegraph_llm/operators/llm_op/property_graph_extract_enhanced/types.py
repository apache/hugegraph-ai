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

"""Shared data structures for the enhanced graph extraction quality layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class CandidateGraph:
    """Chunk-level candidate graph produced by ``CandidateGraphParser``.

    The candidate graph is intentionally schema-agnostic — items are handed on
    to the schema-aware normalizer in whatever shape the LLM produced them.
    The parser guarantees only that:

    * ``vertices`` and ``edges`` are lists (possibly empty);
    * every element is a ``dict`` (non-dict candidates are dropped by the
      parser with an ``ITEM_NOT_OBJECT`` warning);
    * items with an explicit ``type`` field agree with the array they live in
      (mismatches are dropped with ``ITEM_TYPE_MISMATCH``).

    The dataclass is frozen so a consumer cannot rebind the ``vertices``/
    ``edges`` lists, but the lists themselves are ordinary mutable lists that
    downstream stages read but do not modify in place.
    """

    vertices: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.vertices and not self.edges


# Pending-endpoint marker keys used on normalized edges. They live under a
# leading underscore so JSON serialization at the API boundary can strip them
# without special casing individual fields.
PENDING_OUT_KEY = "_pending_out"
PENDING_IN_KEY = "_pending_in"


@dataclass(frozen=True)
class NormalizedChunkGraph:
    """Chunk-level schema-normalized graph produced by ``SchemaAwareNormalizer``.

    Vertices are schema-valid and have canonical ids when the schema permits;
    otherwise the LLM-provided id (or none) is kept for baseline-compatible
    fallback. Edges either have both endpoints resolved to canonical ids
    (ready to emit) or carry ``PENDING_OUT_KEY`` / ``PENDING_IN_KEY`` hints
    describing what the document-level assembler can still try. Edges whose
    endpoints have already been ruled out by the schema are dropped by the
    normalizer and never appear here.

    ``aliases`` maps ``(label, llm_original_id)`` → ``canonical_id`` for every
    vertex whose LLM-generated id differed from the canonical one. The
    assembler unions these tables across chunks to service the third-tier
    ``explicit_id_alias`` endpoint repair pass.
    """

    vertices: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    aliases: Dict[Tuple[str, str], str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.vertices and not self.edges
