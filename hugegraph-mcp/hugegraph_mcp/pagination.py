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

"""Byte-budgeted page packing for MCP read responses."""

from __future__ import annotations

import json
from typing import Any


class ItemTooLargeError(ValueError):
    """Raised when a single item cannot fit within the response byte budget."""


def serialized_utf8_bytes(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def pack_paginated_items(
    items: list[Any],
    *,
    max_items: int,
    max_bytes: int,
    overhead_bytes: int = 512,
) -> tuple[list[Any], list[Any], bool]:
    """Pack up to ``max_items`` within ``max_bytes`` UTF-8 JSON budget.

    Returns ``(packed_items, overflow_items, byte_truncated)``.
    """

    if not items:
        return [], [], False

    budget = max(1, max_bytes - overhead_bytes)
    packed: list[Any] = []
    running_bytes = 2  # JSON array brackets "[]"
    byte_truncated = False

    for index, item in enumerate(items):
        if len(packed) >= max_items:
            return packed, items[index:], byte_truncated
        item_bytes = serialized_utf8_bytes(item) + (1 if packed else 0)
        if running_bytes + item_bytes > budget:
            if not packed:
                raise ItemTooLargeError(
                    f"Single result item ({item_bytes} bytes) exceeds response budget ({budget} bytes)."
                )
            byte_truncated = True
            return packed, items[index:], byte_truncated
        packed.append(item)
        running_bytes += item_bytes

    return packed, [], False
