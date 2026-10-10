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
from dataclasses import asdict, dataclass, field


@dataclass
class NeighborRankStep:
    """
    Step object defines the traversal path rules from the starting vertex.
    """

    direction: str = "BOTH"
    labels: list[str] = field(default_factory=list)
    max_degree: int = 10000
    top: int = 100

    def dumps(self):
        return json.dumps(asdict(self))


@dataclass
class NeighborRankParameters:
    """
    BodyParams defines the body parameters for the rank API requests.
    """

    source: str | int
    label: str
    alpha: float = 0.85
    capacity: int = 10000000
    steps: list[NeighborRankStep] = field(default_factory=list)

    def dumps(self):
        return json.dumps(asdict(self))


@dataclass
class PersonalRankParameters:
    """
    Data class that represents the body parameters for a rank API request.

    Attributes:
      - source (Union[str, int]): The ID of the source vertex. This is a required field with no default value.
      - label (str): The label of the edge type that starts the traversal.
                     This is a required field with no default value.
      - alpha (float): The probability of moving to a neighboring vertex in each iteration,
                       similar to the alpha in PageRank. Optional with a default value of 0.85.
                       The value should be in the range (0, 1].
      - max_degree (int): The maximum number of adjacent edges a single vertex can traverse
                          during the query process. Optional with a default value of 10000.
                          The value should be greater than 0.
      - max_depth (int): The maximum number of iterations for the traversal. Optional with a default value of 5.
                         The value should be within the range [2, 50].
      - limit (int): The maximum number of vertices to return in the results. Optional with a default value of 100.
                     The value should be greater than 0.
      - max_diff (float): The precision difference for early convergence (to be implemented later).
                          Optional with a default value of 0.0001. The value should be in the range (0, 1).
      - sorted (bool): Indicates whether the results should be sorted based on rank.
                       If true, the results are sorted in descending order of rank;
                       if false, they are not sorted. Optional with a default value of True.
      - with_label (str): Determines which results to keep in the final output.
                          Optional with a default value of "BOTH_LABEL". The options are "SAME_LABEL" to keep only
                          vertices of the same category as the source vertex, "OTHER_LABEL" to keep only vertices
                          of a different category (the other end of a bipartite graph), and "BOTH_LABEL" to keep both.
    """

    source: str | int
    label: str
    alpha: float = 0.85
    max_degree: int = 10000
    max_depth: int = 5
    limit: int = 100
    max_diff: float = 0.0001
    sorted: bool = True
    with_label: str = "BOTH_LABEL"

    def dumps(self):
        return json.dumps(asdict(self))
