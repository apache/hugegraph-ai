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

"""Confirmation mode policy for local stdio elicitation vs manual confirmation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hugegraph_mcp.config import MCPConfig

DEFAULT_CONFIRMATION_MODE = "manual"
VALID_CONFIRMATION_MODES = frozenset({DEFAULT_CONFIRMATION_MODE, "elicitation"})


def resolve_confirmation_mode(value: str | None) -> str:
    if value is None:
        return DEFAULT_CONFIRMATION_MODE
    normalized = value.strip().lower()
    if normalized in VALID_CONFIRMATION_MODES:
        return normalized
    raise ValueError(f"Invalid HUGEGRAPH_MCP_CONFIRMATION_MODE value {value!r}; expected manual or elicitation.")


def requires_interactive_confirmation(cfg: MCPConfig, *, side_effect: str = "write") -> bool:
    """Return True when interactive MCP elicitation should gate execution."""

    if side_effect not in {"write", "admin"}:
        return False
    return cfg.confirmation_mode == "elicitation" and cfg.transport == "stdio"
