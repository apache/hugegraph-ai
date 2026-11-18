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

"""Canonical serialization and content digest ownership."""

import hashlib
import json
from typing import Self

from pydantic import BaseModel, JsonValue, field_validator, model_validator

from hugegraph_llm_eval.contracts.base import StrictModel


class ContentDigest(StrictModel):
    """A versioned digest string using the only initial algorithm, SHA-256."""

    value: str

    @model_validator(mode="before")
    @classmethod
    def _accept_wire_string(cls, value: object) -> object:
        if isinstance(value, str):
            return {"value": value}
        return value

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: str) -> str:
        prefix = "sha256:"
        encoded = value.removeprefix(prefix)
        if not value.startswith(prefix) or len(encoded) != 64:
            msg = "digest must use sha256:<64 lowercase hex>"
            raise ValueError(msg)
        if encoded.lower() != encoded or any(char not in "0123456789abcdef" for char in encoded):
            msg = "digest must use sha256:<64 lowercase hex>"
            raise ValueError(msg)
        return value

    @property
    def hex_value(self) -> str:
        return self.value.removeprefix("sha256:")

    @classmethod
    def from_bytes(cls, content: bytes) -> Self:
        return cls(value=f"sha256:{hashlib.sha256(content).hexdigest()}")


def canonical_json_bytes(value: BaseModel | JsonValue) -> bytes:
    """Serialize JSON-compatible content deterministically for identity use."""

    serializable: JsonValue = (
        value.model_dump(mode="json", exclude_none=False) if isinstance(value, BaseModel) else value
    )
    try:
        encoded = json.dumps(
            serializable,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except ValueError as exc:
        msg = "canonical JSON numbers must be finite"
        raise ValueError(msg) from exc
    return encoded.encode("utf-8")


def canonical_digest(value: BaseModel | JsonValue) -> ContentDigest:
    return ContentDigest.from_bytes(canonical_json_bytes(value))
