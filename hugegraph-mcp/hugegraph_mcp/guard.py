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

"""权限守卫 — 统一的能力检查入口。

readonly 模式下只允许 READ + GENERATE 能力，其他操作返回 READONLY_VIOLATION 信封。
不抛异常：调用方检查返回值是否是 envelope_err 即可。"""

from enum import Enum
from typing import Any

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err


class Capability(str, Enum):
    READ = "READ"
    GENERATE = "GENERATE"
    DATA_WRITE = "DATA_WRITE"
    SCHEMA_WRITE = "SCHEMA_WRITE"
    INDEX_WRITE = "INDEX_WRITE"
    DEBUG_WRITE = "DEBUG_WRITE"


READONLY_ALLOWED_CAPABILITIES = frozenset(
    {
        Capability.READ,
        Capability.GENERATE,
    }
)
WRITE_CAPABILITIES = frozenset(
    {
        Capability.DATA_WRITE,
        Capability.SCHEMA_WRITE,
        Capability.INDEX_WRITE,
        Capability.DEBUG_WRITE,
    }
)


def is_allowed_in_readonly(capability: Capability) -> bool:
    return capability in READONLY_ALLOWED_CAPABILITIES


def guard(
    capability: Capability,
    *,
    cfg: MCPConfig | None = None,
) -> dict[str, Any] | None:
    cfg = cfg or MCPConfig.from_env()
    readonly = cfg.is_readonly()

    if capability in WRITE_CAPABILITIES and not readonly and not cfg.has_safe_write_store():
        return envelope_err(
            ErrorType.FEATURE_DISABLED,
            "Write capability requires a shared transactional plan store when multiple MCP instances are configured.",
            suggestion=(
                "Run one write-enabled MCP instance with the SQLite plan store, "
                "or configure a supported shared transactional PlanStore."
            ),
            readonly=False,
            graph=cfg.graph,
            graphspace=cfg.graphspace,
            capability=capability.value,
            details={
                "plan_store_backend": cfg.plan_store_backend,
                "write_instance_count": cfg.write_instance_count,
            },
        )

    if not readonly or is_allowed_in_readonly(capability):
        return None

    return envelope_err(
        ErrorType.READONLY_VIOLATION,
        f"{capability.value} capability is disabled in read-only mode",
        suggestion="Disable HUGEGRAPH_MCP_READONLY to allow this operation.",
        readonly=readonly,
        graph=cfg.graph,
        graphspace=cfg.graphspace,
        capability=capability.value,
    )


def guard_write(
    capability: Capability = Capability.DATA_WRITE,
    *,
    cfg: MCPConfig | None = None,
) -> dict[str, Any] | None:
    return guard(capability, cfg=cfg)


def require_capability(
    capability: Capability,
    *,
    cfg: MCPConfig | None = None,
) -> None:
    violation = guard(capability, cfg=cfg)
    if violation is not None:
        message = violation["error"]["message"]
        raise PermissionError(message)
