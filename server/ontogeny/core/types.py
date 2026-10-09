# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Property type system: parse DSL type strings, coerce raw values, map to SQL.

Supported (dsl-spec §3): string, integer, decimal(p,s), boolean, date,
timestamp, enum[A, B], geo-point, geo-shape, vector(d), media, document,
array(T), struct{...}.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any

from ..errors import TypeMismatchError

_SIMPLE = {
    "string", "integer", "decimal", "boolean", "date", "timestamp",
    "geo-point", "geo-shape", "media", "document",
}


@dataclass(frozen=True)
class PropertyType:
    kind: str
    enum_values: tuple[str, ...] = ()
    precision: int | None = None
    scale: int | None = None
    dim: int | None = None
    inner: "PropertyType | None" = None
    struct_fields: dict[str, "PropertyType"] = field(default_factory=dict)

    # ---------- parsing ----------

    @classmethod
    def parse(cls, text: str) -> "PropertyType":
        t = text.strip()
        m = re.fullmatch(r"enum\[(.*)\]", t)
        if m:
            values = tuple(v.strip() for v in m.group(1).split(",") if v.strip())
            if not values:
                raise ValueError(f"empty enum: {text!r}")
            return cls("enum", enum_values=values)
        m = re.fullmatch(r"decimal\((\d+)\s*,\s*(\d+)\)", t)
        if m:
            return cls("decimal", precision=int(m.group(1)), scale=int(m.group(2)))
        m = re.fullmatch(r"vector\((\d+)\)", t)
        if m:
            return cls("vector", dim=int(m.group(1)))
        m = re.fullmatch(r"array\((.+)\)", t)
        if m:
            return cls("array", inner=cls.parse(m.group(1)))
        m = re.fullmatch(r"struct\{(.*)\}", t)
        if m:
            fields: dict[str, PropertyType] = {}
            for part in _split_top(m.group(1)):
                name, _, ftype = part.partition(":")
                fields[name.strip()] = cls.parse(ftype)
            return cls("struct", struct_fields=fields)
        if t in _SIMPLE:
            return cls(t)
        raise ValueError(f"unknown property type: {text!r}")

    # ---------- coercion (sync from source / API params) ----------

    def coerce(self, value: Any, *, prop: str = "?") -> Any:
        if value is None:
            return None
        k = self.kind
        try:
            if k == "string":
                if isinstance(value, str):
                    return value
                return str(value)
            if k == "integer":
                if isinstance(value, bool):
                    return int(value)
                if isinstance(value, int):
                    return value
                if isinstance(value, float) and value.is_integer():
                    return int(value)
                return int(str(value).strip())
            if k == "decimal":
                return float(value)
            if k == "boolean":
                if isinstance(value, bool):
                    return value
                s = str(value).strip().lower()
                if s in ("true", "1", "yes", "y"):
                    return True
                if s in ("false", "0", "no", "n"):
                    return False
                raise ValueError(value)
            if k == "date":
                if isinstance(value, _dt.datetime):
                    return value.date()
                if isinstance(value, _dt.date):
                    return value
                return _dt.date.fromisoformat(str(value).strip())
            if k == "timestamp":
                if isinstance(value, _dt.datetime):
                    return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
                s = str(value).strip().replace("Z", "+00:00")
                return _dt.datetime.fromisoformat(s)
            if k == "enum":
                s = value if isinstance(value, str) else str(value)
                if s not in self.enum_values:
                    raise ValueError(f"{s!r} not in {list(self.enum_values)}")
                return s
            if k in ("geo-point", "geo-shape", "media", "document"):
                return str(value)
            if k == "vector":
                if isinstance(value, (list, tuple)):
                    return list(map(float, value))
                raise ValueError("vector value must be a list")
            if k == "array":
                if isinstance(value, (list, tuple)):
                    return [self.inner.coerce(v, prop=prop) for v in value]  # type: ignore[union-attr]
                raise ValueError("array value must be a list")
            if k == "struct":
                if isinstance(value, dict):
                    return {
                        name: ftype.coerce(value.get(name), prop=f"{prop}.{name}")
                        for name, ftype in self.struct_fields.items()
                    }
                raise ValueError("struct value must be a mapping")
        except (ValueError, TypeError) as exc:
            raise TypeMismatchError(
                f"property {prop}: cannot coerce {value!r} to {self.to_dsl()}",
                details={"property": prop, "reason": str(exc), "value": repr(value)},
            ) from exc
        raise ValueError(f"unhandled kind {k}")  # pragma: no cover

    def to_dsl(self) -> str:
        k = self.kind
        if k == "enum":
            return "enum[" + ", ".join(self.enum_values) + "]"
        if k == "decimal":
            return f"decimal({self.precision},{self.scale})"
        if k == "vector":
            return f"vector({self.dim})"
        if k == "array":
            return f"array({self.inner.to_dsl()})"  # type: ignore[union-attr]
        if k == "struct":
            return "struct{" + ", ".join(f"{n}:{t.to_dsl()}" for n, t in self.struct_fields.items()) + "}"
        return k


def _split_top(text: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return [p for p in (s.strip() for s in parts) if p]
