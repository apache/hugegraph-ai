# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import math

import pytest

from hugegraph_llm.extraction_runtime.v1 import GraphStateV1, InvalidGraphError, StaleGraphError

pytestmark = pytest.mark.unit


def test_graph_promotion_is_immutable_and_monotonic() -> None:
    candidate = {"items": [{"name": "bolt", "count": 2}]}
    state = GraphStateV1()

    initial = state.promote_initial(candidate)
    candidate["items"][0]["name"] = "mutated"

    assert initial.revision == 0
    assert initial.graph["items"][0]["name"] == "bolt"  # type: ignore[index]
    with pytest.raises(TypeError):
        initial.graph["items"][0]["name"] = "mutated"  # type: ignore[index]

    repaired = state.promote_repair(
        {"items": [{"name": "bolt", "count": 3}]},
        expected_base_digest=initial.graph_digest,
    )
    assert repaired.revision == 1
    assert state.current is repaired
    assert repaired.graph_digest != initial.graph_digest


def test_stale_or_invalid_repair_never_mutates_current_graph() -> None:
    state = GraphStateV1()
    initial = state.promote_initial({"items": [{"name": "bolt"}]})

    with pytest.raises(StaleGraphError):
        state.promote_repair({"items": []}, expected_base_digest="sha256:stale")
    assert state.current is initial

    with pytest.raises(InvalidGraphError):
        state.promote_repair({"score": math.nan}, expected_base_digest=initial.graph_digest)
    assert state.current is initial


def test_initial_graph_requires_a_json_object() -> None:
    state = GraphStateV1()
    with pytest.raises(InvalidGraphError):
        state.promote_initial([{"name": "bolt"}])  # type: ignore[arg-type]
    assert state.current is None
