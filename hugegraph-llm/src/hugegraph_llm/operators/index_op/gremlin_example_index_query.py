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


from typing import Any, Dict, List, Optional

import pandas as pd

from hugegraph_llm.config import resource_file, resource_path
from hugegraph_llm.indices.vector_index.base import VectorStoreBase
from hugegraph_llm.models.embeddings.base import BaseEmbedding
from hugegraph_llm.models.embeddings.init_embedding import Embeddings
from hugegraph_llm.utils.log import log


class GremlinExampleIndexQuery:
    def __init__(
        self,
        vector_index: type[VectorStoreBase],
        embedding: Optional[BaseEmbedding] = None,
        num_examples: int = 1,
    ):
        self.embedding = embedding or Embeddings().get_embedding()
        self.num_examples = num_examples
        if not vector_index.exist("gremlin_examples"):
            log.warning("No gremlin example index found, will generate one.")
            self.vector_index = vector_index.from_name(self.embedding.get_embedding_dim(), "gremlin_examples")
            self._build_default_example_index()
        else:
            self.vector_index = vector_index.from_name(self.embedding.get_embedding_dim(), "gremlin_examples")

    def _get_match_result(self, context: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
        if self.num_examples <= 0:
            return []

        query_embedding = context.get("query_embedding")
        if not isinstance(query_embedding, list):
            query_embedding = self.embedding.get_texts_embeddings([query])[0]
        return self.vector_index.search(query_embedding, self.num_examples, dis_threshold=1.8)

    def _build_default_example_index(self):
        properties = pd.read_csv(resource_file("demo", "text2gremlin.csv", root=resource_path)).to_dict(
            orient="records"
        )
        # Some supported services accept at most 10 texts, regardless of the adapter default.
        # Complete each batch sequentially and only publish the index after all batches succeed.
        embeddings = []
        for start in range(0, len(properties), 10):
            texts = [row["query"] for row in properties[start : start + 10]]
            batch_embeddings = self.embedding.get_texts_embeddings(texts)
            if len(batch_embeddings) != len(texts):
                raise ValueError(f"Embedding batch returned {len(batch_embeddings)} vectors for {len(texts)} texts.")
            embeddings.extend(batch_embeddings)
        self.vector_index.add(embeddings, properties)
        self.vector_index.save_index_by_name("gremlin_examples")

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        query = context.get("query")
        if not query:
            raise ValueError("query is required")

        context["match_result"] = self._get_match_result(context, query)
        return context
