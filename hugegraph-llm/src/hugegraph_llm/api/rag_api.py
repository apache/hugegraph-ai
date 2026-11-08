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
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, status

from hugegraph_llm.api.exceptions.rag_exceptions import generate_response
from hugegraph_llm.api.models.rag_requests import (
    GraphConfigRequest,
    GraphRAGRequest,
    GremlinGenerateRequest,
    LLMConfigRequest,
    RAGRequest,
    RerankerConfigRequest,
)
from hugegraph_llm.api.models.rag_response import RAGResponse
from hugegraph_llm.config import huge_settings, prompt
from hugegraph_llm.utils.graph_index_utils import get_vertex_details
from hugegraph_llm.utils.log import log

_GRAPH_CONFIG_FIELD_MAP = {
    "url": "graph_url",
    "graph": "graph_name",
    "user": "graph_user",
    "pwd": "graph_pwd",
    "gs": "graph_space",
}


def _request_graph_connection(req):
    client_config = getattr(req, "client_config", None)
    values = {
        "url": huge_settings.graph_url,
        "graph": huge_settings.graph_name,
        "user": huge_settings.graph_user,
        "pwd": huge_settings.graph_pwd,
        "graphspace": huge_settings.graph_space,
    }
    if client_config is None:
        return values
    if "url" in client_config.model_fields_set:
        if _normalize_graph_url(client_config.url) != _normalize_graph_url(values["url"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request graph URL must match the configured HugeGraph URL.",
            )
    configured_targets = {
        "graph": values["graph"],
        "gs": values["graphspace"],
    }
    for request_field, configured_value in configured_targets.items():
        if (
            request_field in client_config.model_fields_set
            and getattr(client_config, request_field) != configured_value
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Request {request_field} must match the configured HugeGraph target.",
            )
    configured_credentials = {
        "user": values["user"],
        "pwd": values["pwd"],
    }
    for request_field, configured_value in configured_credentials.items():
        if (
            request_field in client_config.model_fields_set
            and getattr(client_config, request_field) != configured_value
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Request {request_field} must match the configured HugeGraph credentials.",
            )
    for request_field in _GRAPH_CONFIG_FIELD_MAP:
        if request_field == "url":
            continue
        if request_field in client_config.model_fields_set:
            connection_field = "graphspace" if request_field == "gs" else request_field
            values[connection_field] = getattr(client_config, request_field)
    return values


def _normalize_graph_url(url: str) -> str:
    raw_url = str(url).strip()
    if "://" not in raw_url:
        raw_url = f"http://{raw_url}"
    try:
        parsed = urlsplit(raw_url)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("not an absolute HTTP(S) URL")
        port = parsed.port
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise ValueError("missing hostname")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Graph URL must be a valid absolute HTTP(S) URL.",
        ) from exc
    authority = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 80 if parsed.scheme.lower() == "http" else 443
    if port is not None and port != default_port:
        authority += f":{port}"
    return f"{parsed.scheme.lower()}://{authority}{parsed.path.rstrip('/')}"


# pylint: disable=too-many-statements
def rag_http_api(
    router: APIRouter,
    rag_answer_func,
    graph_rag_recall_func,
    apply_graph_conf,
    apply_llm_conf,
    apply_embedding_conf,
    apply_reranker_conf,
    gremlin_generate_selective_func,
):
    @router.post("/rag", status_code=status.HTTP_200_OK)
    def rag_answer_api(req: RAGRequest):
        # client_config on /rag is accepted for request compatibility but ignored
        # here. Matching/mismatch request-scoped config belongs to a later llm
        # change; this path must not reject the field and must not mutate
        # process-global huge_settings.
        # Basic parameter validation: empty query => 400
        if not req.query or not str(req.query).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query must not be empty.",
            )

        result = rag_answer_func(
            text=req.query,
            raw_answer=req.raw_answer,
            vector_only_answer=req.vector_only,
            graph_only_answer=req.graph_only,
            graph_vector_answer=req.graph_vector_answer,
            graph_ratio=req.graph_ratio,
            rerank_method=req.rerank_method,
            near_neighbor_first=req.near_neighbor_first,
            gremlin_tmpl_num=req.gremlin_tmpl_num,
            max_graph_items=req.max_graph_items,
            topk_return_results=req.topk_return_results,
            vector_dis_threshold=req.vector_dis_threshold,
            topk_per_keyword=req.topk_per_keyword,
            # Keep prompt params in the end
            custom_related_information=req.custom_priority_info,
            answer_prompt=req.answer_prompt or prompt.answer_prompt,
            keywords_extract_prompt=req.keywords_extract_prompt or prompt.keywords_extract_prompt,
            gremlin_prompt=req.gremlin_prompt or prompt.gremlin_generate_prompt,
        )
        # TODO: we need more info in the response for users to understand the query logic
        return {
            "query": req.query,
            **{
                key: value
                for key, value in zip(
                    ["raw_answer", "vector_only", "graph_only", "graph_vector_answer"],
                    result,
                )
                if getattr(req, key)
            },
        }

    @router.post("/rag/graph", status_code=status.HTTP_200_OK)
    def graph_rag_recall_api(req: GraphRAGRequest):
        try:
            # client_config on /rag/graph is accepted for request compatibility
            # but ignored here. Do not reject the field or mutate huge_settings.
            # Basic parameter validation: empty query => 400
            if not req.query or not str(req.query).strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Query must not be empty.",
                )

            result = graph_rag_recall_func(
                query=req.query,
                max_graph_items=req.max_graph_items,
                topk_return_results=req.topk_return_results,
                vector_dis_threshold=req.vector_dis_threshold,
                topk_per_keyword=req.topk_per_keyword,
                gremlin_tmpl_num=req.gremlin_tmpl_num,
                rerank_method=req.rerank_method,
                near_neighbor_first=req.near_neighbor_first,
                custom_related_information=req.custom_priority_info,
                gremlin_prompt=req.gremlin_prompt or prompt.gremlin_generate_prompt,
                get_vertex_only=req.get_vertex_only,
            )

            if req.get_vertex_only:
                vertex_details = get_vertex_details(result["match_vids"], result)
                if vertex_details:
                    result["match_vids"] = vertex_details

            if isinstance(result, dict):
                params = [
                    "query",
                    "keywords",
                    "match_vids",
                    "graph_result_flag",
                    "gremlin",
                    "graph_result",
                    "vertex_degree_list",
                ]
                user_result = {key: result[key] for key in params if key in result}
                return {"graph_recall": user_result}
            return {"graph_recall": json.dumps(result)}

        except HTTPException as e:
            raise e
        except TypeError as e:
            log.error("TypeError in graph_rag_recall_api: %s", e)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
        except Exception as e:
            log.error("Unexpected error occurred: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred.",
            ) from e

    @router.post("/config/graph", status_code=status.HTTP_201_CREATED)
    def graph_config_api(req: GraphConfigRequest):
        # Accept status code
        res = apply_graph_conf(req.url, req.graph, req.user, req.pwd, req.gs, origin_call="http")
        return generate_response(RAGResponse(status_code=res, message="Missing Value"))

    def save_model(callback, *args, **kwargs):
        try:
            res = callback(*args, origin_call="http", **kwargs)
        except (ValueError, TypeError):
            raise HTTPException(
                400, detail="Invalid configuration. Check the fields and destination/key pairing."
            ) from None
        except OSError:
            raise HTTPException(503, detail="Configuration could not be saved. Check storage permissions.") from None
        if not 200 <= res < 300:
            raise HTTPException(400, detail="Configuration was not saved.")
        return {"message": "Configuration saved."}

    @router.post("/config/llm", status_code=status.HTTP_201_CREATED)
    def llm_config_api(req: LLMConfigRequest):
        key, base = (req.host, req.port) if req.llm_type == "ollama/local" else (req.api_key, req.api_base)
        return save_model(
            apply_llm_conf,
            req.role,
            key,
            base,
            req.language_model,
            req.max_tokens,
            clear_api_key=req.clear_api_key,
            provider=req.llm_type,
        )

    @router.post("/config/embedding", status_code=status.HTTP_201_CREATED)
    def embedding_config_api(req: LLMConfigRequest):
        key, base = (req.host, req.port) if req.llm_type == "ollama/local" else (req.api_key, req.api_base)
        return save_model(
            apply_embedding_conf, key, base, req.language_model, clear_api_key=req.clear_api_key, provider=req.llm_type
        )

    @router.post("/config/rerank", status_code=status.HTTP_201_CREATED)
    def rerank_config_api(req: RerankerConfigRequest):
        return save_model(
            apply_reranker_conf,
            req.api_key,
            req.reranker_model,
            req.cohere_base_url,
            clear_api_key=req.clear_api_key,
            provider=req.reranker_type,
        )

    @router.post("/config/model/{role}/test")
    def test_model_config_api(role: Literal["chat", "extract", "text2gql", "embedding", "reranker"]):
        from hugegraph_llm.demo.rag_demo.configs_block import test_saved_model

        try:
            test_saved_model(role)
        except Exception as exc:
            raise HTTPException(
                502, detail=f"Connection test failed ({type(exc).__name__}). Saved configuration is unchanged."
            ) from None
        return {"message": "Connection test successful."}

    @router.post("/config/llm/{role}/use-chat")
    def inherit_chat_api(role: Literal["extract", "text2gql"]):
        from hugegraph_llm.demo.rag_demo.configs_block import use_chat_connection

        return save_model(use_chat_connection, role, True)

    @router.post("/text2gremlin", status_code=status.HTTP_200_OK)
    def text2gremlin_api(req: GremlinGenerateRequest):
        try:
            # Basic parameter validation: empty query => 400
            if not req.query or not str(req.query).strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Query must not be empty.",
                )

            output_types_str_list = None
            if req.output_types:
                output_types_str_list = [ot.value for ot in req.output_types]

            graph_connection = _request_graph_connection(req)
            response_dict = gremlin_generate_selective_func(
                inp=req.query,
                example_num=req.example_num,
                schema_input=graph_connection["graph"],
                gremlin_prompt_input=req.gremlin_prompt,
                requested_outputs=output_types_str_list,
                graph_client_config=graph_connection,
            )
            return response_dict
        except HTTPException as e:
            raise e
        except Exception as e:
            log.error("Error in text2gremlin_api: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred during Gremlin generation.",
            ) from e
