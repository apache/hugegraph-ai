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
from typing import Any, Dict, List


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
