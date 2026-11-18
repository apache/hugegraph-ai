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

"""Bounded public schema snapshot helpers (separate from full internal validation)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

SCHEMA_COLLECTIONS = ("propertykeys", "vertexlabels", "edgelabels", "indexlabels")
DEFAULT_SCHEMA_MAX_ITEMS = 200
DEFAULT_SCHEMA_MAX_BYTES = 262_144


def compute_schema_fingerprint(schema_payload: Mapping[str, Any]) -> str:
    """Compute a deterministic SHA-256 fingerprint for a HugeGraph schema payload."""
    canonical = json.dumps(
        schema_payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sort_key(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("name", ""))
    return str(item)


def bound_schema_payload(
    raw_payload: Mapping[str, Any],
    *,
    max_items: int = DEFAULT_SCHEMA_MAX_ITEMS,
    max_bytes: int = DEFAULT_SCHEMA_MAX_BYTES,
) -> tuple[dict[str, Any], bool, str | None]:
    """Return a deterministic, item- and byte-bounded view of a raw schema payload."""

    bounded: dict[str, Any] = {}
    remaining_items = max(1, int(max_items))
    truncated = False
    reason: str | None = None

    for key in SCHEMA_COLLECTIONS:
        items = raw_payload.get(key)
        if not isinstance(items, list):
            continue
        sorted_items = sorted(items, key=_sort_key)
        kept: list[Any] = []
        for entry in sorted_items:
            if remaining_items <= 0:
                truncated = True
                reason = reason or "max_items_exceeded"
                break
            candidate = dict(bounded)
            candidate[key] = [*kept, entry]
            encoded_len = len(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if encoded_len > max_bytes:
                truncated = True
                reason = reason or "max_bytes_exceeded"
                break
            kept.append(entry)
            remaining_items -= 1
        bounded[key] = kept

    return bounded, truncated, reason
