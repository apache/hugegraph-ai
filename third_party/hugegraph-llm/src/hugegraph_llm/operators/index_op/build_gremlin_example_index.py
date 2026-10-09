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


import asyncio
from typing import Any, Dict, List

from hugegraph_llm.indices.vector_index.base import VectorStoreBase
from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.utils.embedding_utils import get_embeddings_parallel


# FIXME: we need keep the logic same with build_semantic_index.py
class BuildGremlinExampleIndex:
    def __init__(
        self,
        embedding: BaseEmbedding,
        examples: List[Dict[str, str]],
        vector_index: type[VectorStoreBase],
    ):
        self.vector_index_name = "gremlin_examples"
        self.examples = examples
        self.embedding = embedding
        self.vector_index = vector_index

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if not self.examples:
            context["embed_dim"] = 0
            return context

        queries = [example["query"] for example in self.examples]
        # TODO: refactor function chain async to avoid blocking
        examples_embedding = asyncio.run(get_embeddings_parallel(self.embedding, queries))

        if not examples_embedding:
            raise ValueError(f"Embedding service returned empty result for {len(self.examples)} gremlin examples")

        embed_dim = len(examples_embedding[0])
        vector_index = self.vector_index.from_name(embed_dim, self.vector_index_name)
        vector_index.add(examples_embedding, self.examples)
        vector_index.save_index_by_name(self.vector_index_name)

        context["embed_dim"] = embed_dim
        return context
