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
from typing import Any, List, Set, Union

from pymilvus import (  # pylint: disable=import-error
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from hugegraph_llm.config import index_settings
from hugegraph_llm.indices.vector_index.base import VectorStoreBase
from hugegraph_llm.utils.log import log

COLLECTION_NAME_PREFIX = "hugegraph_llm_"


class MilvusVectorIndex(VectorStoreBase):
    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        user="",
        password="",
        embed_dim: int = 1024,
    ):
        self.embed_dim = embed_dim
        self.host = host
        self.port = port
        self.name = COLLECTION_NAME_PREFIX + name
        connections.connect(host=host, port=port, user=user, password=password)

        if not utility.has_collection(self.name):
            self._create_collection()
        else:
            # dim is different, recreate
            existing_collection = Collection(self.name)
            existing_schema = existing_collection.schema
            for field in existing_schema.fields:
                if field.name == "embedding" and field.params.get("dim"):
                    existing_dim = int(field.params["dim"])
                    if existing_dim != self.embed_dim:
                        log.debug(
                            "Milvus collection '%s' dimension mismatch: %d != %d. Recreating.",
                            self.name,
                            existing_dim,
                            self.embed_dim,
                        )
                        utility.drop_collection(self.name)
                        break

        self.collection = Collection(self.name)

    def _create_collection(self):
        """Create a new collection in Milvus."""
        id_field = FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True)
        vector_field = FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.embed_dim)
        property_field = FieldSchema(name="property", dtype=DataType.VARCHAR, max_length=65535)
        original_id_field = FieldSchema(name="original_id", dtype=DataType.INT64)

        schema = CollectionSchema(
            fields=[id_field, vector_field, property_field, original_id_field],
            description="Vector index collection",
        )

        collection = Collection(name=self.name, schema=schema)

        index_params = {
            "metric_type": "L2",
            "index_type": "IVF_FLAT",
            "params": {"nlist": 128},
        }
        collection.create_index(field_name="embedding", index_params=index_params)

    def save_index_by_name(self, *name: str):
        self.collection.flush()

    def _deserialize_property(self, prop) -> str:
        """If input is a string, return as-is. If dict or list, convert to JSON string."""
        if isinstance(prop, str):
            return prop
        return json.dumps(prop)

    def _serialize_property(self, prop: str):
        """If input is a JSON string, parse it. Otherwise, return as-is."""
        try:
            return json.loads(prop)
        except (json.JSONDecodeError, TypeError):
            # a simple string
            return prop

    def add(self, vectors: List[List[float]], props: List[Any]):
        if len(vectors) == 0:
            return

        # Get the current count to use as starting index
        count = self.collection.num_entities
        entities = []

        for i, (vector, prop) in enumerate(zip(vectors, props)):
            idx = count + i
            entities.append(
                {
                    "embedding": vector,
                    "property": self._deserialize_property(prop),
                    "original_id": idx,
                }
            )

        self.collection.insert(entities)
        self.collection.flush()

    def remove(self, props: Union[Set[Any], List[Any]]) -> int:
        if isinstance(props, list):
            props = set(props)
        try:
            self.collection.load()
            remove_num = 0
            for prop in props:
                expr = f'property == "{self._deserialize_property(prop)}"'
                res = self.collection.delete(expr)
                if hasattr(res, "delete_count"):
                    remove_num += res.delete_count
            if remove_num > 0:
                self.collection.flush()
            return remove_num
        finally:
            self.collection.release()

    def search(self, query_vector: List[float], top_k: int, dis_threshold: float = 0.9) -> List[Any]:
        try:
            if self.collection.num_entities == 0:
                return []

            self.collection.load()
            search_params = {"metric_type": "L2", "params": {"nprobe": 10}}
            results = self.collection.search(
                data=[query_vector],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                output_fields=["property"],
            )

            ret = []
            for hits in results:
                for hit in hits:
                    if hit.distance < dis_threshold:
                        prop_str = hit.entity.get("property")
                        prop = self._serialize_property(prop_str)
                        ret.append(prop)
                        log.debug("[✓] Add valid distance %s to results.", hit.distance)
                    else:
                        log.debug(
                            "[x] Distance %s >= threshold %s, ignore this result.",
                            hit.distance,
                            dis_threshold,
                        )

            return ret

        finally:
            self.collection.release()

    def get_all_properties(self) -> list[str]:
        if self.collection.num_entities == 0:
            return []

        self.collection.load()
        try:
            results = self.collection.query(
                expr='property != ""',
                output_fields=["property"],
            )

            return [self._deserialize_property(item["property"]) for item in results]

        finally:
            self.collection.release()

    def get_vector_index_info(self) -> dict:
        self.collection.load()
        try:
            embed_dim = None
            for field in self.collection.schema.fields:
                if field.name == "embedding" and field.dtype == DataType.FLOAT_VECTOR:
                    embed_dim = int(field.params["dim"])
                    break

            if embed_dim is None:
                raise ValueError("Could not determine embedding dimension from schema.")

            properties = self.get_all_properties()
            return {
                "embed_dim": embed_dim,
                "vector_info": {
                    "chunk_vector_num": self.collection.num_entities,
                    "graph_vid_vector_num": self.collection.num_entities,
                    "graph_properties_vector_num": len(properties),
                },
            }
        finally:
            self.collection.release()

    @staticmethod
    def clean(*name: str):
        name_str = "_".join(name)
        connections.connect(
            host=index_settings.milvus_host,
            port=index_settings.milvus_port,
            user=index_settings.milvus_user,
            password=index_settings.milvus_password,
        )
        if utility.has_collection(COLLECTION_NAME_PREFIX + name_str):
            utility.drop_collection(COLLECTION_NAME_PREFIX + name_str)

    @staticmethod
    def from_name(embed_dim: int, *name: str) -> "MilvusVectorIndex":
        name_str = "_".join(name)
        assert index_settings.milvus_host, "Milvus host is not configured"
        return MilvusVectorIndex(
            name_str,
            host=index_settings.milvus_host,
            port=index_settings.milvus_port,
            user=index_settings.milvus_user,
            password=index_settings.milvus_password,
            embed_dim=embed_dim,
        )

    @staticmethod
    def exist(*name: str) -> bool:
        name_str = "_".join(name)
        connections.connect(
            host=index_settings.milvus_host,
            port=index_settings.milvus_port,
            user=index_settings.milvus_user,
            password=index_settings.milvus_password,
        )
        return utility.has_collection(COLLECTION_NAME_PREFIX + name_str)
