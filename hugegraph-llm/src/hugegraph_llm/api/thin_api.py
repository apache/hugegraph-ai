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

import os
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, status

from hugegraph_llm.api.models.rag_requests import (
    GraphExtractRequest,
    GraphImportRequest,
    VidEmbeddingsRefreshRequest,
)
from hugegraph_llm.api.models.rag_response import ThinAPIResponse
from hugegraph_llm.config import admin_settings, prompt
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.scheduler import SchedulerSingleton
from hugegraph_llm.utils.log import log

thin_router = APIRouter()


def _generate_request_id() -> str:
    return f"req-{uuid4().hex[:12]}"


def _envelope_ok(
    data: Any, *, warnings: list[str] | None = None, next_actions: list[str] | None = None
) -> dict[str, Any]:
    return {
        "ok": True,
        "data": data,
        "error": None,
        "warnings": warnings or [],
        "next_actions": next_actions or [],
        "meta": {
            "request_id": _generate_request_id(),
            "duration_ms": 0,
        },
    }


def _envelope_err(
    error_type: str, message: str, *, suggestion: str | None = None, details: Any = None
) -> dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": {
            "type": error_type,
            "message": message,
            "suggestion": suggestion,
            "retryable": False,
            "source": "hugegraph-llm",
            "details": details if details is not None else {},
        },
        "warnings": [],
        "next_actions": [],
        "meta": {
            "request_id": _generate_request_id(),
            "duration_ms": 0,
        },
    }


def _wrap_flow_call(flow_name: FlowName, *args: Any, **kwargs: Any) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        result = SchedulerSingleton.get_instance().schedule_flow(flow_name, *args, **kwargs)
        envelope = _envelope_ok(result)
        envelope["meta"]["duration_ms"] = (time.perf_counter() - start) * 1000.0
        return envelope
    except Exception as exc:
        log.error("Thin API flow execution failed: %s", exc, exc_info=True)
        envelope = _envelope_err(
            "FLOW_EXECUTION_FAILED",
            "An internal error occurred during flow execution.",
            suggestion="Check HugeGraph-AI service logs for details.",
        )
        envelope["meta"]["duration_ms"] = (time.perf_counter() - start) * 1000.0
        return envelope


def _thin_write_disabled() -> dict[str, Any] | None:
    """Keep legacy write endpoints fail-closed unless authenticated and enabled."""
    login_enabled = str(admin_settings.enable_login).strip().lower() == "true"
    configured_write_flag = os.getenv("HUGEGRAPH_LLM_ENABLE_THIN_WRITES", "false")
    writes_enabled = str(configured_write_flag).strip().lower() == "true"
    if login_enabled and writes_enabled:
        return None
    return _envelope_err(
        "FEATURE_DISABLED",
        "Legacy Thin API writes are disabled.",
        suggestion=(
            "Set ENABLE_LOGIN=true and HUGEGRAPH_LLM_ENABLE_THIN_WRITES=true "
            "only for authenticated internal deployments."
        ),
        details={
            "requires_login": True,
            "enable_env": "HUGEGRAPH_LLM_ENABLE_THIN_WRITES",
        },
    )


@thin_router.post("/graph-extract", status_code=status.HTTP_200_OK, response_model=ThinAPIResponse)
def graph_extract_api(req: GraphExtractRequest):
    return _wrap_flow_call(
        FlowName.GRAPH_EXTRACT,
        req.graph_schema,
        req.text,
        prompt.extract_graph_prompt if req.example_prompt is None else req.example_prompt,
        "property_graph",
        split_type="document",
        language=req.language,
    )


@thin_router.post("/graph-import", status_code=status.HTTP_200_OK, response_model=ThinAPIResponse)
def graph_import_api(req: GraphImportRequest):
    if blocked := _thin_write_disabled():
        return blocked
    return _wrap_flow_call(FlowName.IMPORT_GRAPH_DATA, req.data, req.graph_schema)


@thin_router.post("/vid-embeddings/refresh", status_code=status.HTTP_200_OK, response_model=ThinAPIResponse)
def vid_embeddings_refresh_api(_req: VidEmbeddingsRefreshRequest):
    if blocked := _thin_write_disabled():
        return blocked
    return _wrap_flow_call(FlowName.UPDATE_VID_EMBEDDINGS)


@thin_router.get("/graph-index-info", status_code=status.HTTP_200_OK, response_model=ThinAPIResponse)
def graph_index_info_api():
    return _wrap_flow_call(FlowName.GET_GRAPH_INDEX_INFO)
