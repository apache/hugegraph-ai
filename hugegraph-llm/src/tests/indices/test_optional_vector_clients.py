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
