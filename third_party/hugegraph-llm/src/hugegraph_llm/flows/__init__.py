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


class FlowName(str, Enum):
    RAG_GRAPH_ONLY = "rag_graph_only"
    RAG_VECTOR_ONLY = "rag_vector_only"
    TEXT2GREMLIN = "text2gremlin"
    BUILD_EXAMPLES_INDEX = "build_examples_index"
    BUILD_VECTOR_INDEX = "build_vector_index"
    GRAPH_EXTRACT = "graph_extract"
    IMPORT_GRAPH_DATA = "import_graph_data"
    UPDATE_VID_EMBEDDINGS = "update_vid_embeddings"
    GET_GRAPH_INDEX_INFO = "get_graph_index_info"
    BUILD_SCHEMA = "build_schema"
    PROMPT_GENERATE = "prompt_generate"
    RAG_RAW = "rag_raw"
    RAG_GRAPH_VECTOR = "rag_graph_vector"
