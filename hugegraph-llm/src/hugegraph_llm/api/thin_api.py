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

import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, status
from pydantic import BaseModel

from hugegraph_llm.api.models.rag_requests import (
    GraphExtractRequest,
    GraphImportRequest,
    ValidatedVidEmbeddingsRefreshRequest,
    VidEmbeddingsRefreshRequest,
    VidEmbeddingsSearchRequest,
)
from hugegraph_llm.api.models.rag_response import ThinAPIResponse
from hugegraph_llm.config import admin_settings, huge_settings, index_settings, prompt, runtime_config_lock
from hugegraph_llm.config.admin_config import AdminConfig
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.scheduler import SchedulerSingleton
from hugegraph_llm.utils.log import log

thin_router = APIRouter()


def _generate_request_id() -> str:
    return f"req-{uuid4().hex[:12]}"


def _envelope_ok(
    data: Any,
    *,
    warnings: list[str] | None = None,
    next_actions: list[str] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "data": data,
        "error": None,
        "warnings": warnings or [],
        "next_actions": next_actions or [],
        "meta": {
            "request_id": request_id or _generate_request_id(),
            "duration_ms": 0,
        },
    }


def _envelope_err(
    error_type: str,
    message: str,
    *,
    suggestion: str | None = None,
    details: Any = None,
    request_id: str | None = None,
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
            "request_id": request_id or _generate_request_id(),
            "duration_ms": 0,
        },
    }


def _wrap_flow_call(flow_name: FlowName, *args: Any, **kwargs: Any) -> dict[str, Any]:
    start = time.perf_counter()
    request_id = _generate_request_id()
    try:
        result = SchedulerSingleton.get_instance().schedule_flow(flow_name, *args, **kwargs)
        envelope = _envelope_ok(result, request_id=request_id)
        envelope["meta"]["duration_ms"] = (time.perf_counter() - start) * 1000.0
        return envelope
    except Exception as exc:
        log.error(
            "Thin API flow execution failed: request_id=%s flow=%s exception_type=%s",
            request_id,
            flow_name.value,
            type(exc).__name__,
        )
        envelope = _envelope_err(
            "FLOW_EXECUTION_FAILED",
            "An internal error occurred during flow execution.",
            suggestion="Check HugeGraph-AI service logs for details.",
            request_id=request_id,
        )
        envelope["meta"]["duration_ms"] = (time.perf_counter() - start) * 1000.0
        return envelope


def _thin_write_disabled() -> dict[str, Any] | None:
    """Keep legacy write endpoints fail-closed unless authenticated and enabled."""
    login_enabled = admin_settings.is_login_enabled()
    writes_enabled = AdminConfig().hugegraph_llm_enable_thin_writes
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


def _effective_graphspace(graphspace: str | None) -> str:
    # Match the client's default-space identity without changing configuration
    # or index paths. Non-default names retain their exact routing semantics.
    return graphspace if graphspace and graphspace.strip() else "DEFAULT"


def _refresh_vid_embeddings(req: VidEmbeddingsRefreshRequest):
    if blocked := _thin_write_disabled():
        return blocked
    # Keep target validation and flow execution atomic with respect to runtime
    # graph configuration updates. The flow reads the same shared settings.
    with runtime_config_lock:
        expected_fields = {"expected_graph", "expected_graphspace"}
        supplied_fields = req.model_fields_set & expected_fields
        if supplied_fields and (
            supplied_fields != expected_fields
            or req.expected_graph != huge_settings.graph_name
            or _effective_graphspace(req.expected_graphspace) != _effective_graphspace(huge_settings.graph_space)
        ):
            return _envelope_err(
                "VALIDATION_ERROR",
                "Expected graph and graphspace must match the configured HugeGraph target.",
                suggestion="Provide both expected_graph and expected_graphspace matching the AI service target.",
            )
        return _wrap_flow_call(FlowName.UPDATE_VID_EMBEDDINGS)


@thin_router.post("/vid-embeddings/refresh", status_code=status.HTTP_200_OK, response_model=ThinAPIResponse)
def vid_embeddings_refresh_api(req: VidEmbeddingsRefreshRequest):
    """Keep empty requests compatible with authenticated legacy callers."""
    return _refresh_vid_embeddings(req)


@thin_router.post("/v1/vid-embeddings/refresh", status_code=status.HTTP_200_OK, response_model=ThinAPIResponse)
def validated_vid_embeddings_refresh_api(req: ValidatedVidEmbeddingsRefreshRequest):
    """Require target validation on a route that old replicas cannot execute."""
    return _refresh_vid_embeddings(req)


@thin_router.get("/vid-embeddings/refresh-capabilities", status_code=status.HTTP_200_OK, response_model=ThinAPIResponse)
def vid_embeddings_refresh_capabilities_api():
    """Keep discovery compatible; the versioned POST enforces validation."""
    return _envelope_ok({"protocol_version": 1})


@thin_router.post("/v1/vid-embeddings/search", status_code=status.HTTP_200_OK, response_model=ThinAPIResponse)
def vid_embeddings_search_api(req: VidEmbeddingsSearchRequest):
    """Search indexed VID embeddings for the configured (graphspace, graph) target."""
    start = time.perf_counter()
    request_id = _generate_request_id()
    query_text = req.query.strip()
    if not query_text:
        return _envelope_err(
            "VALIDATION_ERROR",
            "query must not be empty.",
            suggestion="Provide a non-empty natural language query or entity name.",
            request_id=request_id,
        )

    with runtime_config_lock:
        target_graph = huge_settings.graph_name
        target_graphspace = _effective_graphspace(huge_settings.graph_space)
        if req.expected_graph != target_graph or _effective_graphspace(req.expected_graphspace) != target_graphspace:
            return _envelope_err(
                "VALIDATION_ERROR",
                "Expected graph and graphspace must match the configured HugeGraph target.",
                suggestion="Provide expected_graph and expected_graphspace matching the AI service target.",
                request_id=request_id,
            )

        try:
            from hugegraph_llm.models.embeddings.init_embedding import (  # pylint: disable=import-outside-toplevel
                Embeddings,
            )
            from hugegraph_llm.operators.index_op.build_semantic_index import (  # pylint: disable=import-outside-toplevel
                read_vid_index_meta,
                vid_index_name_parts,
            )
            from hugegraph_llm.utils.vector_index_utils import (  # pylint: disable=import-outside-toplevel
                get_vector_index_class,
            )

            vector_index_class = get_vector_index_class(index_settings.cur_vector_index)
            embedding = Embeddings().get_embedding()
            index_parts = vid_index_name_parts(target_graph, target_graphspace)
            if not vector_index_class.exist(*index_parts):
                meta = read_vid_index_meta(target_graph, target_graphspace)
                envelope = _envelope_ok(
                    {
                        "vids": [],
                        "count": 0,
                        "query": query_text,
                        "top_k": req.top_k,
                        "index_generation": meta.get("index_generation", 0),
                        "refreshed_at": meta.get("refreshed_at"),
                        "graph": target_graph,
                        "graphspace": target_graphspace,
                    },
                    request_id=request_id,
                )
                envelope["meta"]["duration_ms"] = (time.perf_counter() - start) * 1000.0
                return envelope
            vid_index = vector_index_class.from_name(embedding.get_embedding_dim(), *index_parts, read_only=True)
            query_vector = embedding.get_text_embedding(query_text)
            raw_results = vid_index.search(query_vector, top_k=req.top_k) or []
            seen: set[Any] = set()
            ranked_vids: list[Any] = []
            for item in raw_results:
                if item not in seen:
                    seen.add(item)
                    ranked_vids.append(item)
                    if len(ranked_vids) >= req.top_k:
                        break
            meta = read_vid_index_meta(target_graph, target_graphspace)
            envelope = _envelope_ok(
                {
                    "vids": ranked_vids,
                    "count": len(ranked_vids),
                    "query": query_text,
                    "top_k": req.top_k,
                    "index_generation": meta.get("index_generation", 0),
                    "refreshed_at": meta.get("refreshed_at"),
                    "graph": target_graph,
                    "graphspace": target_graphspace,
                },
                request_id=request_id,
            )
            envelope["meta"]["duration_ms"] = (time.perf_counter() - start) * 1000.0
            return envelope
        except Exception as exc:  # pylint: disable=broad-except
            log.error(
                "VID embedding search failed: request_id=%s exception_type=%s",
                request_id,
                type(exc).__name__,
            )
            envelope = _envelope_err(
                "FLOW_EXECUTION_FAILED",
                "An internal error occurred during VID embedding search.",
                suggestion="Check HugeGraph-AI service logs and ensure VID embeddings have been refreshed.",
                request_id=request_id,
            )
            envelope["meta"]["duration_ms"] = (time.perf_counter() - start) * 1000.0
            return envelope


@thin_router.get("/graph-index-info", status_code=status.HTTP_200_OK, response_model=ThinAPIResponse)
def graph_index_info_api():
    return _wrap_flow_call(FlowName.GET_GRAPH_INDEX_INFO)


class RetrieveContextRequest(BaseModel):
    query: str = ""
    mode: str = "hybrid"
    top_k: int = 10
    seed_ids: list[Any] | None = None
    expected_graph: str | None = None
    expected_graphspace: str | None = None


@thin_router.post("/v1/retrieve-context", status_code=status.HTTP_200_OK, response_model=ThinAPIResponse)
def retrieve_context_api(req: RetrieveContextRequest):
    """Retrieve bounded, provenance-tagged graph/vector/hybrid evidence."""
    start = time.perf_counter()
    request_id = _generate_request_id()
    if req.mode not in {"graph", "vector", "hybrid"}:
        return _envelope_err(
            "VALIDATION_ERROR",
            f"Unsupported retrieval mode: {req.mode!r}; expected graph, vector, or hybrid.",
            request_id=request_id,
        )
    if req.mode == "graph" and not req.seed_ids:
        return _envelope_err(
            "VALIDATION_ERROR",
            "seed_ids is required for mode='graph'.",
            request_id=request_id,
        )
    if req.mode in {"vector", "hybrid"} and not req.query.strip():
        return _envelope_err(
            "VALIDATION_ERROR",
            "query must not be empty for vector or hybrid retrieval.",
            request_id=request_id,
        )

    with runtime_config_lock:
        target_graph = huge_settings.graph_name
        target_graphspace = _effective_graphspace(huge_settings.graph_space)
        cur_vector_index = index_settings.cur_vector_index
        connection = {
            "url": huge_settings.graph_url,
            "graph": target_graph,
            "user": huge_settings.graph_user,
            "pwd": huge_settings.graph_pwd,
            "graphspace": huge_settings.graph_space,
        }
    if req.expected_graph != target_graph or _effective_graphspace(req.expected_graphspace) != target_graphspace:
        return _envelope_err(
            "VALIDATION_ERROR",
            "Expected graph and graphspace must match the configured HugeGraph target.",
            request_id=request_id,
        )

    try:
        from hugegraph_llm.operators.index_op.build_semantic_index import (  # pylint: disable=import-outside-toplevel
            read_vid_index_meta,
            vid_index_name_parts,
        )
        from hugegraph_llm.retrieval import retrieve_evidence_context  # pylint: disable=import-outside-toplevel
        from hugegraph_llm.utils.hugegraph_utils import get_hg_client  # pylint: disable=import-outside-toplevel

        client = get_hg_client(connection=connection)
        meta = read_vid_index_meta(target_graph, target_graphspace)
        vector_search_fn = None
        if req.mode in {"vector", "hybrid"}:
            from hugegraph_llm.models.embeddings.init_embedding import (  # pylint: disable=import-outside-toplevel
                Embeddings,
            )
            from hugegraph_llm.utils.vector_index_utils import (  # pylint: disable=import-outside-toplevel
                get_vector_index_class,
            )

            vector_index_class = get_vector_index_class(cur_vector_index)
            index_parts = vid_index_name_parts(target_graph, target_graphspace)
            if vector_index_class.exist(*index_parts):
                embedding = Embeddings().get_embedding()
                embed_dim = embedding.get_embedding_dim()
                vid_index = vector_index_class.from_name(embed_dim, *index_parts, read_only=True)

                def _vector_search(q: str, k: int):
                    return vid_index.search(embedding.get_text_embedding(q), top_k=k) or []

                vector_search_fn = _vector_search

        result = retrieve_evidence_context(
            query=req.query,
            mode=req.mode,
            top_k=max(1, min(50, int(req.top_k))),
            seed_ids=req.seed_ids,
            graph_target={"graph": target_graph, "graphspace": target_graphspace},
            graph_api=client.graph(),
            traverser_api=client.traverser(),
            vector_search_fn=vector_search_fn,
            vid_index_meta=meta,
        )
        warnings = [
            f"{err.get('stage', 'unknown')}: {err.get('error_type', 'Error')} (count={err.get('count', 1)})"
            for err in result.get("partial_errors", [])
        ]
        envelope = _envelope_ok(result, warnings=warnings, request_id=request_id)
        envelope["meta"]["duration_ms"] = (time.perf_counter() - start) * 1000.0
        return envelope
    except Exception as exc:  # pylint: disable=broad-except
        log.error("Context retrieval failed: request_id=%s exception_type=%s", request_id, type(exc).__name__)
        envelope = _envelope_err(
            "FLOW_EXECUTION_FAILED",
            "An internal error occurred during context retrieval.",
            request_id=request_id,
        )
        envelope["meta"]["duration_ms"] = (time.perf_counter() - start) * 1000.0
        return envelope
