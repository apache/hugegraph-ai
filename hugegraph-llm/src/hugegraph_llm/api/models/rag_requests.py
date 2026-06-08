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

from enum import Enum
from typing import List, Literal, Optional

from fastapi import Query
from pydantic import BaseModel, field_validator

from hugegraph_llm.config import prompt

LLMProviderType = Literal["openai", "ollama/local", "litellm"]
RerankerProviderType = Literal["cohere", "siliconflow"]


class GraphConfigRequest(BaseModel):
    url: str = Query("127.0.0.1:8080", description="hugegraph client url.")
    graph: str = Query("hugegraph", description="hugegraph client name.")
    user: str = Query("", description="hugegraph client user.")
    pwd: str = Query("", description="hugegraph client pwd.")
    gs: Optional[str] = None


class RAGRequest(BaseModel):
    query: str = Query(..., description="Query you want to ask")
    raw_answer: bool = Query(False, description="Use LLM to generate answer directly")
    vector_only: bool = Query(False, description="Use LLM to generate answer with vector")
    graph_only: bool = Query(True, description="Use LLM to generate answer with graph RAG only")
    graph_vector_answer: bool = Query(False, description="Use LLM to generate answer with vector & GraphRAG")
    graph_ratio: float = Query(0.5, description="The ratio of GraphRAG ans & vector ans")
    rerank_method: Literal["bleu", "reranker"] = Query("bleu", description="Method to rerank the results.")
    near_neighbor_first: bool = Query(False, description="Prioritize near neighbors in the search results.")
    custom_priority_info: str = Query("", description="Custom information to prioritize certain results.")
    # Graph Configs
    max_graph_items: int = Query(30, description="Maximum number of items for GQL queries in graph.")
    topk_return_results: int = Query(20, description="Number of sorted results to return finally.")
    vector_dis_threshold: float = Query(
        0.9,
        description="Threshold for vector similarity\
                                         (results greater than this will be ignored).",
    )
    topk_per_keyword: int = Query(
        1,
        description="TopK results returned for each keyword \
                                   extracted from the query, by default only the most similar one is returned.",
    )
    client_config: Optional[GraphConfigRequest] = Query(None, description="hugegraph server config.")

    # Keep prompt params in the end
    answer_prompt: Optional[str] = Query(prompt.answer_prompt, description="Prompt to guide the answer generation.")
    keywords_extract_prompt: Optional[str] = Query(
        prompt.keywords_extract_prompt,
        description="Prompt for extracting keywords from query.",
    )
    gremlin_tmpl_num: int = Query(1, description="Number of Gremlin templates to use.")
    gremlin_prompt: Optional[str] = Query(
        prompt.gremlin_generate_prompt,
        description="Prompt for the Text2Gremlin query.",
    )


# TODO: import the default value of prompt.* dynamically
class GraphRAGRequest(BaseModel):
    query: str = Query(..., description="Query you want to ask")
    # Graph Configs
    max_graph_items: int = Query(30, description="Maximum number of items for GQL queries in graph.")
    topk_return_results: int = Query(20, description="Number of sorted results to return finally.")
    vector_dis_threshold: float = Query(
        0.9,
        description="Threshold for vector similarity \
                                        (results greater than this will be ignored).",
    )
    topk_per_keyword: int = Query(
        1,
        description="TopK results returned for each keyword extracted\
                                    from the query, by default only the most similar one is returned.",
    )

    client_config: Optional[GraphConfigRequest] = Query(None, description="hugegraph server config.")
    get_vertex_only: bool = Query(False, description="return only keywords & vertex (early stop).")

    gremlin_tmpl_num: int = Query(
        1,
        description="Number of Gremlin templates to use. If num <=0 means template is not provided",
    )
    rerank_method: Literal["bleu", "reranker"] = Query("bleu", description="Method to rerank the results.")
    near_neighbor_first: bool = Query(False, description="Prioritize near neighbors in the search results.")
    custom_priority_info: str = Query("", description="Custom information to prioritize certain results.")
    gremlin_prompt: Optional[str] = Query(
        prompt.gremlin_generate_prompt,
        description="Prompt for the Text2Gremlin query.",
    )


class LLMConfigRequest(BaseModel):
    llm_type: LLMProviderType
    # The common parameters shared by OpenAI, LiteLLM,
    # and OLLAMA platforms.
    api_key: str
    api_base: str
    language_model: str
    # Openai-only properties
    max_tokens: str = None
    # ollama-only properties
    # TODO: replace to url later
    host: str = None
    port: str = None


class RerankerConfigRequest(BaseModel):
    reranker_model: str
    reranker_type: RerankerProviderType
    api_key: str
    cohere_base_url: Optional[str] = None


class LogStreamRequest(BaseModel):
    admin_token: Optional[str] = None
    log_file: Optional[str] = "llm-server.log"


class GremlinOutputType(str, Enum):
    MATCH_RESULT = "match_result"
    TEMPLATE_GREMLIN = "template_gremlin"
    RAW_GREMLIN = "raw_gremlin"
    TEMPLATE_EXECUTION_RESULT = "template_execution_result"
    RAW_EXECUTION_RESULT = "raw_execution_result"


class GremlinGenerateRequest(BaseModel):
    query: str
    example_num: Optional[int] = Query(0, description="Number of Gremlin templates to use.(0 means no templates)")
    gremlin_prompt: Optional[str] = Query(
        prompt.gremlin_generate_prompt,
        description="Prompt for the Text2Gremlin query.",
    )
    client_config: Optional[GraphConfigRequest] = Query(None, description="hugegraph server config.")
    output_types: Optional[List[GremlinOutputType]] = Query(
        default=[GremlinOutputType.TEMPLATE_GREMLIN],
        description="""
        a list can contain "match_result","template_gremlin",
        "raw_gremlin","template_execution_result","raw_execution_result"
        You can specify which type of result do you need. Empty means all types.
        """,
    )

    @field_validator("gremlin_prompt")
    @classmethod
    def validate_prompt_placeholders(cls, v):
        if v is not None:
            required_placeholders = ["{query}", "{schema}", "{example}", "{vertices}"]
            missing = [p for p in required_placeholders if p not in v]
            if missing:
                raise ValueError(f"Prompt template is missing required placeholders: {', '.join(missing)}")
        return v
