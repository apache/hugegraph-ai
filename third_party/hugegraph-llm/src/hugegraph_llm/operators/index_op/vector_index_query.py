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


from typing import Any, Dict

from hugegraph_llm.config import huge_settings
from hugegraph_llm.indices.vector_index.base import VectorStoreBase
from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.utils.log import log


class VectorIndexQuery:
    def __init__(self, vector_index: type[VectorStoreBase], embedding: BaseEmbedding, topk: int = 3):
        self.embedding = embedding
        self.topk = topk
        self.vector_index = vector_index.from_name(embedding.get_embedding_dim(), huge_settings.graph_name, "chunks")

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        query = context.get("query")
        query_embedding = self.embedding.get_texts_embeddings([query])[0]
        # TODO: why set dis_threshold=2?
        results = self.vector_index.search(query_embedding, self.topk, dis_threshold=2)
        # TODO: check format results
        context["vector_result"] = results
        log.debug("KNOWLEDGE FROM VECTOR:\n%s", "\n".join(rel for rel in context["vector_result"]))
        return context
