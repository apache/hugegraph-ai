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

import json
import time
from typing import Any, Dict, List, Optional

from hugegraph_llm.api.models.graph_extract_requests import (
    GraphExtractAndImportRequest,
    GraphExtractRequest,
    GraphImportRequest,
    SchemaInput,
    _validate_schema_value,
)
from hugegraph_llm.api.models.graph_extract_responses import (
    GraphExtractResponse,
    GraphImportResponse,
)
from hugegraph_llm.config import prompt
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.scheduler import SchedulerSingleton
from hugegraph_llm.utils.log import log

SENSITIVE_CLIENT_CONFIG_KEYS = {"pwd", "password", "token", "api_key", "secret"}
SAFE_IMPORT_ERROR_KEYS = {"kind", "index", "label", "key", "reason"}


class FlowOutputValidationError(ValueError):
    """Raised when a workflow returns malformed output."""


def normalize_schema(schema: SchemaInput) -> str:
    schema = _validate_schema_value(schema)
    if isinstance(schema, dict):
        return json.dumps(schema, ensure_ascii=False)

    schema_text = str(schema).strip()
    if schema_text.startswith("{"):
        try:
            parsed_schema = json.loads(schema_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"schema must be valid JSON: {exc.msg}") from exc
        return json.dumps(parsed_schema, ensure_ascii=False)
    return schema_text


def _redact_client_config(client_config) -> Dict[str, Any]:
    if client_config is None:
        return {}
    config = client_config if isinstance(client_config, dict) else client_config.model_dump(exclude_none=True)
    return {key: ("***" if key in SENSITIVE_CLIENT_CONFIG_KEYS and value else value) for key, value in config.items()}


def _schema_graph_name(schema: str) -> Optional[str]:
    schema_text = str(schema).strip()
    return None if schema_text.startswith("{") else schema_text


def apply_client_config(
    client_config,
    schema: Optional[str] = None,
    align_graph_with_schema: bool = False,
) -> Optional[Dict[str, Any]]:
    if client_config is None:
        config = {}
    elif isinstance(client_config, dict):
        config = {key: value for key, value in client_config.items() if value is not None}
    else:
        config = client_config.model_dump(exclude_none=True)
    schema_graph = _schema_graph_name(schema) if schema else None
    if schema_graph:
        target_graph = config.get("graph")
        if target_graph and target_graph != schema_graph:
            raise ValueError("schema graph name must match client_config.graph")
        if align_graph_with_schema:
            config["graph"] = schema_graph
    return config or None


def _parse_flow_json(raw_result: Any, error_message: str) -> Dict[str, Any]:
    if isinstance(raw_result, dict):
        return raw_result
    if not isinstance(raw_result, str):
        raise FlowOutputValidationError(error_message)
    try:
        parsed = json.loads(raw_result)
    except json.JSONDecodeError as exc:
        raise FlowOutputValidationError(error_message) from exc
    if not isinstance(parsed, dict):
        raise FlowOutputValidationError(error_message)
    return parsed


def _pop_warnings(result: Dict[str, Any]) -> List[str]:
    warnings = []
    warning = result.pop("warning", None)
    if warning:
        warnings.append(str(warning))
    extra_warnings = result.pop("warnings", None)
    if isinstance(extra_warnings, list):
        warnings.extend(str(item) for item in extra_warnings)
    elif extra_warnings:
        warnings.append(str(extra_warnings))
    return warnings


def _count_items(result: Dict[str, Any], key: str) -> int:
    value = result.get(key)
    return len(value) if isinstance(value, list) else 0


def _validate_property_graph_result(result: Dict[str, Any]) -> None:
    vertices = result.get("vertices", [])
    edges = result.get("edges", [])
    if not isinstance(vertices, list) or not isinstance(edges, list):
        raise FlowOutputValidationError("property graph result must contain list vertices and edges")
    for index, vertex in enumerate(vertices):
        if not isinstance(vertex, dict) or "label" not in vertex or "properties" not in vertex:
            raise FlowOutputValidationError("canonical property graph vertex must include label and properties")
        if not _is_non_empty_string(vertex["label"]):
            raise FlowOutputValidationError(
                f"canonical property graph vertex[{index}].label must be a non-empty string"
            )
        if not isinstance(vertex["properties"], dict):
            raise FlowOutputValidationError(f"canonical property graph vertex[{index}].properties must be an object")
    required_edge_keys = {"label", "outV", "outVLabel", "inV", "inVLabel", "properties"}
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict) or not required_edge_keys.issubset(edge):
            raise FlowOutputValidationError(
                "canonical property graph edge must include label, outV, outVLabel, inV, inVLabel, and properties"
            )
        for key in ("label", "outV", "outVLabel", "inV", "inVLabel"):
            if not _is_non_empty_string(edge[key]):
                raise FlowOutputValidationError(
                    f"canonical property graph edge[{index}].{key} must be a non-empty string"
                )
        if not isinstance(edge["properties"], dict):
            raise FlowOutputValidationError(f"canonical property graph edge[{index}].properties must be an object")


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _build_import_status(import_result: Dict[str, Any]) -> str:
    skipped = (
        import_result.get("vertices_skipped", 0)
        + import_result.get("edges_skipped", 0)
        + import_result.get("triples_skipped", 0)
    )
    created = (
        import_result.get("vertices_created", 0)
        + import_result.get("edges_created", 0)
        + import_result.get("triples_created", 0)
    )
    if skipped and created:
        return "partial"
    if skipped and not created:
        return "failed"
    return "succeeded"


def _validate_import_result(import_result: Any) -> Dict[str, Any]:
    counter_keys = (
        "vertices_attempted",
        "vertices_created",
        "vertices_skipped",
        "edges_attempted",
        "edges_created",
        "edges_skipped",
        "triples_attempted",
        "triples_created",
        "triples_skipped",
    )
    if not isinstance(import_result, dict):
        raise FlowOutputValidationError("graph import flow output must include import_result")
    for key in counter_keys:
        value = import_result.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise FlowOutputValidationError(
                f"graph import flow output import_result.{key} must be a non-negative integer"
            )
    if not isinstance(import_result.get("errors"), list):
        raise FlowOutputValidationError("graph import flow output import_result.errors must be a list")
    return import_result


def _sanitize_import_error(error: Any) -> Dict[str, Any]:
    if not isinstance(error, dict):
        return {"kind": "import", "reason": "import_error"}
    sanitized = {
        key: value for key, value in error.items() if key in SAFE_IMPORT_ERROR_KEYS and isinstance(value, (str, int))
    }
    return sanitized or {"kind": "import", "reason": "import_error"}


def _format_import_warning(error: Dict[str, Any]) -> str:
    kind = error.get("kind", "import")
    reason = error.get("reason", "import_error")
    parts = ["import error" if kind == "import" else f"{kind} import error"]
    if "index" in error:
        parts.append(f"index={error['index']}")
    if "label" in error:
        parts.append(f"label={error['label']}")
    if "key" in error:
        parts.append(f"key={error['key']}")
    parts.append(f"reason={reason}")
    return " ".join(parts)


class GraphExtractService:
    def __init__(self, scheduler=None):
        self._scheduler = scheduler

    @property
    def scheduler(self):
        return self._scheduler or SchedulerSingleton.get_instance()

    def extract_sync(self, request: GraphExtractRequest) -> GraphExtractResponse:
        started = time.perf_counter()
        schema = normalize_schema(request.schema)
        extract_client_config = request.client_config if _schema_graph_name(schema) else None
        client_config_meta = _redact_client_config(apply_client_config(extract_client_config, schema=schema))
        example_prompt = request.example_prompt or prompt.extract_graph_prompt
        try:
            raw_result = self.scheduler.schedule_flow(
                FlowName.GRAPH_EXTRACT,
                schema,
                request.texts,
                example_prompt,
                request.extract_type,
                language=request.language,
                split_type=request.split_type,
                client_config=extract_client_config,
                content_type=request.content_type,
                max_parallel_chunks=request.max_parallel_chunks,
            )
        except Exception:
            log.exception("Graph extraction failed during scheduler execution")
            raise

        parsed_result = _parse_flow_json(raw_result, "Invalid graph extraction flow JSON")
        warnings = _pop_warnings(parsed_result)
        result = self._build_result(parsed_result, request.extract_type)
        if not request.options.include_warnings:
            warnings = []
        meta = (
            self._build_extract_meta(request, parsed_result, result, started, client_config_meta)
            if request.options.include_meta
            else {}
        )
        return GraphExtractResponse(status="succeeded", result=result, warnings=warnings, meta=meta)

    def _build_result(self, parsed_result: Dict[str, Any], extract_type: str) -> Dict[str, Any]:
        if extract_type == "triples":
            triples = parsed_result.get("triples")
            if not triples:
                triples = self._legacy_edges_to_triples(parsed_result.get("edges", []))
            return {"triples": triples}
        result = {
            "vertices": parsed_result.get("vertices", []),
            "edges": parsed_result.get("edges", []),
        }
        _validate_property_graph_result(result)
        return result

    def _legacy_edges_to_triples(self, edges: Any) -> List[Dict[str, Any]]:
        if not isinstance(edges, list):
            return []
        triples = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            start = edge.get("start", edge.get("outV"))
            end = edge.get("end", edge.get("inV"))
            edge_type = edge.get("type", edge.get("label"))
            if start is not None and end is not None and edge_type is not None:
                triples.append({"start": start, "type": edge_type, "end": end})
        return triples

    def _build_extract_meta(
        self,
        request: GraphExtractRequest,
        parsed_result: Dict[str, Any],
        result: Dict[str, Any],
        started: float,
        client_config_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        chunk_count = parsed_result.get("chunk_count")
        if chunk_count is None:
            chunk_count = (
                len(request.texts)
                if request.content_type == "chunks" and isinstance(request.texts, (list, tuple))
                else parsed_result.get("call_count")
            )
        max_parallel_chunks = parsed_result.get("max_parallel_chunks")
        if max_parallel_chunks is None:
            max_parallel_chunks = (
                min(request.max_parallel_chunks, chunk_count)
                if isinstance(chunk_count, int) and chunk_count >= 0
                else request.max_parallel_chunks
            )

        meta = {
            "extract_type": request.extract_type,
            "content_type": request.content_type,
            "language": request.language,
            "split_type": request.split_type,
            "text_count": 1 if request.content_type == "text" else 0,
            "chunk_count": chunk_count,
            "max_parallel_chunks": max_parallel_chunks,
            "vertex_count": _count_items(result, "vertices"),
            "edge_count": _count_items(result, "edges"),
            "triple_count": _count_items(result, "triples"),
            "call_count": parsed_result.get("call_count"),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        if client_config_meta:
            meta["client_config"] = client_config_meta
        return meta


class GraphImportService:
    def __init__(self, scheduler=None):
        self._scheduler = scheduler

    @property
    def scheduler(self):
        return self._scheduler or SchedulerSingleton.get_instance()

    def import_graph(self, request: GraphImportRequest) -> GraphImportResponse:
        if not request.write_to_graph:
            raise ValueError("write_to_graph must be True to confirm graph import")

        started = time.perf_counter()
        schema = normalize_schema(request.schema)
        graph_config = apply_client_config(request.client_config, schema=schema, align_graph_with_schema=True)
        client_config_meta = _redact_client_config(graph_config)
        try:
            raw_result = self.scheduler.schedule_flow(
                FlowName.IMPORT_GRAPH_DATA,
                request.data,
                schema,
                graph_config=graph_config,
            )
        except Exception:
            log.exception("Graph import failed during scheduler execution")
            raise

        parsed_result = _parse_flow_json(raw_result, "Invalid graph import flow JSON")
        warnings = _pop_warnings(parsed_result)
        import_result = _validate_import_result(parsed_result.get("import_result"))
        import_errors = [_sanitize_import_error(item) for item in import_result.get("errors", [])]
        import_result["errors"] = import_errors
        warnings.extend(_format_import_warning(item) for item in import_errors)
        status = _build_import_status(import_result)
        vertex_count = int(import_result["vertices_created"])
        edge_count = int(import_result["edges_created"])
        triple_count = int(import_result["triples_created"])
        updated_embeddings = False
        if request.options.update_vid_embeddings:
            try:
                self.scheduler.schedule_flow(FlowName.UPDATE_VID_EMBEDDINGS, graph_config=graph_config)
                updated_embeddings = True
            except Exception as exc:  # pylint: disable=broad-exception-caught
                log.warning("VID embedding update failed after graph import: %s", exc, exc_info=True)
                warnings.append("update_vid_embeddings failed")
                if status == "succeeded":
                    status = "partial"

        meta = {"duration_ms": int((time.perf_counter() - started) * 1000)}
        meta["import_result"] = import_result
        if client_config_meta:
            meta["client_config"] = client_config_meta
        return GraphImportResponse(
            status=status,
            vertex_count=vertex_count,
            edge_count=edge_count,
            triple_count=triple_count,
            updated_embeddings=updated_embeddings,
            warnings=warnings,
            meta=meta,
        )

    def import_extracted_graph(
        self,
        request: GraphExtractAndImportRequest,
        extract_response: GraphExtractResponse,
    ) -> GraphImportResponse:
        import_request = GraphImportRequest(
            schema=request.schema,
            data=extract_response.result,
            write_to_graph=True,
            client_config=request.client_config,
            options=request.import_options,
        )
        return self.import_graph(import_request)
