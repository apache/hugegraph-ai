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

"""统一配置层 — 所有 MCP 工具通过 MCPConfig.from_env() 获取配置。

环境变量优先级高于默认值，避免硬编码连接信息。"""

import logging
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})
LOGGER = logging.getLogger("hugegraph_mcp.config")
CONFIG_ENV_NAMES = (
    "HUGEGRAPH_URL",
    "HUGEGRAPH_GRAPH_PATH",
    "HUGEGRAPH_GRAPH",
    "HUGEGRAPH_GRAPHSPACE",
    "HUGEGRAPH_USER",
    "HUGEGRAPH_PASSWORD",
    "HUGEGRAPH_MCP_READONLY",
    "HUGEGRAPH_AI_URL",
    "HUGEGRAPH_AI_TOKEN",
    "HUGEGRAPH_AI_GRAPH_URL",
    "HUGEGRAPH_MCP_ALLOW_AI",
    "HUGEGRAPH_MCP_ADMIN_MODE",
    "HUGEGRAPH_MCP_TIMEOUT_SECONDS",
    "HUGEGRAPH_AI_TIMEOUT_SECONDS",
    "HUGEGRAPH_CONNECT_TIMEOUT_SECONDS",
    "HUGEGRAPH_READ_TIMEOUT_SECONDS",
    "HUGEGRAPH_WRITE_TIMEOUT_SECONDS",
    "HUGEGRAPH_MCP_MAX_RESULT_ITEMS",
    "HUGEGRAPH_MCP_MAX_RESULT_BYTES",
    "HUGEGRAPH_MCP_PLAN_STORE",
    "HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT",
    "HUGEGRAPH_MCP_STATE_DIR",
    "XDG_STATE_HOME",
)
_CONFIG_CACHE: tuple[tuple[tuple[str, str | None], ...], "MCPConfig"] | None = None


@dataclass(frozen=True)
class _NumericFieldSpec:
    """Parsing and operational bounds for one numeric environment setting."""

    kind: Literal["integer", "numeric"]
    default: int | float
    minimum: int | float
    maximum: int | float


_NUMERIC_FIELD_SPECS = {
    "connect_timeout_seconds": _NumericFieldSpec("numeric", 0.5, 0.001, 86_400.0),
    "read_timeout_seconds": _NumericFieldSpec("numeric", 15.0, 0.001, 86_400.0),
    "write_timeout_seconds": _NumericFieldSpec("numeric", 15.0, 0.001, 86_400.0),
    "timeout_seconds": _NumericFieldSpec("integer", 30, 1, 86_400),
    "max_result_items": _NumericFieldSpec("integer", 100, 1, 1_000_000),
    "max_result_bytes": _NumericFieldSpec("integer", 1_048_576, 1, 1_073_741_824),
    "write_instance_count": _NumericFieldSpec("integer", 1, 1, 1024),
}


@dataclass(frozen=True)
class MCPConfig:
    """MCP 服务器统一配置，所有字段从环境变量读取，有合理默认值。"""

    url: str = "http://127.0.0.1:8080"
    graph: str = "hugegraph"
    graphspace: str | None = "DEFAULT"
    user: str = "admin"
    password: str = ""
    readonly: bool = True
    ai_url: str = "http://127.0.0.1:8001"
    ai_token: str | None = None
    ai_graph_url: str | None = None
    allow_ai: bool = False
    admin_mode: bool = False
    connect_timeout_seconds: float = 0.5
    read_timeout_seconds: float = 15.0
    write_timeout_seconds: float = 15.0
    timeout_seconds: int = 30
    max_result_items: int = 100
    max_result_bytes: int = 1_048_576
    plan_store_backend: str = "sqlite"
    write_instance_count: int = 1
    state_dir: Path = field(default_factory=lambda: Path.home() / ".local" / "state" / "hugegraph-mcp")
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "MCPConfig":
        global _CONFIG_CACHE

        use_cache = env is None
        if use_cache:
            # Read each setting once, then use that same snapshot for both the
            # cache key and parsing.  Reading os.environ once for the key and
            # again below could otherwise cache a permissive configuration
            # under a fail-closed key when the environment changes mid-call.
            env = _environment_snapshot(os.environ)
            cache_key = _env_cache_key(env)
            if _CONFIG_CACHE is not None and cache_key == _CONFIG_CACHE[0]:
                return _CONFIG_CACHE[1]
        else:
            cache_key = None

        warnings: list[str] = []

        path_graphspace, path_graph = _parse_graph_path(env.get("HUGEGRAPH_GRAPH_PATH", "DEFAULT/hugegraph"))
        graphspace = path_graphspace
        graph = path_graph

        split_graphspace = env.get("HUGEGRAPH_GRAPHSPACE")
        split_graph = env.get("HUGEGRAPH_GRAPH")
        if env.get("HUGEGRAPH_GRAPH_PATH") is not None and (split_graphspace is not None or split_graph is not None):
            warnings.append("HUGEGRAPH_GRAPHSPACE/HUGEGRAPH_GRAPH override HUGEGRAPH_GRAPH_PATH")

        if split_graphspace is not None:
            graphspace = _non_empty(split_graphspace, "DEFAULT")
        if split_graph is not None:
            graph = _non_empty(split_graph, "hugegraph")

        readonly = _parse_bool(
            env.get("HUGEGRAPH_MCP_READONLY"),
            "HUGEGRAPH_MCP_READONLY",
            True,
            warnings,
        )
        allow_ai = _parse_bool(
            env.get("HUGEGRAPH_MCP_ALLOW_AI"),
            "HUGEGRAPH_MCP_ALLOW_AI",
            False,
            warnings,
        )
        admin_mode = _parse_bool(
            env.get("HUGEGRAPH_MCP_ADMIN_MODE"),
            "HUGEGRAPH_MCP_ADMIN_MODE",
            False,
            warnings,
        )

        config = cls(
            url=env.get("HUGEGRAPH_URL", "http://127.0.0.1:8080"),
            graph=graph,
            graphspace=graphspace,
            user=env.get("HUGEGRAPH_USER", "admin"),
            password=env.get("HUGEGRAPH_PASSWORD", ""),
            readonly=readonly,
            ai_url=env.get("HUGEGRAPH_AI_URL", "http://127.0.0.1:8001"),
            ai_token=_optional_non_empty(env.get("HUGEGRAPH_AI_TOKEN")),
            ai_graph_url=_optional_non_empty(env.get("HUGEGRAPH_AI_GRAPH_URL")),
            allow_ai=allow_ai,
            admin_mode=admin_mode,
            connect_timeout_seconds=_parse_numeric_field(
                env.get("HUGEGRAPH_CONNECT_TIMEOUT_SECONDS"),
                "connect_timeout_seconds",
            ),
            read_timeout_seconds=_parse_numeric_field(
                env.get("HUGEGRAPH_READ_TIMEOUT_SECONDS"),
                "read_timeout_seconds",
            ),
            write_timeout_seconds=_parse_numeric_field(
                env.get("HUGEGRAPH_WRITE_TIMEOUT_SECONDS"),
                "write_timeout_seconds",
            ),
            timeout_seconds=_parse_numeric_field(
                env.get("HUGEGRAPH_AI_TIMEOUT_SECONDS") or env.get("HUGEGRAPH_MCP_TIMEOUT_SECONDS"),
                "timeout_seconds",
            ),
            max_result_items=_parse_numeric_field(
                env.get("HUGEGRAPH_MCP_MAX_RESULT_ITEMS"),
                "max_result_items",
            ),
            max_result_bytes=_parse_numeric_field(
                env.get("HUGEGRAPH_MCP_MAX_RESULT_BYTES"),
                "max_result_bytes",
            ),
            plan_store_backend=(env.get("HUGEGRAPH_MCP_PLAN_STORE", "sqlite").strip().lower() or "invalid"),
            write_instance_count=_parse_numeric_field(
                env.get("HUGEGRAPH_MCP_WRITE_INSTANCE_COUNT"),
                "write_instance_count",
            ),
            state_dir=_state_dir(env),
            warnings=tuple(warnings),
        )
        for warning in config.warnings:
            LOGGER.warning(warning)
        if use_cache:
            assert cache_key is not None
            # Store key and value as one object so concurrent readers can
            # never observe a key paired with a different configuration.
            _CONFIG_CACHE = (cache_key, config)
        return config

    def is_readonly(self) -> bool:
        return self.readonly

    def has_safe_write_store(self) -> bool:
        return self.plan_store_backend == "sqlite" and self.write_instance_count == 1


def _parse_graph_path(graph_path: str) -> tuple[str, str]:
    if "/" in graph_path:
        graphspace, graph = graph_path.split("/", 1)
    else:
        graphspace, graph = "DEFAULT", graph_path

    return _non_empty(graphspace, "DEFAULT"), _non_empty(graph, "hugegraph")


def _parse_bool(
    value: str | None,
    env_name: str,
    safe_default: bool,
    warnings: list[str],
) -> bool:
    if value is None:
        return safe_default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    warnings.append(f"Invalid boolean configuration: {env_name}; using safe default")
    return safe_default


def _parse_numeric_field(value: str | None, field_name: str) -> int | float:
    spec = _NUMERIC_FIELD_SPECS[field_name]
    if value is None or value.strip() == "":
        return spec.default
    try:
        parsed = int(value) if spec.kind == "integer" else float(value)
    except ValueError:
        _warn_invalid_numeric(value, spec)
        return spec.default
    if (isinstance(parsed, float) and not math.isfinite(parsed)) or parsed < spec.minimum or parsed > spec.maximum:
        _warn_invalid_numeric(value, spec)
        return spec.default
    return parsed


def _warn_invalid_numeric(value: str, spec: _NumericFieldSpec) -> None:
    LOGGER.warning(
        "Invalid %s config value %r; using default %s",
        spec.kind,
        value,
        spec.default,
    )


def _non_empty(value: str, default: str) -> str:
    return value.strip() or default


def _optional_non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _state_dir(env: Mapping[str, str]) -> Path:
    explicit = env.get("HUGEGRAPH_MCP_STATE_DIR")
    if explicit is not None and explicit.strip():
        return Path(explicit).expanduser()
    xdg_state_home = env.get("XDG_STATE_HOME")
    if xdg_state_home is not None and xdg_state_home.strip():
        return Path(xdg_state_home).expanduser() / "hugegraph-mcp"
    return Path.home() / ".local" / "state" / "hugegraph-mcp"


def _env_cache_key(env: Mapping[str, str]) -> tuple[tuple[str, str | None], ...]:
    return tuple((name, env.get(name)) for name in CONFIG_ENV_NAMES)


def _environment_snapshot(env: Mapping[str, str]) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for name in CONFIG_ENV_NAMES:
        value = env.get(name)
        if value is not None:
            snapshot[name] = value
    return snapshot


class RuntimeConfigProxy:
    """Compatibility proxy for code that imports config directly."""

    def __getattr__(self, name: str):
        return getattr(MCPConfig.from_env(), name)

    def is_readonly(self) -> bool:
        return MCPConfig.from_env().is_readonly()


config = RuntimeConfigProxy()
