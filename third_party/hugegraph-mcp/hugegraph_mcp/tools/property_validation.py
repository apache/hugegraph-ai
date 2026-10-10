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

"""Shared validation for JSON property values against HugeGraph schema."""

import base64
import binascii
import math
from datetime import datetime
from typing import Any
from uuid import UUID

from hugegraph_mcp.tools.schema_utils import normalized_schema_summary

PropertySpec = tuple[str, str]

DATA_TYPE_ALIASES = {
    "BOOL": "BOOLEAN",
    "INTEGER": "INT",
    "STRING": "TEXT",
}
SUPPORTED_DATA_TYPES = frozenset(
    {
        "TEXT",
        "UUID",
        "INT",
        "LONG",
        "DOUBLE",
        "FLOAT",
        "BOOLEAN",
        "DATE",
        "BYTE",
        "BLOB",
        "OBJECT",
    }
)
SUPPORTED_CARDINALITIES = frozenset({"SINGLE", "LIST", "SET"})

_INTEGER_RANGES = {
    "BYTE": (-(2**7), 2**7 - 1),
    "INT": (-(2**31), 2**31 - 1),
    "LONG": (-(2**63), 2**63 - 1),
}

# HugeGraph FLOAT and DOUBLE map to IEEE-754 binary32 and binary64 values.
# Keep the bounds as exactly representable Python floats, and compare integers
# directly so arbitrary-precision JSON integers never need a lossy conversion.
_FLOATING_MAXIMUMS = {
    "FLOAT": float.fromhex("0x1.fffffep+127"),
    "DOUBLE": float.fromhex("0x1.fffffffffffffp+1023"),
}


def property_specs(live_schema: dict[str, Any]) -> dict[str, PropertySpec]:
    """Return normalized ``name -> (data type, cardinality)`` schema entries."""

    specs: dict[str, PropertySpec] = {}
    normalized_schema = normalized_schema_summary(live_schema) or {}
    for prop in normalized_schema.get("propertykeys", []):
        if not isinstance(prop, dict):
            continue
        name = prop.get("name")
        data_type = prop.get("data_type")
        if not isinstance(name, str) or not isinstance(data_type, str):
            continue
        normalized_type = data_type.strip().upper()
        specs[name] = (
            DATA_TYPE_ALIASES.get(normalized_type, normalized_type),
            str(prop.get("cardinality") or "SINGLE").strip().upper(),
        )
    return specs


def property_value_error(
    *,
    item_kind: str,
    item_index: int,
    property_name: str,
    value: Any,
    spec: PropertySpec | None,
) -> str | None:
    """Return a stable validation message, or ``None`` for a valid value.

    ``None`` retains the existing import contract: required/nullable-property
    policy is owned by label validation and HugeGraph, not guessed here.
    Collection elements remain non-null because HugeGraph cannot store a null
    property value inside LIST/SET cardinalities.
    """

    if spec is None:
        return None

    data_type, cardinality = spec
    prefix = f"{item_kind} {item_index} property '{property_name}'"
    if data_type not in SUPPORTED_DATA_TYPES:
        return f"{prefix} unsupported data_type '{data_type}'"
    if cardinality not in SUPPORTED_CARDINALITIES:
        return f"{prefix} unsupported cardinality '{cardinality}'"
    if cardinality in {"LIST", "SET"}:
        if value is None:
            return None
        if not isinstance(value, list):
            return f"{prefix} expects {cardinality} of {data_type}, got {type(value).__name__}"
        for element_index, element in enumerate(value):
            if element is None or not value_matches_type(element, data_type):
                return f"{prefix} element {element_index} expects {data_type}, got {type(element).__name__}"
        return None

    if not value_matches_type(value, data_type):
        return f"{prefix} expects {data_type}, got {type(value).__name__}"
    return None


def value_matches_type(value: Any, data_type: str) -> bool:
    """Check whether a JSON-compatible value can be stored by HugeGraph."""

    if value is None:
        return True
    if data_type == "TEXT":
        return isinstance(value, str)
    if data_type in _INTEGER_RANGES:
        if not isinstance(value, int) or isinstance(value, bool):
            return False
        minimum, maximum = _INTEGER_RANGES[data_type]
        return minimum <= value <= maximum
    if data_type in {"FLOAT", "DOUBLE"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        maximum = _FLOATING_MAXIMUMS[data_type]
        if isinstance(value, int):
            return -maximum <= value <= maximum
        return math.isfinite(value) and -maximum <= value <= maximum
    if data_type == "BOOLEAN":
        return isinstance(value, bool)
    if data_type == "UUID":
        return _is_uuid(value)
    if data_type == "DATE":
        return _is_date(value)
    if data_type == "BLOB":
        return _is_blob(value)
    if data_type == "OBJECT":
        return isinstance(value, dict)
    return False


def _is_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except (ValueError, AttributeError):
        return False
    return True


def _is_date(value: Any) -> bool:
    if isinstance(value, int) and not isinstance(value, bool):
        return -(2**63) <= value <= 2**63 - 1
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return True


def _is_blob(value: Any) -> bool:
    if isinstance(value, str):
        if value.startswith("0x"):
            try:
                bytes.fromhex(value[2:])
            except ValueError:
                return False
            return True
        try:
            base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            return False
        return True
    if isinstance(value, list):
        return all(
            isinstance(element, int) and not isinstance(element, bool) and -128 <= element <= 255 for element in value
        )
    return False
