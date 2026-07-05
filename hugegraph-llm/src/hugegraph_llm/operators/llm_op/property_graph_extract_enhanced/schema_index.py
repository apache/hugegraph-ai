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

"""Runtime schema index for the enhanced graph extraction strategy.

``GraphSchemaIndex`` compiles a HugeGraph schema (already validated by
``CheckSchema`` or fetched via ``SchemaManager``) into fast lookups used by the
schema-aware quality layer. It performs no HugeGraph I/O and does not modify the
input schema.
"""

from __future__ import annotations

import json
import re
from typing import Any, FrozenSet, List, Mapping, Optional, Tuple, Union

_INT_TYPES = frozenset({"INT", "LONG", "BYTE"})
_FLOAT_TYPES = frozenset({"FLOAT", "DOUBLE"})
_TEXT_TYPES = frozenset({"TEXT", "UUID", "BLOB"})

_BOOL_TRUE = frozenset({"true", "yes", "1"})
_BOOL_FALSE = frozenset({"false", "no", "0"})

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class GraphSchemaIndex:
    """Immutable lookup over a HugeGraph property-graph schema.

    Callers pass a schema object (already parsed) or a JSON string. Constructor
    validates only the outer envelope shape; deeper validation belongs to
    ``CheckSchema`` upstream.
    """

    def __init__(self, schema: Mapping[str, Any]) -> None:
        if not isinstance(schema, Mapping):
            raise TypeError("schema must be a mapping (dict-like).")
        if "vertexlabels" not in schema or "edgelabels" not in schema:
            raise ValueError("schema must contain 'vertexlabels' and 'edgelabels'.")

        self._raw: Mapping[str, Any] = schema
        self._vertex_labels: dict[str, Mapping[str, Any]] = {
            v["name"]: v for v in schema["vertexlabels"] if isinstance(v, Mapping) and "name" in v
        }
        self._edge_labels: dict[str, Mapping[str, Any]] = {
            e["name"]: e for e in schema["edgelabels"] if isinstance(e, Mapping) and "name" in e
        }
        self._property_keys: dict[str, Mapping[str, Any]] = {
            p["name"]: p for p in schema.get("propertykeys", []) if isinstance(p, Mapping) and "name" in p
        }

    @classmethod
    def from_schema(cls, schema: Union[str, Mapping[str, Any]]) -> "GraphSchemaIndex":
        """Build an index from either a dict schema or a JSON-string schema.

        Named-graph strings (schema names without a leading '{') are not accepted:
        callers must fetch the concrete schema first (see ``SchemaNode``).
        """
        if isinstance(schema, str):
            trimmed = schema.strip()
            if not trimmed.startswith("{"):
                raise ValueError(
                    "GraphSchemaIndex.from_schema does not resolve named graphs; "
                    "hand in the fetched schema object or JSON string."
                )
            try:
                parsed = json.loads(trimmed)
            except json.JSONDecodeError as exc:
                raise ValueError(f"schema JSON is not parseable: {exc}") from exc
            return cls(parsed)
        return cls(schema)

    # ------------------------------------------------------------------ labels
    def is_vertex_label(self, label: str) -> bool:
        return label in self._vertex_labels

    def is_edge_label(self, label: str) -> bool:
        return label in self._edge_labels

    def vertex_label(self, label: str) -> Optional[Mapping[str, Any]]:
        return self._vertex_labels.get(label)

    def edge_label(self, label: str) -> Optional[Mapping[str, Any]]:
        return self._edge_labels.get(label)

    def vertex_label_names(self) -> FrozenSet[str]:
        return frozenset(self._vertex_labels)

    def edge_label_names(self) -> FrozenSet[str]:
        return frozenset(self._edge_labels)

    # -------------------------------------------------------------- properties
    def is_property_key(self, key: str) -> bool:
        return key in self._property_keys

    def property_data_type(self, key: str) -> str:
        pk = self._property_keys.get(key)
        if pk is None:
            return "TEXT"
        return str(pk.get("data_type", "TEXT")).upper()

    def property_cardinality(self, key: str) -> str:
        pk = self._property_keys.get(key)
        if pk is None:
            return "SINGLE"
        return str(pk.get("cardinality", "SINGLE")).upper()

    def allowed_properties(self, item_type: str, label: str) -> FrozenSet[str]:
        """Return the set of property keys a given vertex/edge label may carry."""
        if item_type == "vertex":
            v = self._vertex_labels.get(label)
            if v is None:
                return frozenset()
            return frozenset(v.get("properties", []) or [])
        if item_type == "edge":
            e = self._edge_labels.get(label)
            if e is None:
                return frozenset()
            return frozenset(e.get("properties", []) or [])
        return frozenset()

    # --------------------------------------------------------- primary key id
    def primary_keys(self, vertex_label: str) -> Tuple[str, ...]:
        v = self._vertex_labels.get(vertex_label)
        if v is None:
            return ()
        pks = v.get("primary_keys") or ()
        return tuple(pks)

    def canonical_vertex_id(self, label: str, properties: Mapping[str, Any]) -> Optional[str]:
        """Compute the canonical id ``{vertex_label.id}:{pk1}!{pk2}`` for a vertex.

        Returns ``None`` when the canonical rule cannot apply. This mirrors the
        baseline behavior in ``PropertyGraphExtract._primary_key_id`` — callers
        fall back to the LLM-provided raw id in that case. Preconditions:

        * ``vertex_label.id_strategy`` is ``PRIMARY_KEY`` (or absent, treated as
          PRIMARY_KEY);
        * ``vertex_label.id`` is present in the schema entry (HugeGraph server
          populates this; inline user schemas may not);
        * every primary key resolves to a non-empty property value in the input.
        """
        v = self._vertex_labels.get(label)
        if v is None:
            return None
        id_strategy = v.get("id_strategy")
        if id_strategy and str(id_strategy).upper() != "PRIMARY_KEY":
            return None
        if "id" not in v:
            return None
        pks = v.get("primary_keys") or ()
        if not pks:
            return None
        values: List[str] = []
        for key in pks:
            value = properties.get(key)
            if value is None or value == "":
                return None
            values.append(str(value))
        return f"{v['id']}:{'!'.join(values)}"

    # ---------------------------------------------------------------- edges
    def edge_endpoint_spec(self, edge_label: str) -> Optional[Tuple[str, str]]:
        """Return ``(source_label, target_label)`` for a schema edge, or None."""
        e = self._edge_labels.get(edge_label)
        if e is None:
            return None
        source = e.get("source_label")
        target = e.get("target_label")
        if not isinstance(source, str) or not isinstance(target, str):
            return None
        return source, target

    def is_endpoint_compatible(self, edge_label: str, out_label: str, in_label: str) -> bool:
        spec = self.edge_endpoint_spec(edge_label)
        if spec is None:
            return False
        return spec == (out_label, in_label)

    # ------------------------------------------------------------- coercion
    def coerce_property_value(self, key: str, value: Any) -> Tuple[Any, Optional[str]]:
        """Best-effort safe conversion of ``value`` to the schema's declared type.

        Returns ``(coerced_value, warning_reason)``. ``warning_reason`` is
        ``None`` on clean success. Failures return ``(None, reason)``. For LIST
        and SET cardinalities, partial success returns the surviving elements
        plus a summary reason listing the dropped ones.

        Design notes:

        * INT/LONG/BYTE never accept booleans or lossy floats; DATE accepts only
          ``YYYY-MM-DD`` (no fuzzy parsing) — see design doc §6.4.
        * BLOB is treated as TEXT-like passthrough (unspecified in the design
          doc, kept forgiving so downstream commit-to-graph handles the actual
          bytes-vs-text boundary).
        """
        cardinality = self.property_cardinality(key)
        if cardinality in ("LIST", "SET"):
            if not isinstance(value, list):
                return (
                    None,
                    f"property '{key}' expects a list for {cardinality} cardinality, got {type(value).__name__}",
                )
            coerced: List[Any] = []
            dropped: List[str] = []
            for idx, item in enumerate(value):
                item_coerced, item_reason = self._coerce_scalar(key, item)
                if item_reason is not None:
                    dropped.append(f"[{idx}]: {item_reason}")
                    continue
                coerced.append(item_coerced)
            if cardinality == "SET":
                seen: List[Any] = []
                for item in coerced:
                    if item not in seen:
                        seen.append(item)
                coerced = seen
            if dropped:
                return coerced, f"property '{key}' dropped {len(dropped)} items: {'; '.join(dropped)}"
            return coerced, None
        return self._coerce_scalar(key, value)

    def _coerce_scalar(self, key: str, value: Any) -> Tuple[Any, Optional[str]]:
        data_type = self.property_data_type(key)
        if value is None:
            return None, f"property '{key}' value is None"

        if data_type in _TEXT_TYPES:
            if isinstance(value, str):
                return value, None
            if isinstance(value, bool):
                # str(True) → "True" is rarely what an integrator wants; keep it
                # explicit rather than silently converting.
                return str(value), None
            try:
                return str(value), None
            except Exception as exc:  # pragma: no cover - defensive
                return None, f"property '{key}' failed to stringify: {exc}"

        if data_type in _INT_TYPES:
            if isinstance(value, bool):
                return None, f"property '{key}' bool cannot be coerced to {data_type}"
            if isinstance(value, int):
                return value, None
            if isinstance(value, float):
                if value.is_integer():
                    return int(value), None
                return None, f"property '{key}' float {value} is not a lossless {data_type}"
            if isinstance(value, str):
                stripped = value.strip()
                try:
                    return int(stripped), None
                except ValueError:
                    return None, f"property '{key}' string '{value}' is not a {data_type}"
            return None, f"property '{key}' cannot coerce {type(value).__name__} to {data_type}"

        if data_type in _FLOAT_TYPES:
            if isinstance(value, bool):
                return None, f"property '{key}' bool cannot be coerced to {data_type}"
            if isinstance(value, (int, float)):
                return float(value), None
            if isinstance(value, str):
                try:
                    return float(value.strip()), None
                except ValueError:
                    return None, f"property '{key}' string '{value}' is not a {data_type}"
            return None, f"property '{key}' cannot coerce {type(value).__name__} to {data_type}"

        if data_type == "BOOLEAN":
            if isinstance(value, bool):
                return value, None
            if isinstance(value, int) and value in (0, 1):
                return bool(value), None
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in _BOOL_TRUE:
                    return True, None
                if lowered in _BOOL_FALSE:
                    return False, None
            return None, f"property '{key}' value {value!r} is not a BOOLEAN"

        if data_type == "DATE":
            if isinstance(value, str) and _DATE_RE.match(value.strip()):
                return value.strip(), None
            return None, f"property '{key}' value {value!r} is not a YYYY-MM-DD DATE"

        # Unknown type — pass through as-is with a soft warning so the writer can decide.
        return value, f"property '{key}' has unrecognized data_type {data_type!r}; passing through"
