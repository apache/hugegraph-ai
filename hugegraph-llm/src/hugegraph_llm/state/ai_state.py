#  Licensed to the Apache Software Foundation (ASF) under one or more
#  contributor license agreements.  See the NOTICE file distributed with
#  this work for additional information regarding copyright ownership.
#  The ASF licenses this file to You under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance with
#  the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from pycgraph import CStatus, GParam

from hugegraph_llm.utils.log import log


class WkFlowInput(GParam):
    texts: Optional[Union[str, List[str]]] = None  # texts input used by ChunkSplit Node
    language: Optional[str] = None  # language configuration used by ChunkSplit Node
    split_type: Optional[str] = None  # split type used by ChunkSplit Node
    example_prompt: Optional[str] = None  # need by graph information extract
    schema: Optional[str] = None  # Schema information requeired by SchemaNode
    # Request-scoped HugeGraph connection; None falls back to global huge_settings.
    graph_client_config: Optional[Dict[str, Any]] = None
    data_json: Optional[Dict[str, Any]] = None
    extract_type: Optional[str] = None
    query_examples: Optional[Any] = None
    few_shot_schema: Optional[Any] = None
    # Fields related to PromptGenerate
    source_text: Optional[str] = None  # Original text
    scenario: Optional[str] = None  # Scenario description
    example_name: Optional[str] = None  # Example name
    # Fields for Text2Gremlin
    example_num: Optional[int] = None
    requested_outputs: Optional[List[str]] = None

    # RAG Flow related fields
    query: Optional[str] = None  # User query for RAG
    vector_search: Optional[bool] = None  # Enable vector search
    graph_search: Optional[bool] = None  # Enable graph search
    raw_answer: Optional[bool] = None  # Return raw answer
    vector_only_answer: Optional[bool] = None  # Vector only answer mode
    graph_only_answer: Optional[bool] = None  # Graph only answer mode
    graph_vector_answer: Optional[bool] = None  # Combined graph and vector answer
    graph_ratio: Optional[float] = None  # Graph ratio for merging
    rerank_method: Optional[str] = None  # Reranking method
    near_neighbor_first: Optional[bool] = None  # Near neighbor first flag
    custom_related_information: Optional[str] = None  # Custom related information
    answer_prompt: Optional[str] = None  # Answer generation prompt
    keywords_extract_prompt: Optional[str] = None  # Keywords extraction prompt
    gremlin_tmpl_num: Optional[int] = None  # Gremlin template number
    gremlin_prompt: Optional[str] = None  # Gremlin generation prompt
    max_graph_items: Optional[int] = None  # Maximum graph items
    topk_return_results: Optional[int] = None  # Top-k return results
    vector_dis_threshold: Optional[float] = None  # Vector distance threshold
    topk_per_keyword: Optional[int] = None  # Top-k per keyword
    max_keywords: Optional[int] = None
    max_items: Optional[int] = None

    # Semantic query related fields
    semantic_by: Optional[str] = None  # Semantic query method
    topk_per_query: Optional[int] = None  # Top-k per query

    # Graph query related fields
    max_deep: Optional[int] = None  # Maximum depth for graph traversal
    max_v_prop_len: Optional[int] = None  # Maximum vertex property length
    max_e_prop_len: Optional[int] = None  # Maximum edge property length
    prop_to_match: Optional[str] = None  # Property to match

    stream: Optional[bool] = None  # used for recognize stream mode

    # used for rag_recall api
    is_graph_rag_recall: bool = False
    is_vector_only: bool = False

    # used for build text2gremin index
    examples: Optional[List[Dict[str, str]]] = None

    def reset(self, _: CStatus) -> None:
        self.texts = None
        self.language = None
        self.split_type = None
        self.example_prompt = None
        self.schema = None
        self.graph_client_config = None
        self.data_json = None
        self.extract_type = None
        self.query_examples = None
        self.few_shot_schema = None
        # PromptGenerate related configuration
        self.source_text = None
        self.scenario = None
        self.example_name = None
        # Text2Gremlin related configuration
        self.example_num = None
        self.gremlin_prompt = None
        self.requested_outputs = None
        # RAG Flow related fields
        self.query = None
        self.vector_search = None
        self.graph_search = None
        self.raw_answer = None
        self.vector_only_answer = None
        self.graph_only_answer = None
        self.graph_vector_answer = None
        self.graph_ratio = None
        self.rerank_method = None
        self.near_neighbor_first = None
        self.custom_related_information = None
        self.answer_prompt = None
        self.keywords_extract_prompt = None
        self.gremlin_tmpl_num = None
        self.max_graph_items = None
        self.topk_return_results = None
        self.vector_dis_threshold = None
        self.topk_per_keyword = None
        self.max_keywords = None
        self.max_items = None
        # Semantic query related fields
        self.semantic_by = None
        self.topk_per_query = None
        # Graph query related fields
        self.max_deep = None
        self.max_v_prop_len = None
        self.max_e_prop_len = None
        self.prop_to_match = None
        self.stream = None

        self.examples = None
        self.is_graph_rag_recall = False
        self.is_vector_only = False


class WkFlowState(GParam):
    schema: Optional[str] = None  # schema message
    simple_schema: Optional[str] = None
    chunks: Optional[List[str]] = None
    edges: Optional[List[Any]] = None
    vertices: Optional[List[Any]] = None
    triples: Optional[List[Any]] = None
    call_count: Optional[int] = None

    keywords: Optional[List[str]] = None
    vector_result: Optional[Any] = None
    graph_result: Optional[Any] = None
    keywords_embeddings: Optional[Any] = None

    generated_extract_prompt: Optional[str] = None
    # Fields for Text2Gremlin results
    match_result: Optional[List[dict]] = None
    result: Optional[str] = None
    raw_result: Optional[str] = None
    template_exec_res: Optional[Any] = None
    raw_exec_res: Optional[Any] = None

    match_vids: Optional[Any] = None

    raw_answer: Optional[str] = None
    vector_only_answer: Optional[str] = None
    graph_only_answer: Optional[str] = None
    graph_vector_answer: Optional[str] = None

    merged_result: Optional[Any] = None

    vertex_num: Optional[int] = None
    edge_num: Optional[int] = None
    note: Optional[str] = None
    removed_vid_vector_num: Optional[int] = None
    added_vid_vector_num: Optional[int] = None
    raw_texts: Optional[List] = None
    query_examples: Optional[List] = None
    few_shot_schema: Optional[Dict] = None
    source_text: Optional[str] = None
    scenario: Optional[str] = None
    example_name: Optional[str] = None

    graph_ratio: Optional[float] = None
    query: Optional[str] = None
    vector_search: Optional[bool] = None
    graph_search: Optional[bool] = None
    max_graph_items: Optional[int] = None
    stream_generator: Optional[AsyncGenerator] = None

    graph_result_flag: Optional[int] = None
    vertex_degree_list: Optional[List] = None
    knowledge_with_degree: Optional[Dict] = None
    graph_context_head: Optional[str] = None

    embed_dim: Optional[int] = None
    is_graph_rag_recall: Optional[bool] = None

    def setup(self) -> CStatus:
        self.schema = None
        self.simple_schema = None
        self.chunks = None
        self.edges = None
        self.vertices = None
        self.triples = None
        self.call_count = None

        self.keywords = None
        self.vector_result = None
        self.graph_result = None
        self.keywords_embeddings = None

        self.generated_extract_prompt = None
        # Text2Gremlin results reset
        self.match_result = None
        self.result = None
        self.raw_result = None
        self.template_exec_res = None
        self.raw_exec_res = None

        self.raw_answer = None
        self.vector_only_answer = None
        self.graph_only_answer = None
        self.graph_vector_answer = None

        self.merged_result = None

        self.match_vids = None
        self.vertex_num = None
        self.edge_num = None
        self.note = None
        self.removed_vid_vector_num = None
        self.added_vid_vector_num = None

        self.raw_texts = None
        self.query_examples = None
        self.few_shot_schema = None
        self.source_text = None
        self.scenario = None
        self.example_name = None

        self.graph_ratio = None
        self.query = None
        self.vector_search = None
        self.graph_search = None
        self.max_graph_items = None

        self.stream_generator = None
        self.graph_result_flag = None
        self.vertex_degree_list = None
        self.knowledge_with_degree = None
        self.graph_context_head = None

        self.embed_dim = None
        self.is_graph_rag_recall = None
        return CStatus()

    def to_json(self):
        """
        Automatically returns a JSON-formatted dictionary of all non-None instance members,
        eliminating the need to manually maintain the member list.

        Returns:
            dict: A dictionary containing non-None instance members and their serialized values.
        """
        # Only export instance attributes (excluding methods and class attributes) whose values are not None
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_") and v is not None}

    # Implement a method that assigns keys from data_json as WkFlowState member variables
    def assign_from_json(self, data_json: dict):
        """
        Assigns each key in the input json object as a member variable of WkFlowState.
        """
        for k, v in data_json.items():
            if hasattr(self, k):
                setattr(self, k, v)
            else:
                log.warning("key %s should be a member of WkFlowState & type %s", k, type(v))
