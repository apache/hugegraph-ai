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

"""NL-to-Gremlin 生成 — 通过 HugeGraph-AI /text2gremlin 将自然语言转为 Gremlin。

默认只返回生成的 Gremlin + 安全元数据，不自动执行。
execute=True 且安全分类为 safe 时才自动执行，不安全查询只返回不执行。
"""

from typing import Any

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.gremlin_policy import check_gremlin_read
from hugegraph_mcp.gremlin_tools import execute_gremlin_read
from hugegraph_mcp.hugegraph_ai_client import post

_GENERATION_OUTPUT_TYPES = frozenset(
    {
        "match_result",
        "template_gremlin",
        "raw_gremlin",
    }
)


def generate_gremlin(
    query: str,
    execute: bool = False,
    output_types: list[str] | None = None,
    limit_policy: str = "warn",
) -> dict[str, Any]:
    """将自然语言转为 Gremlin — 默认只生成不执行。

    execute=True 时通过 GremlinPolicy 检查安全性：只有 safe 的查询才会执行。
    limit_policy 透传给 execute_gremlin_read，默认 warn 保持兼容。
    """

    invalid_output_types = sorted(
        {
            output_type if isinstance(output_type, str) else repr(output_type)
            for output_type in (output_types or [])
            if not isinstance(output_type, str)
            or output_type not in _GENERATION_OUTPUT_TYPES
        }
    )
    if invalid_output_types:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            "generate_gremlin only accepts generation output types.",
            suggestion=(
                "Use match_result, template_gremlin, or raw_gremlin. "
                "Execute generated Gremlin through the MCP read execution path."
            ),
            details={
                "invalid_output_types": invalid_output_types,
                "allowed_output_types": sorted(_GENERATION_OUTPUT_TYPES),
            },
        )

    cfg = MCPConfig.from_env()
    client_config = {
        "graph": cfg.graph,
    }
    if cfg.graphspace:
        client_config["gs"] = cfg.graphspace
    payload: dict[str, Any] = {
        "query": query,
        "client_config": client_config,
    }
    if output_types is not None:
        payload["output_types"] = output_types

    ai_result = post("/text2gremlin", json=payload)
    if not ai_result.get("ok"):
        return ai_result

    ai_data = ai_result.get("data") or {}
    if not isinstance(ai_data, dict):
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            "HugeGraph-AI returned an invalid text2gremlin response.",
            details={"response": ai_data},
        )

    template_gremlin = ai_data.get("template_gremlin")
    raw_gremlin = ai_data.get("raw_gremlin")
    match_result = ai_data.get("match_result")
    requested = set(output_types or [])
    gremlin_candidates = []
    if not requested or "template_gremlin" in requested:
        gremlin_candidates.append(template_gremlin)
    if not requested or "raw_gremlin" in requested:
        gremlin_candidates.append(raw_gremlin)
    if not requested:
        gremlin_candidates.append(ai_data.get("gremlin"))
    gremlin = next(
        (
            candidate
            for candidate in gremlin_candidates
            if isinstance(candidate, str) and candidate.strip()
        ),
        None,
    )
    requires_gremlin = not requested or bool(
        requested & {"template_gremlin", "raw_gremlin"}
    )
    if requires_gremlin and gremlin is None:
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            "HugeGraph-AI did not return Gremlin.",
            details={"response": ai_data},
        )

    requires_index = ai_data.get("requires_index", False)
    assumptions = ai_data.get("assumptions")

    decision = check_gremlin_read(gremlin) if gremlin else None
    safety = decision.classification if decision else "uncertain"
    is_readonly = decision.allowed if decision else False
    risk_level = _risk_level(safety)

    data = {
        "gremlin": gremlin,
        "template_gremlin": template_gremlin,
        "raw_gremlin": raw_gremlin,
        "match_result": match_result,
        "is_readonly": is_readonly,
        "risk_level": risk_level,
        "requires_index": requires_index,
        "assumptions": assumptions,
        "executed": False,
        "execution_result": None,
    }

    if not execute:
        return envelope_ok(data)

    if not is_readonly:
        return envelope_err(
            ErrorType.UNSAFE_GREMLIN,
            "Generated Gremlin is not safe to execute automatically",
            details={
                "classification": safety,
                "gremlin": gremlin,
                "risk_level": risk_level,
            },
        )

    data["executed"] = True
    execution_result = execute_gremlin_read(gremlin, limit_policy=limit_policy)
    if isinstance(execution_result, dict) and execution_result.get("ok") is False:
        data["execution_result"] = execution_result
        error = execution_result.get("error") or {}
        return envelope_err(
            error.get("type", ErrorType.FLOW_EXECUTION_FAILED),
            error.get("message", "Generated Gremlin execution failed."),
            suggestion=error.get("suggestion"),
            retryable=error.get("retryable", False),
            details={
                "gremlin": gremlin,
                "generation": data,
                "execution_error": error,
            },
            warnings=execution_result.get("warnings", []),
        )
    if isinstance(execution_result, dict) and execution_result.get("success") is False:
        data["execution_result"] = execution_result
        return envelope_err(
            ErrorType.FLOW_EXECUTION_FAILED,
            "Generated Gremlin execution failed.",
            details={"gremlin": gremlin, "generation": data},
        )
    if isinstance(execution_result, dict) and execution_result.get("ok") is True:
        data["execution_result"] = execution_result.get("data")
        data["execution_meta"] = execution_result.get("meta")
    else:
        data["execution_result"] = execution_result
    return envelope_ok(data)


def _risk_level(safety: str) -> str:
    if safety == "safe":
        return "low"
    if safety == "unsafe":
        return "high"
    return "medium"
