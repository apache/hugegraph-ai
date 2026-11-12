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


from abc import ABC, abstractmethod
from typing import Any, Dict, List, Set, Union


class VectorStoreBase(ABC):
    """
    Abstract base class defining the interface for a vector store.
    Implementations must support adding, removing, searching vectors,
    saving/loading from disk, and cleaning up resources.
    """

    @abstractmethod
    def add(self, vectors: List[List[float]], props: List[Any]):
        """
        Add a list of vectors and their corresponding properties to the store.

        Args:
            vectors (List[List[float]]): List of embedding vectors.
            props (List[Any]): List of associated metadata or properties for each vector.
        """

    @abstractmethod
    def get_all_properties(self) -> list[Any]:
        """
        Return all properties currently stored in the index.

        Returns:
            List[Any]: The values previously passed to add().
        """

    @abstractmethod
    def remove(self, props: Union[Set[Any], List[Any]]) -> int:
        """
        Remove vectors based on their associated properties.

        Args:
            props (Union[Set[Any], List[Any]]): Properties of vectors to remove.

        Returns:
            int: Number of vectors removed.
        """

    @abstractmethod
    def search(self, query_vector: List[float], top_k: int, dis_threshold: float = 0.9) -> List[Any]:
        """
        Search for the top_k most similar vectors to the query vector.

        Args:
            query_vector (List[float]): The vector to query against the index.
            top_k (int): Number of top results to return.
            dis_threshold (float): Distance threshold below which results are considered relevant.

        Returns:
            List[Any]: List of properties of the matched vectors.
        """

    @abstractmethod
    def save_index_by_name(self, *name: str):
        """
        Persist the index under the given name.

        Server-backed stores persist on write and may do nothing here.

        Args:
            *name (str): Path segments identifying the index.
        """

    @abstractmethod
    def get_vector_index_info(
        self,
    ) -> Dict:
        """
        Return backend-specific statistics about the index.

        Returns:
            Dict: Informational stats (e.g. dimensions and entry counts) for display and diagnostics.
        """

    @staticmethod
    @abstractmethod
    def from_name(embed_dim: int, *name: str) -> "VectorStoreBase":
        """
        Return the index registered under the given name.

        Loads persisted data when it exists; otherwise returns an empty index sized to embed_dim.
        Reusing persisted vectors requires passing their existing dimension as embed_dim: vectors
        built with a different dimension cannot be reused, so the call returns a fresh empty index
        sized to embed_dim instead of failing the load. Disposal of the stale data is
        backend-specific: the file-backed store keeps its saved files untouched, while
        server-backed stores delete and recreate the underlying collection, so a caller that
        changes embed_dim must expect to re-index.

        Args:
            embed_dim (int): Vector dimension used when a new index is needed, including when
                the persisted dimension cannot be reused.
            *name (str): Path segments identifying the index.

        Returns:
            VectorStoreBase: The loaded index, or an empty index sized to embed_dim when no
                reusable data is persisted.
        """

    @staticmethod
    @abstractmethod
    def exist(*name: str) -> bool:
        """
        Check whether an index exists under the given name.

        Args:
            *name (str): Path segments identifying the index.

        Returns:
            bool: True when the index exists.
        """

    @staticmethod
    @abstractmethod
    def clean(*name: str) -> None:
        """
        Delete the index stored under the given name, if it exists.

        Args:
            *name (str): Path segments identifying the index.
        """
