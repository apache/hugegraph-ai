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

"""Canonical JSON helpers shared by runtime contracts and graph state."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import TypeAlias, cast

from hugegraph_llm.extraction_runtime.v1.errors import InvalidGraphError

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | Mapping[str, "JsonValue"] | Sequence["JsonValue"]
JsonObject: TypeAlias = Mapping[str, JsonValue]

_SENSITIVE_PROVENANCE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "cookies",
    "password",
    "refresh_token",
    "secret",
    "token",
}
_VOLATILE_PROVENANCE_KEYS = {
    "duration",
    "ended_at",
    "lease_owner",
    "request_id",
    "run_id",
    "started_at",
    "temporary_path",
    "timestamp",
    "trace_id",
    "worker_id",
}
_SENSITIVE_PROVENANCE_KEYS_COMPACT = {key.replace("_", "") for key in _SENSITIVE_PROVENANCE_KEYS}
_VOLATILE_PROVENANCE_KEYS_COMPACT = {key.replace("_", "") for key in _VOLATILE_PROVENANCE_KEYS}


def canonical_json(value: object) -> str:
    """Return a deterministic JSON representation after strict validation."""
    plain = _copy_json(value, path="$", require_object=False)
    return json.dumps(plain, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def digest_json(value: object) -> str:
    """Return a version-explicit SHA-256 digest for canonical JSON."""
    encoded = canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def freeze_json_object(value: object) -> JsonObject:
    """Validate and detach a JSON object, then recursively make it immutable."""
    plain = _copy_json(value, path="$", require_object=True)
    return cast(JsonObject, _freeze(plain))


def thaw_json(value: JsonValue) -> object:
    """Return detached plain dict/list JSON data from an immutable value."""
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw_json(item) for item in value]
    return value


def ensure_credential_free(value: JsonValue, *, path: str = "$") -> None:
    """Reject credential-shaped keys without inspecting user text values."""
    _ensure_provenance_keys(
        value,
        path=path,
        forbidden=_SENSITIVE_PROVENANCE_KEYS,
        forbidden_compact=_SENSITIVE_PROVENANCE_KEYS_COMPACT,
        kind="credential",
    )


def ensure_stable_provenance(value: JsonValue, *, path: str = "$") -> None:
    """Reject credentials and process-instance fields from digest inputs."""
    ensure_credential_free(value, path=path)
    _ensure_provenance_keys(
        value,
        path=path,
        forbidden=_VOLATILE_PROVENANCE_KEYS,
        forbidden_compact=_VOLATILE_PROVENANCE_KEYS_COMPACT,
        kind="volatile",
    )


def _copy_json(value: object, *, path: str, require_object: bool) -> object:
    if require_object and not isinstance(value, Mapping):
        raise InvalidGraphError(f"{path} must be a JSON object")
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidGraphError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        copied: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidGraphError(f"{path} contains a non-string object key")
            copied[key] = _copy_json(item, path=f"{path}.{key}", require_object=False)
        return copied
    if isinstance(value, (list, tuple)):
        return [_copy_json(item, path=f"{path}[{index}]", require_object=False) for index, item in enumerate(value)]
    raise InvalidGraphError(f"{path} contains unsupported JSON value {type(value).__name__}")


def _freeze(value: object) -> JsonValue:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return cast(JsonScalar, value)


def _ensure_provenance_keys(
    value: JsonValue,
    *,
    path: str,
    forbidden: set[str],
    forbidden_compact: set[str],
    kind: str,
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = key.lower().replace("-", "_")
            if normalized in forbidden or normalized.replace("_", "") in forbidden_compact:
                raise ValueError(f"{kind} provenance field {path}.{key} is forbidden")
            _ensure_provenance_keys(
                item,
                path=f"{path}.{key}",
                forbidden=forbidden,
                forbidden_compact=forbidden_compact,
                kind=kind,
            )
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            _ensure_provenance_keys(
                item,
                path=f"{path}[{index}]",
                forbidden=forbidden,
                forbidden_compact=forbidden_compact,
                kind=kind,
            )
