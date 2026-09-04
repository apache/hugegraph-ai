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

"""自然语言抽取图数据 — 从文本中提取候选 vertices/edges，不写入 HugeGraph。

通过 HugeGraph-AI /graph-extract 端点将自然语言描述转为结构化的
{vertices: [...], edges: [...]} 图数据，供用户审阅后再导入。
"""

import hashlib
import json
from typing import Any

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.hugegraph_ai_client import post
from hugegraph_mcp.tools.live_schema import fetch_live_schema_or_none
from hugegraph_mcp.tools.schema_utils import schema_payload

DEFAULT_GRAPH_EXTRACT_PROMPT_ZH = """## 主要任务
只抽取输入文本和给定图谱 schema 共同支持的顶点与边。只返回合法 JSON。

## 输出格式
必须返回唯一 JSON 对象：{"vertices": [...], "edges": [...]}。
顶点对象：{"id":"顶点 id","label":"顶点标签","properties":{"属性名":"属性值", ...}}。
边对象：{"label":"边标签","outV":"源顶点 id","outVLabel":"源顶点标签","inV":"目标顶点 id","inVLabel":"目标顶点标签","properties":{"属性名":"属性值", ...}}。

## 抽取规则
1. 只能使用 schema 中已经存在的 vertex label、edge label 和 property key。
2. 可以把中文关系语义映射到 schema 中已有的英文标签，例如"同事"可映射为 schema 中的 colleague；但不要创造 schema 中不存在的标签。
3. 顶点 id 必须按 schema 的 vertexlabels[].id 与 primary_keys 生成；单主键格式为 "{vertexLabelID}:{properties.<primary_key>}"。
4. outV 和 inV 必须引用本次输出 vertices 中的 id，outVLabel/inVLabel 必须匹配边 schema 的 source_label/target_label。
5. 保持属性类型，移除空属性，不要编造文本中没有的事实。
6. 不要输出 Markdown、解释、注释或额外文本。"""


def extract_graph_data(
    text: str,
    schema: dict[str, Any] | str | None = None,
    example_prompt: str | None = None,
) -> dict[str, Any]:
    """从自然语言文本中抽取候选图数据 — 不写入 HugeGraph。

    返回 standard envelope，其中 graph_data 含 vertices/edges 供用户审阅。
    """

    cfg = MCPConfig.from_env()
    if schema is None and not cfg.allow_ai:
        # Preserve the capability gate without requiring HugeGraph connectivity.
        schema_message = cfg.graph
        schema_ref = _schema_ref(cfg, "graph", None)
    else:
        schema_message, schema_ref = _schema_context(schema, cfg)
    if schema_message is None:
        return envelope_err(
            ErrorType.CONNECTION_FAILED,
            "Cannot read the live HugeGraph schema for graph extraction.",
            suggestion="Check HugeGraph connectivity and retry the extraction.",
            details={"graph": cfg.graph, "graphspace": cfg.graphspace},
        )
    prompt_message = _example_prompt_message(example_prompt)
    ai_result = post(
        "/graph-extract",
        json={
            "text": text,
            "schema": schema_message,
            "example_prompt": prompt_message,
            "language": "zh",
        },
    )
    if not ai_result.get("ok"):
        return ai_result

    payload = _unwrap_ai_payload(ai_result.get("data"))
    graph_data = _extract_graph_data(payload)
    if graph_data is None:
        return envelope_err(
            ErrorType.INVALID_GRAPH_DATA,
            "HugeGraph-AI did not return graph_data with vertices and edges.",
            details={"data": payload},
        )

    return envelope_ok(
        {
            "graph_data": {
                "schema_ref": schema_ref,
                "vertices": graph_data.get("vertices", []),
                "edges": graph_data.get("edges", []),
                "warnings": graph_data.get("warnings", []),
                "raw": graph_data.get("raw"),
            },
            "raw_summary": graph_data.get("raw_summary"),
            "schema_warnings": graph_data.get("schema_warnings", []),
        }
    )


def _schema_context(schema: dict[str, Any] | str | None, cfg: MCPConfig) -> tuple[str | None, dict[str, Any]]:
    """Resolve schema input and provenance from one graph target.

    A missing schema is read from MCP's HugeGraph connection and sent inline to
    HugeGraph-AI. This keeps extraction and provenance tied to the same target.
    """
    schema_source = "provided"
    raw_schema: Any = schema
    if schema is None:
        live_schema = fetch_live_schema_or_none()
        raw_schema = schema_payload(live_schema)
        schema_source = "live"
        if raw_schema is None:
            return None, _schema_ref(cfg, schema_source, None)

    if isinstance(raw_schema, dict):
        schema_message = json.dumps(raw_schema, sort_keys=True, default=str)
        fingerprint = _schema_fingerprint(raw_schema)
    elif isinstance(raw_schema, str) and raw_schema.strip():
        schema_message = raw_schema
        try:
            parsed = json.loads(raw_schema)
        except json.JSONDecodeError:
            parsed = None
        fingerprint = _schema_fingerprint(parsed) if isinstance(parsed, dict) else None
    else:
        return None, _schema_ref(cfg, schema_source, None)

    return schema_message, _schema_ref(cfg, schema_source, fingerprint)


def _schema_ref(cfg: MCPConfig, schema_source: str, fingerprint: str | None) -> dict[str, Any]:
    return {
        "schema_source": schema_source,
        "graph": cfg.graph,
        "graphspace": cfg.graphspace,
        "version": None,
        "fingerprint": fingerprint,
    }


def _schema_fingerprint(schema: dict[str, Any]) -> str:
    encoded = json.dumps(schema, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _example_prompt_message(example_prompt: str | None) -> str:
    if example_prompt is None:
        return DEFAULT_GRAPH_EXTRACT_PROMPT_ZH
    return example_prompt


def _unwrap_ai_payload(data: Any) -> Any:
    """解包 AI 返回的双层信封 {ok, data} -> 内层 data。"""
    if isinstance(data, dict) and "ok" in data and "data" in data:
        if data.get("ok") is False:
            return data
        return data.get("data")
    return data


def _extract_graph_data(data: Any) -> dict[str, Any] | None:
    parsed = _parse_json_if_needed(data)
    if isinstance(parsed, dict) and "graph_data" in parsed:
        parsed = _parse_json_if_needed(parsed.get("graph_data"))

    if not isinstance(parsed, dict):
        return None

    vertices = parsed.get("vertices")
    edges = parsed.get("edges")
    if not isinstance(vertices, list) or not isinstance(edges, list):
        return None

    return {
        "vertices": vertices,
        "edges": edges,
        "warnings": parsed.get("warnings", []),
        "raw": parsed.get("raw"),
        "raw_summary": parsed.get("raw_summary"),
        "schema_warnings": parsed.get("schema_warnings", []),
    }


def _parse_json_if_needed(data: Any) -> Any:
    """AI 可能返回 JSON 字符串而非已解析对象，这里做兼容处理。"""
    if not isinstance(data, str):
        return data

    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return data
