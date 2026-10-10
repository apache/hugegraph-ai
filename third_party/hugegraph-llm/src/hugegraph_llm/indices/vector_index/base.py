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
    def get_all_properties(self) -> list[str]:
        """
        #TODO: finish comment
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
        #TODO: finish comment
        """

    @abstractmethod
    def get_vector_index_info(
        self,
    ) -> Dict:
        """
        #TODO: finish comment
        """

    @staticmethod
    @abstractmethod
    def from_name(embed_dim: int, *name: str) -> "VectorStoreBase":
        """
        #TODO: finish comment
        """

    @staticmethod
    @abstractmethod
    def exist(*name: str) -> bool:
        """
        #TODO: finish comment
        """

    @staticmethod
    @abstractmethod
    def clean(*name: str) -> bool:
        """
        #TODO: finish comment
        """
