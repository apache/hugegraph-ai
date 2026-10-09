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
from pathlib import Path

import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.integration]


class DeterministicEmbedding:
    def get_embedding_dim(self):
        return 2

    def get_texts_embeddings(self, texts):
        return [[float("lop" in text.lower()), float("marko" in text.lower())] for text in texts]

    async def async_get_texts_embeddings(self, texts):
        return self.get_texts_embeddings(texts)


class InMemoryVectorIndex:
    stores = {}

    def __init__(self, name):
        self.name = name
        self.entries = []

    @classmethod
    def from_name(cls, embedding_dim, graph_name, index_name):
        key = (embedding_dim, graph_name, index_name)
        cls.stores.setdefault(key, cls(index_name))
        return cls.stores[key]

    def add(self, embeddings, chunks):
        self.entries.extend(zip(embeddings, chunks))

    def save_index_by_name(self, graph_name, index_name):
        return None

    def search(self, query_embedding, topk, dis_threshold=2):
        scored = [(sum(a * b for a, b in zip(query_embedding, embedding)), chunk) for embedding, chunk in self.entries]
        return [chunk for _, chunk in sorted(scored, reverse=True)[:topk]]


def test_graphrag_smoke_uses_production_vector_and_rerank_operators():
    from hugegraph_llm.operators.common_op.merge_dedup_rerank import MergeDedupRerank
    from hugegraph_llm.operators.index_op.build_vector_index import BuildVectorIndex
    from hugegraph_llm.operators.index_op.vector_index_query import VectorIndexQuery

    InMemoryVectorIndex.stores.clear()
    data_file = Path(__file__).resolve().parents[1] / "data" / "quality_program" / "graphrag_documents.json"
    docs = json.loads(data_file.read_text(encoding="utf-8"))
    chunks = [doc["text"] for doc in docs]
    embedding = DeterministicEmbedding()

    BuildVectorIndex(embedding=embedding, vector_index=InMemoryVectorIndex).run({"chunks": chunks})
    vector_context = VectorIndexQuery(vector_index=InMemoryVectorIndex, embedding=embedding, topk=2).run(
        {"query": "Who created lop?"}
    )
    merged_context = MergeDedupRerank(embedding=embedding, topk_return_results=2, method="bleu").run(
        {
            "query": "Who created lop?",
            "vector_search": True,
            "graph_search": True,
            "vector_result": vector_context["vector_result"],
            "graph_result": ["marko created lop"],
        }
    )

    assert vector_context["vector_result"]
    assert merged_context["graph_result"]
    assert merged_context["vector_result"]
    assert any("lop" in item for item in merged_context["vector_result"])
