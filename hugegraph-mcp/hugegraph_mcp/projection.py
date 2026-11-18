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

"""Field projection helpers for bounded MCP graph read responses."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

MAX_PROJECTED_FIELDS = 50
_IDENTITY_FIELDS = ("id", "label", "type", "outV", "inV", "outVLabel", "inVLabel")


def validate_fields(fields: Iterable[str] | None) -> tuple[str, ...] | None:
    """Validate and normalize a requested field projection list."""

    if fields is None:
        return None
    if isinstance(fields, str | bytes):
        raise ValueError("fields must be a list of field names, not a string.")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in fields:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("Each projected field must be a non-empty string.")
        field_name = raw.strip()
        if ".." in field_name or field_name.startswith(".") or field_name.endswith(".") or len(field_name) > 128:
            raise ValueError(f"Invalid projected field name: {field_name!r}")
        if field_name not in seen:
            seen.add(field_name)
            normalized.append(field_name)
    if len(normalized) > MAX_PROJECTED_FIELDS:
        raise ValueError(f"Projected fields exceed maximum of {MAX_PROJECTED_FIELDS}.")
    return tuple(normalized)


def project_element(item: Any, fields: tuple[str, ...] | None) -> Any:
    """Project a graph element while preserving identity fields."""

    if fields is None or not isinstance(item, Mapping):
        return item

    projected: dict[str, Any] = {}
    for key in _IDENTITY_FIELDS:
        if key in item:
            projected[key] = item[key]

    props = item.get("properties")
    has_props_dict = isinstance(props, Mapping)
    projected_props: dict[str, Any] = {}
    include_all_props = False

    for field_name in fields:
        if field_name in ("properties", "properties.*") and has_props_dict:
            include_all_props = True
            continue
        if has_props_dict and field_name in props:
            projected_props[field_name] = props[field_name]
            continue
        if field_name.startswith("properties.") and has_props_dict:
            prop_key = field_name[len("properties.") :]
            if prop_key in props:
                projected_props[prop_key] = props[prop_key]
            continue
        if field_name in item and field_name != "properties":
            projected[field_name] = item[field_name]

    if include_all_props and has_props_dict:
        projected["properties"] = dict(props)
    elif projected_props:
        projected["properties"] = projected_props

    return projected


def project_items(items: list[Any], fields: tuple[str, ...] | None) -> list[Any]:
    """Apply ``project_element`` to every element in ``items``."""

    if fields is None:
        return items
    return [project_element(item, fields) for item in items]
