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

"""Capability-driven tool registry for HugeGraph MCP toolsets and profiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hugegraph_mcp.toolsets import DEFAULT_CORE_PROFILE


@dataclass(frozen=True)
class ToolSpec:
    """Metadata describing a tool's profile membership and runtime requirements."""

    name: str
    profiles: frozenset[str]
    requires_ai: bool = False
    requires_write: bool = False
    requires_admin: bool = False
    placeholder: bool = False
    side_effect: str = "read"


class ToolRegistry:
    """Stores MCP tool functions alongside their capability specs."""

    def __init__(self) -> None:
        self._entries: list[tuple[ToolSpec, Any]] = []
        self._by_name: dict[str, tuple[ToolSpec, Any]] = {}

    def register(self, spec: ToolSpec, func: Any) -> Any:
        if spec.name in self._by_name:
            raise ValueError(f"Duplicate tool registration: {spec.name}")
        entry = (spec, func)
        self._entries.append(entry)
        self._by_name[spec.name] = entry
        return func

    def spec_for(self, name: str) -> ToolSpec | None:
        entry = self._by_name.get(name)
        return entry[0] if entry is not None else None

    def select(
        self,
        toolset: str,
        *,
        core_profile: str = DEFAULT_CORE_PROFILE,
        readonly: bool = True,
        allow_ai: bool = False,
        admin_mode: bool = False,
    ) -> list[tuple[ToolSpec, Any]]:
        """Select tools matching the requested toolset/profile and runtime capabilities."""

        if toolset == "legacy":
            return [(spec, func) for spec, func in self._entries if "legacy" in spec.profiles]

        profile_key = f"core:{core_profile}"
        selected: list[tuple[ToolSpec, Any]] = []
        for spec, func in self._entries:
            if profile_key not in spec.profiles:
                continue
            if core_profile == "lean":
                if spec.placeholder:
                    continue
                if spec.requires_ai and not allow_ai:
                    continue
                if spec.requires_admin and not admin_mode:
                    continue
                if spec.requires_write and readonly:
                    continue
            selected.append((spec, func))
        return selected
