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


from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.structure.rank_data import (
    NeighborRankParameters,
    PersonalRankParameters,
)
from pyhugegraph.utils import huge_router as router


class RankManager(HugeParamsBase):
    """
    This class provides methods to interact with the rank APIs in HugeGraphServer.
    It allows for personalized recommendations based on graph traversal and ranking algorithms.

    Methods:
        personal_rank(source, label, alpha=0.85, max_degree=10000, max_depth=5,
                       limit=100, sorted=True, with_label="BOTH_LABEL"):
            Computes the Personal Rank for a given source vertex and edge label.

        neighbor_rank(source, steps, alpha=0.85, capacity=10000000):
            Computes the Neighbor Rank for a given source vertex and defined steps.
    """

    @router.http("POST", "traversers/personalrank")
    def personal_rank(self, body_params: PersonalRankParameters):
        """
        Computes the Personal Rank for a given source vertex and edge label.

        Args:
            body_params (PersonalRankParameters): BodyParams defines the body parameters for the rank API requests.

        Returns:
            dict: A dictionary containing the ranked list of vertices and their corresponding rank values.
        """
        return self._invoke_request(data=body_params.dumps())

    @router.http("POST", "traversers/neighborrank")
    def neighbor_rank(self, body_params: NeighborRankParameters):
        """
        Computes the Neighbor Rank for a given source vertex and defined steps.

        Args:
            body_params (NeighborRankParameters): BodyParams defines the body parameters for the rank API requests.

        Returns:
            dict: A dictionary containing the probability of reaching other vertices from the source vertex.
        """
        return self._invoke_request(data=body_params.dumps())
