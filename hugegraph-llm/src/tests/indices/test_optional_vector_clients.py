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

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.contract


def test_installed_milvus_client_constructs_adapter_schema():
    milvus = pytest.importorskip("pymilvus", reason="Install the vectordb extra")
    from hugegraph_llm.indices.vector_index.milvus_vector_store import MilvusVectorIndex

    schema = milvus.CollectionSchema(
        fields=[
            milvus.FieldSchema(name="id", dtype=milvus.DataType.INT64, is_primary=True),
            milvus.FieldSchema(name="embedding", dtype=milvus.DataType.FLOAT_VECTOR, dim=3),
        ]
    )
    assert schema.fields[1].params["dim"] == 3
    assert callable(MilvusVectorIndex.search)


def _fake_milvus(monkeypatch, store, collections, created):
    class FakeCollection:
        def __init__(self, name, schema=None):
            if schema is not None:
                collections[name] = next(f.params["dim"] for f in schema.fields if f.name == "embedding")
                created.append(name)
            elif name not in collections:
                raise RuntimeError(f"collection {name} does not exist and no schema given")
            self.name = name
            self.schema = SimpleNamespace(fields=[SimpleNamespace(name="embedding", params={"dim": collections[name]})])

        def create_index(self, **kwargs):
            pass

    monkeypatch.setattr(store, "Collection", FakeCollection)
    monkeypatch.setattr(store, "connections", SimpleNamespace(connect=lambda **kwargs: None))
    monkeypatch.setattr(
        store,
        "utility",
        SimpleNamespace(has_collection=lambda name: name in collections, drop_collection=collections.pop),
    )


@pytest.mark.parametrize(("existing_dim", "expected_created"), [(768, ["hugegraph_llm_graph_vids"]), (1024, [])])
def test_milvus_index_recreates_collection_only_when_dimension_changes(monkeypatch, existing_dim, expected_created):
    pytest.importorskip("pymilvus", reason="Install the vectordb extra")
    from hugegraph_llm.indices.vector_index import milvus_vector_store as store

    collections = {"hugegraph_llm_graph_vids": existing_dim}
    created = []
    _fake_milvus(monkeypatch, store, collections, created)

    index = store.MilvusVectorIndex("graph_vids", "localhost", 19530, embed_dim=1024)

    assert created == expected_created
    assert collections == {"hugegraph_llm_graph_vids": 1024}
    assert index.collection.name == "hugegraph_llm_graph_vids"


def test_installed_qdrant_client_searches_real_local_storage(monkeypatch):
    qdrant = pytest.importorskip("qdrant_client", reason="Install the vectordb extra")
    from hugegraph_llm.indices.vector_index import qdrant_vector_store

    client = qdrant.QdrantClient(":memory:")
    monkeypatch.setattr(qdrant_vector_store, "QdrantClient", lambda **kwargs: client)
    try:
        index = qdrant_vector_store.QdrantVectorIndex("contract", "localhost", 6333, embed_dim=3)
        index.add([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], ["Alice", "Acme"])
        assert index.search([1.0, 0.0, 0.0], top_k=2, dis_threshold=0.2) == ["Alice"]
        assert index.remove(["Alice"]) == 1
        assert index.search([1.0, 0.0, 0.0], top_k=2, dis_threshold=0.2) == []
    finally:
        client.close()


def test_qdrant_threshold_semantics_include_exact_matches(monkeypatch):
    qdrant = pytest.importorskip("qdrant_client", reason="Install the vectordb extra")
    from hugegraph_llm.indices.vector_index import qdrant_vector_store

    client = qdrant.QdrantClient(":memory:")
    monkeypatch.setattr(qdrant_vector_store, "QdrantClient", lambda **kwargs: client)
    try:
        index = qdrant_vector_store.QdrantVectorIndex("contract", "localhost", 6333, embed_dim=3)
        index.add([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], ["Alice", "Acme"])
        # identical vector -> cosine distance 0.0; the orthogonal candidate sits at distance 1.0
        assert index.search([1.0, 0.0, 0.0], top_k=2, dis_threshold=0) == ["Alice"]
        assert sorted(index.search([0.0, 1.0, 0.0], top_k=2, dis_threshold=1.0)) == ["Acme", "Alice"]
        assert index.search([0.0, 1.0, 0.0], top_k=2, dis_threshold=0.5) == ["Acme"]
    finally:
        client.close()


def test_qdrant_threshold_tolerates_float32_score_noise(monkeypatch):
    """A float32 cosine score just under 1.0 must not drop an exact match at threshold 0."""
    qdrant = pytest.importorskip("qdrant_client", reason="Install the vectordb extra")
    from hugegraph_llm.indices.vector_index import qdrant_vector_store

    client = qdrant.QdrantClient(":memory:")
    monkeypatch.setattr(qdrant_vector_store, "QdrantClient", lambda **kwargs: client)
    try:
        index = qdrant_vector_store.QdrantVectorIndex("contract", "localhost", 6333, embed_dim=3)
        hits = SimpleNamespace(
            points=[
                # exact match rounded below 1.0 by float32 storage -> distance 5.96e-8
                SimpleNamespace(score=0.99999994, payload={"property": "Alice"}),
                # 1e-5 away: outside the tolerance and outside threshold 0
                SimpleNamespace(score=0.99999, payload={"property": "Eve"}),
                SimpleNamespace(score=0.5, payload={"property": "Acme"}),
            ]
        )
        monkeypatch.setattr(index.client, "query_points", lambda **kwargs: hits)

        assert index.search([1.0, 0.0, 0.0], top_k=3, dis_threshold=0) == ["Alice"]
    finally:
        client.close()


class _StoringPropertyCollection:
    """Minimal Milvus collection double: stores property text and emulates the query filter."""

    def __init__(self, rows=()):
        self.rows = list(rows)

    @property
    def num_entities(self):
        return len(self.rows)

    def load(self):
        pass

    def release(self):
        pass

    def flush(self):
        pass

    def insert(self, entities):
        self.rows.extend(entity["property"] for entity in entities)

    def search(self, **kwargs):
        hits = [
            SimpleNamespace(distance=0.0, entity=SimpleNamespace(get=lambda key, _p=prop: _p))
            for prop in self.rows[: kwargs.get("limit", len(self.rows))]
        ]
        return [hits]

    def query(self, expr, output_fields):
        # Server-side expression evaluation; fail loudly on any unmodeled expr.
        if expr == 'property != ""':
            kept = [prop for prop in self.rows if prop != ""]
        elif expr == "original_id >= 0":
            kept = list(self.rows)
        else:
            raise ValueError(f"fake cannot evaluate expr: {expr}")
        return [{"property": prop} for prop in kept]


def _milvus_with_rows(monkeypatch, rows):
    pytest.importorskip("pymilvus", reason="Install the vectordb extra")
    from hugegraph_llm.indices.vector_index import milvus_vector_store as store

    collections = {"hugegraph_llm_contract": 2}
    created = []
    _fake_milvus(monkeypatch, store, collections, created)
    index = store.MilvusVectorIndex("contract", "localhost", 19530, embed_dim=2)
    monkeypatch.setattr(index, "collection", _StoringPropertyCollection(rows), raising=True)
    return store, index


def test_milvus_search_returns_json_shaped_chunk_text_unchanged(monkeypatch):
    """Chunk text that parses as JSON must come back as its exact text, not as a decoded value."""
    _, index = _milvus_with_rows(monkeypatch, ["123", "true", '{"answer": 42}', "plain chunk"])

    assert index.search([1.0, 0.0], top_k=4, dis_threshold=1.0) == ["123", "true", '{"answer": 42}', "plain chunk"]


def test_milvus_get_all_properties_round_trips_stored_text_including_empty(monkeypatch):
    """add() then get_all_properties() returns the exact strings, including empty ones."""
    _, index = _milvus_with_rows(monkeypatch, [])
    index.add([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], ["123", "", '{"a": 1}'])

    assert index.get_all_properties() == ["123", "", '{"a": 1}']


def test_milvus_retrieval_keeps_json_shaped_chunks_for_chunk_query(monkeypatch):
    """JSON-shaped chunk text survives Milvus retrieval into chunk results instead of vanishing."""
    from hugegraph_llm.operators.index_op.vector_index_query import VectorIndexQuery

    store, index = _milvus_with_rows(monkeypatch, ["123", "true", '{"answer": 42}', "plain chunk"])
    monkeypatch.setattr(store.MilvusVectorIndex, "from_name", staticmethod(lambda *args, **kwargs: index))
    embedding = MagicMock()
    embedding.get_embedding_dim.return_value = 2
    embedding.get_texts_embeddings.return_value = [[1.0, 0.0]]

    query = VectorIndexQuery(vector_index=store.MilvusVectorIndex, embedding=embedding, topk=4)
    context = query.run({"query": "anything"})

    assert context["vector_result"] == ["123", "true", '{"answer": 42}', "plain chunk"]


def test_milvus_dict_properties_round_trip_into_gremlin_example_results(monkeypatch):
    """A stored example dict survives the Milvus round trip into the gremlin-example consumer as a dict."""
    from hugegraph_llm.operators.index_op.gremlin_example_index_query import GremlinExampleIndexQuery

    _, index = _milvus_with_rows(monkeypatch, [])
    example = {"query": "g.V()", "gremlin": "g.V()"}
    index.add([[1.0, 0.0]], [example])

    query = GremlinExampleIndexQuery.__new__(GremlinExampleIndexQuery)
    query.num_examples = 1
    query.vector_index = index
    embedding = MagicMock()
    embedding.get_texts_embeddings.return_value = [[1.0, 0.0]]
    query.embedding = embedding

    assert query._get_match_result({}, "show all vertices") == [example]


def test_milvus_threshold_semantics_include_exact_matches(monkeypatch):
    pytest.importorskip("pymilvus", reason="Install the vectordb extra")
    from hugegraph_llm.indices.vector_index import milvus_vector_store as store

    collections = {"hugegraph_llm_contract": 2}
    created = []
    _fake_milvus(monkeypatch, store, collections, created)
    index = store.MilvusVectorIndex("contract", "localhost", 19530, embed_dim=2)

    class FakeHit:
        def __init__(self, distance, prop):
            self.distance = distance
            self.entity = SimpleNamespace(get=lambda key, _p=prop: _p)

    monkeypatch.setattr(index.collection, "num_entities", 2, raising=False)
    monkeypatch.setattr(index.collection, "load", lambda: None, raising=False)
    monkeypatch.setattr(index.collection, "release", lambda: None, raising=False)
    monkeypatch.setattr(
        index.collection,
        "search",
        lambda **kwargs: [[FakeHit(0.0, "doc1"), FakeHit(1.0, "doc2")]],
        raising=False,
    )

    assert index.search([1.0, 0.0], top_k=2, dis_threshold=0) == ["doc1"]
    assert index.search([1.0, 0.0], top_k=2, dis_threshold=1.0) == ["doc1", "doc2"]
    assert index.search([1.0, 0.0], top_k=2, dis_threshold=0.5) == ["doc1"]
