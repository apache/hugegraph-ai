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

"""Unified typed write-preparation entry point for the lean core profile."""

from __future__ import annotations

from typing import Any

from hugegraph_mcp.envelope import ErrorType, envelope_err
from hugegraph_mcp.tools.manage_graph_data import manage_graph_data
from hugegraph_mcp.tools.manage_schema import manage_schema
from hugegraph_mcp.tools.mutate_graph_properties import mutate_graph_properties

PREPARE_WRITE_KINDS = frozenset({"schema", "import", "delete", "properties"})


def prepare_write(
    *,
    kind: str,
    mode: str | None = None,
    operations: list[dict[str, Any]] | None = None,
    graph_data: dict[str, Any] | None = None,
    change_plan: dict[str, Any] | None = None,
    target: str | None = None,
    operation: str | None = None,
    id: Any = None,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and preview/plan a typed write operation without executing it.

    Confirmed execution always goes through ``confirm_write_tool(plan_id)``.
    """

    normalized_kind = kind.strip().lower() if isinstance(kind, str) else ""
    if normalized_kind not in PREPARE_WRITE_KINDS:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"Unsupported prepare_write kind: {kind!r}.",
            suggestion="Use one of: schema, import, delete, properties.",
            source="prepare_write_tool",
            details={"kind": kind, "supported_kinds": sorted(PREPARE_WRITE_KINDS)},
        )

    if normalized_kind == "schema":
        schema_mode = (mode or "dry_run").strip().lower()
        if schema_mode not in {"validate", "dry_run"}:
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                f"prepare_write(kind='schema') only supports mode='validate' or 'dry_run', got {mode!r}.",
                suggestion="Use mode='dry_run' to issue a plan_id, then confirm with confirm_write_tool.",
                source="prepare_write_tool",
                details={"kind": normalized_kind, "mode": mode},
            )
        return manage_schema(mode=schema_mode, operations=operations)

    if normalized_kind == "import":
        if not isinstance(graph_data, dict):
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                "graph_data dict is required for kind='import'.",
                source="prepare_write_tool",
                details={"kind": normalized_kind},
            )
        return manage_graph_data(
            mode="import",
            graph_data=graph_data,
            dry_run=True,
            plan_tool_name="prepare_write_tool",
        )

    if normalized_kind == "delete":
        if not isinstance(change_plan, dict):
            return envelope_err(
                ErrorType.VALIDATION_ERROR,
                "change_plan dict is required for kind='delete'.",
                source="prepare_write_tool",
                details={"kind": normalized_kind},
            )
        return manage_graph_data(
            mode="delete",
            change_plan=change_plan,
            dry_run=True,
            plan_tool_name="prepare_write_tool",
        )

    if not target or not operation or id is None or not isinstance(properties, dict):
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "target, operation, id, and properties are required for kind='properties'.",
            source="prepare_write_tool",
            details={"kind": normalized_kind},
        )
    return mutate_graph_properties(
        target=target,
        operation=operation,
        id=id,
        properties=properties,
        dry_run=True,
    )
