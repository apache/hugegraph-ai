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

# The extraction prompt contains intentionally long, copy-pasteable JSON contracts.
# ruff: noqa: E501

import json
from typing import Any

from hugegraph_mcp.artifacts import get_default_artifact_store
from hugegraph_mcp.config import MCPConfig, get_effective_config
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.hugegraph_ai_client import post
from hugegraph_mcp.resource_uri import build_artifact_resource_uri
from hugegraph_mcp.runtime import get_current_actor
from hugegraph_mcp.stores.base import default_stdio_actor
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


AUTO_ARTIFACT_THRESHOLD_BYTES = 32_768


def extract_graph_data(
    text: str,
    schema: dict[str, Any] | str | None = None,
    example_prompt: str | None = None,
    review_options: dict[str, Any] | None = None,
    output: str = "inline",
) -> dict[str, Any]:
    """从自然语言文本中抽取候选图数据 — 不写入 HugeGraph。

    返回 standard envelope，其中 graph_data 含 vertices/edges 供用户审阅。
    """

    if output not in {"inline", "artifact", "auto"}:
        return envelope_err(
            ErrorType.VALIDATION_ERROR,
            f"Unsupported output mode: {output!r}; expected inline, artifact, or auto.",
            details={"output": output},
        )

    cfg = get_effective_config()
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
    request_body: dict[str, Any] = {
        "text": text,
        "schema": schema_message,
        "example_prompt": prompt_message,
        "language": "zh",
    }
    if review_options is not None:
        request_body["review_options"] = dict(review_options)
    ai_result = post("/graph-extract", json=request_body)
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

    payload_dict = payload if isinstance(payload, dict) else {}
    raw_chunks = graph_data.get("chunks") or payload_dict.get("chunks") or payload_dict.get("chunk_results") or []
    if isinstance(raw_chunks, str):
        try:
            raw_chunks = json.loads(raw_chunks)
        except json.JSONDecodeError:
            raw_chunks = []
    chunks = raw_chunks if isinstance(raw_chunks, list) else []

    raw_issues = graph_data.get("issues") or payload_dict.get("issues") or []
    if isinstance(raw_issues, str):
        try:
            raw_issues = json.loads(raw_issues)
        except json.JSONDecodeError:
            raw_issues = [raw_issues] if raw_issues else []
    issues = raw_issues if isinstance(raw_issues, list) else []

    extraction_status = graph_data.get("extraction_status") or payload_dict.get("extraction_status") or "complete"
    if not isinstance(extraction_status, str):
        extraction_status = str(extraction_status)
    if extraction_status not in {"failed", "blocked"} and any(
        isinstance(ch, dict) and ch.get("status") in {"partial", "blocked", "failed"} for ch in chunks
    ):
        extraction_status = "partial"

    full_graph_data = {
        "schema_ref": schema_ref,
        "vertices": graph_data.get("vertices", []),
        "edges": graph_data.get("edges", []),
        "warnings": graph_data.get("warnings", []),
        "raw": graph_data.get("raw"),
    }
    response_data: dict[str, Any] = {
        "graph_data": full_graph_data,
        "raw_summary": graph_data.get("raw_summary"),
        "schema_warnings": graph_data.get("schema_warnings", []),
        "extraction_status": extraction_status,
        "chunks": chunks,
        "issues": issues,
        "call_count": graph_data.get("call_count") or payload_dict.get("call_count"),
    }

    encoded_response = json.dumps(response_data, ensure_ascii=False, separators=(",", ":"), default=str)
    encoded_size = len(encoded_response.encode("utf-8"))
    if output == "artifact" or (output == "auto" and encoded_size > AUTO_ARTIFACT_THRESHOLD_BYTES):
        actor = get_current_actor() or default_stdio_actor()
        owner_key = actor.principal_key
        tenant = actor.tenant
        try:
            manifest = get_default_artifact_store(cfg).put(
                encoded_response,
                owner_key=owner_key,
                tenant=tenant,
                target_graph={"url": cfg.url, "graph": cfg.graph, "graphspace": cfg.graphspace or "DEFAULT"},
                kind="extraction_result",
                schema_fingerprint=(
                    schema_ref.get("fingerprint") or schema_ref.get("sha256") if isinstance(schema_ref, dict) else None
                ),
            )
        except Exception as exc:
            return envelope_err(
                ErrorType.SERVER_ERROR,
                f"Failed to persist extraction artifact: {exc}",
                retryable=False,
                source="extract_graph_data_tool",
            )
        return envelope_ok(
            {
                "artifact_id": manifest.artifact_id,
                "artifact_uri": build_artifact_resource_uri(manifest.artifact_id),
                "part_count": manifest.part_count,
                "size_bytes": manifest.size_bytes,
                "vertex_count": len(full_graph_data["vertices"]),
                "edge_count": len(full_graph_data["edges"]),
                "extraction_status": extraction_status,
                "issues": issues,
            }
        )

    return envelope_ok(response_data)


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
    from hugegraph_mcp.schema_snapshot import compute_schema_fingerprint

    return compute_schema_fingerprint(schema)


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
    outer_metadata = {}
    if isinstance(parsed, dict) and "graph_data" in parsed:
        outer_metadata = parsed
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
        "warnings": parsed.get("warnings", outer_metadata.get("warnings", [])),
        "raw": parsed.get("raw"),
        "raw_summary": parsed.get("raw_summary", outer_metadata.get("raw_summary")),
        "schema_warnings": parsed.get("schema_warnings", outer_metadata.get("schema_warnings", [])),
    }


def _parse_json_if_needed(data: Any) -> Any:
    """AI 可能返回 JSON 字符串而非已解析对象，这里做兼容处理。"""
    if not isinstance(data, str):
        return data

    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return data
