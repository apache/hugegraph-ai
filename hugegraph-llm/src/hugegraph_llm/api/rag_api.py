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
from contextlib import contextmanager

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
from hugegraph_llm.config import huge_settings, llm_settings, prompt
from hugegraph_llm.utils.graph_index_utils import get_vertex_details
from hugegraph_llm.utils.log import log

_GRAPH_CONFIG_FIELD_MAP = {
    "url": "graph_url",
    "graph": "graph_name",
    "user": "graph_user",
    "pwd": "graph_pwd",
    "gs": "graph_space",
}
_LLM_TYPE_FIELDS = ("chat_llm_type", "extract_llm_type", "text2gql_llm_type")
_LLM_CONFIG_FIELDS = _LLM_TYPE_FIELDS + (
    "openai_chat_api_key",
    "openai_chat_api_base",
    "openai_chat_language_model",
    "openai_chat_tokens",
    "openai_extract_api_key",
    "openai_extract_api_base",
    "openai_extract_language_model",
    "openai_extract_tokens",
    "openai_text2gql_api_key",
    "openai_text2gql_api_base",
    "openai_text2gql_language_model",
    "openai_text2gql_tokens",
    "ollama_chat_host",
    "ollama_chat_port",
    "ollama_chat_language_model",
    "ollama_extract_host",
    "ollama_extract_port",
    "ollama_extract_language_model",
    "ollama_text2gql_host",
    "ollama_text2gql_port",
    "ollama_text2gql_language_model",
    "litellm_chat_api_key",
    "litellm_chat_api_base",
    "litellm_chat_language_model",
    "litellm_chat_tokens",
    "litellm_extract_api_key",
    "litellm_extract_api_base",
    "litellm_extract_language_model",
    "litellm_extract_tokens",
    "litellm_text2gql_api_key",
    "litellm_text2gql_api_base",
    "litellm_text2gql_language_model",
    "litellm_text2gql_tokens",
)
_EMBEDDING_CONFIG_FIELDS = (
    "embedding_type",
    "openai_embedding_api_key",
    "openai_embedding_api_base",
    "openai_embedding_model",
    "ollama_embedding_host",
    "ollama_embedding_port",
    "ollama_embedding_model",
    "litellm_embedding_api_key",
    "litellm_embedding_api_base",
    "litellm_embedding_model",
)
_RERANKER_CONFIG_FIELDS = (
    "reranker_type",
    "reranker_api_key",
    "reranker_model",
    "cohere_base_url",
)


def _snapshot_settings(settings, fields):
    return {field: getattr(settings, field) for field in fields}


def _restore_settings(settings, values):
    for field, value in values.items():
        setattr(settings, field, value)


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
    @contextmanager
    def request_graph_config(req):
        # FIXME: per-request graph overrides still mutate process-global huge_settings.
        # A global lock would serialize long RAG/Text2Gremlin requests, so the real
        # fix is passing graph config through request-scoped flow/operator context.
        original_values = _snapshot_settings(huge_settings, _GRAPH_CONFIG_FIELD_MAP.values())
        try:
            client_config = getattr(req, "client_config", None)
            if client_config is not None:
                for request_field, settings_field in _GRAPH_CONFIG_FIELD_MAP.items():
                    if request_field in client_config.model_fields_set:
                        setattr(huge_settings, settings_field, getattr(client_config, request_field))
            yield
        finally:
            _restore_settings(huge_settings, original_values)

    @router.post("/rag", status_code=status.HTTP_200_OK)
    def rag_answer_api(req: RAGRequest):
        with request_graph_config(req):
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
            with request_graph_config(req):
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

    # TODO: restructure the implement of llm to three types, like "/config/chat_llm"
    @router.post("/config/llm", status_code=status.HTTP_201_CREATED)
    def llm_config_api(req: LLMConfigRequest):
        original_values = _snapshot_settings(llm_settings, _LLM_CONFIG_FIELDS)
        try:
            llm_settings.chat_llm_type = req.llm_type
            llm_settings.extract_llm_type = req.llm_type
            llm_settings.text2gql_llm_type = req.llm_type

            if req.llm_type in ("openai", "litellm"):
                res = apply_llm_conf(
                    req.api_key,
                    req.api_base,
                    req.language_model,
                    req.max_tokens,
                    origin_call="http",
                )
            else:
                res = apply_llm_conf(req.host, req.port, req.language_model, None, origin_call="http")
            return generate_response(RAGResponse(status_code=res, message="Missing Value"))
        except Exception:
            _restore_settings(llm_settings, original_values)
            raise

    @router.post("/config/embedding", status_code=status.HTTP_201_CREATED)
    def embedding_config_api(req: LLMConfigRequest):
        original_values = _snapshot_settings(llm_settings, _EMBEDDING_CONFIG_FIELDS)
        try:
            llm_settings.embedding_type = req.llm_type

            if req.llm_type in ("openai", "litellm"):
                res = apply_embedding_conf(req.api_key, req.api_base, req.language_model, origin_call="http")
            else:
                res = apply_embedding_conf(req.host, req.port, req.language_model, origin_call="http")
            return generate_response(RAGResponse(status_code=res, message="Missing Value"))
        except Exception:
            _restore_settings(llm_settings, original_values)
            raise

    @router.post("/config/rerank", status_code=status.HTTP_201_CREATED)
    def rerank_config_api(req: RerankerConfigRequest):
        original_values = _snapshot_settings(llm_settings, _RERANKER_CONFIG_FIELDS)
        try:
            llm_settings.reranker_type = req.reranker_type

            if req.reranker_type == "cohere":
                res = apply_reranker_conf(req.api_key, req.reranker_model, req.cohere_base_url, origin_call="http")
            elif req.reranker_type == "siliconflow":
                res = apply_reranker_conf(req.api_key, req.reranker_model, None, origin_call="http")
            else:
                res = status.HTTP_501_NOT_IMPLEMENTED
            return generate_response(RAGResponse(status_code=res, message="Missing Value"))
        except Exception:
            _restore_settings(llm_settings, original_values)
            raise

    @router.post("/text2gremlin", status_code=status.HTTP_200_OK)
    def text2gremlin_api(req: GremlinGenerateRequest):
        try:
            with request_graph_config(req):
                # Basic parameter validation: empty query => 400
                if not req.query or not str(req.query).strip():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Query must not be empty.",
                    )

                output_types_str_list = None
                if req.output_types:
                    output_types_str_list = [ot.value for ot in req.output_types]

                response_dict = gremlin_generate_selective_func(
                    inp=req.query,
                    example_num=req.example_num,
                    schema_input=huge_settings.graph_name,
                    gremlin_prompt_input=req.gremlin_prompt,
                    requested_outputs=output_types_str_list,
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
