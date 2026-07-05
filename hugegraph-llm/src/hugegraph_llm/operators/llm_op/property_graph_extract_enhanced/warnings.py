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

"""Structured warning types for the enhanced graph extraction strategy.

The enhanced strategy attaches a structured warning to every deviation from the
schema-clean happy path (a dropped item, a coerced value, a merged duplicate,
an unresolvable endpoint). These warnings surface in ``meta.structured_warnings``
alongside the resulting graph and drive both the effect report and downstream
debugging.

A ``WarningCode`` is a ``str, Enum`` so it JSON-serializes as its bare code name
(``"ENDPOINT_UNRESOLVED"``) without needing custom encoders. ``StructuredWarning``
is a frozen dataclass, cheap to hash and deduplicate.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Optional


class WarningCode(str, Enum):
    """Stable identifiers for every warning the enhanced strategy may emit.

    Codes are grouped by their producer to make the surface easy to audit.
    A single code may originate from multiple producers when the semantic
    ("this property does not belong to the label") is the same regardless of
    caller.
    """

    # -- Candidate parser (raw LLM output → chunk-level candidate graph) ------
    JSON_NOT_FOUND = "JSON_NOT_FOUND"
    JSON_DECODE_FAILED = "JSON_DECODE_FAILED"
    GRAPH_SECTION_MISSING = "GRAPH_SECTION_MISSING"
    ITEM_NOT_OBJECT = "ITEM_NOT_OBJECT"
    ITEM_TYPE_MISMATCH = "ITEM_TYPE_MISMATCH"

    # -- Schema-aware normalizer, vertex ---------------------------------------
    VERTEX_LABEL_NOT_IN_SCHEMA = "VERTEX_LABEL_NOT_IN_SCHEMA"
    VERTEX_PRIMARY_KEY_MISSING = "VERTEX_PRIMARY_KEY_MISSING"
    VERTEX_PRIMARY_KEY_INVALID = "VERTEX_PRIMARY_KEY_INVALID"
    VERTEX_ALIAS_RECORDED = "VERTEX_ALIAS_RECORDED"

    # -- Schema-aware normalizer, edge -----------------------------------------
    EDGE_LABEL_NOT_IN_SCHEMA = "EDGE_LABEL_NOT_IN_SCHEMA"
    EDGE_ENDPOINT_MISMATCH = "EDGE_ENDPOINT_MISMATCH"

    # -- Property handling (vertex or edge) ------------------------------------
    PROPERTY_NOT_IN_SCHEMA = "PROPERTY_NOT_IN_SCHEMA"
    PROPERTY_COERCED = "PROPERTY_COERCED"
    PROPERTY_COERCION_FAILED = "PROPERTY_COERCION_FAILED"

    # -- Document-level assembler (cross-chunk repair and merge) ---------------
    ENDPOINT_PENDING_REPAIR = "ENDPOINT_PENDING_REPAIR"
    ENDPOINT_UNRESOLVED = "ENDPOINT_UNRESOLVED"
    ENDPOINT_AMBIGUOUS = "ENDPOINT_AMBIGUOUS"
    DUPLICATE_VERTEX_MERGED = "DUPLICATE_VERTEX_MERGED"
    DUPLICATE_EDGE_MERGED = "DUPLICATE_EDGE_MERGED"
    PROPERTY_CONFLICT = "PROPERTY_CONFLICT"


# Warnings that materially changed the emitted graph — reader should expect
# a dropped item, a coerced value, or a merged duplicate. Non-affecting
# warnings (e.g. VERTEX_ALIAS_RECORDED) are recorded for observability but do
# not cause the reader to lose or gain output items.
_SURFACE_AFFECTING = frozenset(
    {
        WarningCode.JSON_NOT_FOUND,
        WarningCode.JSON_DECODE_FAILED,
        WarningCode.ITEM_NOT_OBJECT,
        WarningCode.ITEM_TYPE_MISMATCH,
        WarningCode.VERTEX_LABEL_NOT_IN_SCHEMA,
        WarningCode.VERTEX_PRIMARY_KEY_MISSING,
        WarningCode.VERTEX_PRIMARY_KEY_INVALID,
        WarningCode.EDGE_LABEL_NOT_IN_SCHEMA,
        WarningCode.EDGE_ENDPOINT_MISMATCH,
        WarningCode.PROPERTY_NOT_IN_SCHEMA,
        WarningCode.PROPERTY_COERCED,
        WarningCode.PROPERTY_COERCION_FAILED,
        WarningCode.ENDPOINT_UNRESOLVED,
        WarningCode.ENDPOINT_AMBIGUOUS,
        WarningCode.DUPLICATE_VERTEX_MERGED,
        WarningCode.DUPLICATE_EDGE_MERGED,
    }
)

_ITEM_TYPES = frozenset({"graph", "vertex", "edge"})


@dataclass(frozen=True)
class StructuredWarning:
    """A single, immutable warning produced by the enhanced strategy.

    Attributes:
        code: The stable ``WarningCode`` identifying the reason.
        item_type: ``"graph"``, ``"vertex"``, or ``"edge"``. ``"graph"`` covers
            parser-level issues that are not attributable to a specific item.
        reason: A short human-readable explanation. Format is not stable —
            consumers should key off ``code`` for programmatic decisions.
        label: The vertex or edge label the warning refers to, when known.
        chunk_id: The chunk index (0-based) the warning originated from, when
            the warning is attributable to a single chunk.
        strategy: The extract strategy that produced the warning. Currently
            always ``"enhanced"`` since baseline emits no structured warnings,
            but kept explicit so future strategies can share the same envelope.
        context: Optional free-form metadata (e.g. the offending property key)
            that a debug consumer may find useful. Must be JSON-serializable.
    """

    code: WarningCode
    item_type: str
    reason: str
    label: Optional[str] = None
    chunk_id: Optional[int] = None
    strategy: str = "enhanced"
    context: Optional[Mapping[str, Any]] = field(default=None)

    def __post_init__(self) -> None:
        # Accept raw string codes so callers can write
        # StructuredWarning(code="JSON_NOT_FOUND", ...) without importing the enum.
        if not isinstance(self.code, WarningCode):
            object.__setattr__(self, "code", WarningCode(self.code))
        if self.item_type not in _ITEM_TYPES:
            raise ValueError(
                f"StructuredWarning.item_type must be one of {sorted(_ITEM_TYPES)}, got {self.item_type!r}"
            )
        if self.chunk_id is not None and self.chunk_id < 0:
            raise ValueError(f"StructuredWarning.chunk_id must be non-negative, got {self.chunk_id}")
        if self.context is not None:
            # Freeze the context so the dataclass stays truly immutable and
            # dedup/hashing works via to_hashable_tuple below.
            object.__setattr__(self, "context", dict(self.context))

    @property
    def is_surface_affecting(self) -> bool:
        """Whether this warning represents a material change to the emitted graph."""
        return self.code in _SURFACE_AFFECTING

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dict for ``meta.structured_warnings``.

        Fields with a value of ``None`` are omitted so the response stays
        compact. ``context`` is copied so downstream mutation cannot leak
        back into the frozen warning.
        """
        out: Dict[str, Any] = {
            "code": self.code.value,
            "item_type": self.item_type,
            "reason": self.reason,
            "strategy": self.strategy,
        }
        if self.label is not None:
            out["label"] = self.label
        if self.chunk_id is not None:
            out["chunk_id"] = self.chunk_id
        if self.context:
            out["context"] = dict(self.context)
        return out


def warning_code_distribution(warnings: Iterable[StructuredWarning]) -> Dict[str, int]:
    """Aggregate a warning list into a ``code_name -> count`` histogram.

    Used by the effect report and the ``meta.debug_info.warning_code_distribution``
    field. Non-``StructuredWarning`` entries are silently skipped rather than
    raising — the effect report should never fail because of a malformed entry
    at the very end of a long pipeline.
    """
    counter: Counter[str] = Counter()
    for w in warnings:
        if isinstance(w, StructuredWarning):
            counter[w.code.value] += 1
    return dict(counter)
