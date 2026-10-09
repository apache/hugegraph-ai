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

import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.integration]


class DeterministicEmbedding:
    def get_embedding_dim(self):
        return 2

    def get_texts_embeddings(self, texts):
        return [[float("hugegraph" in text.lower()), float("olap" in text.lower())] for text in texts]

    def get_text_embedding(self, text):
        return self.get_texts_embeddings([text])[0]

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


def test_rag_document_split_index_and_retrieve_use_production_operators():
    from hugegraph_llm.document.chunk_split import ChunkSplitter
    from hugegraph_llm.operators.index_op.build_vector_index import BuildVectorIndex
    from hugegraph_llm.operators.index_op.vector_index_query import VectorIndexQuery

    InMemoryVectorIndex.stores.clear()
    documents = [
        "HugeGraph is a high performance graph database.",
        "HugeGraph supports OLTP and OLAP workloads.",
    ]
    chunks = ChunkSplitter(split_type="paragraph", language="en").split(documents)
    embedding = DeterministicEmbedding()

    BuildVectorIndex(embedding=embedding, vector_index=InMemoryVectorIndex).run({"chunks": chunks})
    context = VectorIndexQuery(vector_index=InMemoryVectorIndex, embedding=embedding, topk=2).run(
        {"query": "HugeGraph OLAP"}
    )

    assert chunks
    assert context["vector_result"]
    assert any("OLAP" in item for item in context["vector_result"])
