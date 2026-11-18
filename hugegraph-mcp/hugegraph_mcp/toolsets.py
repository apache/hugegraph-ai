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

"""Toolset configuration names, independent of package and tool contract versions."""

import logging

DEFAULT_TOOLSET = "core"
VALID_TOOLSETS = frozenset({DEFAULT_TOOLSET, "legacy"})
DEFAULT_CORE_PROFILE = "compat"
VALID_CORE_PROFILES = frozenset({DEFAULT_CORE_PROFILE, "lean"})
_ALIASES = {"v2_core": "core", "v1": "legacy"}
LOGGER = logging.getLogger(__name__)


def resolve_core_profile(value: str | None) -> str:
    """Normalize the core toolset profile (compat or lean)."""
    if value is None:
        return DEFAULT_CORE_PROFILE
    normalized = value.strip().lower()
    if normalized in VALID_CORE_PROFILES:
        return normalized
    raise ValueError(f"Invalid HUGEGRAPH_MCP_CORE_PROFILE value {value!r}; expected compat or lean.")


def tool_contract_version(toolset: str, core_profile: str = DEFAULT_CORE_PROFILE) -> str:
    """Return the tool contract version string for the active toolset/profile."""
    if toolset != "legacy" and core_profile == "lean":
        return "3.0"
    return "2.0"


def resolve_toolset(value: str | None) -> str:
    """Normalize configuration once at startup; never silently change capabilities."""
    if value is None:
        return DEFAULT_TOOLSET
    value = value.strip()
    if value in VALID_TOOLSETS:
        return value
    if value in _ALIASES:
        canonical = _ALIASES[value]
        LOGGER.warning(
            "HUGEGRAPH_MCP_TOOLSET=%s is deprecated; use %s. The toolset reported by inspect_graph_tool is %s.",
            value,
            canonical,
            canonical,
        )
        return canonical
    raise ValueError(
        f"Invalid HUGEGRAPH_MCP_TOOLSET value {value!r}; expected core or legacy "
        "(deprecated aliases: v2_core, v1). Unset the variable to use core."
    )
