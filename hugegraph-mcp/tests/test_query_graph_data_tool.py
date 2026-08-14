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

from typing import ClassVar
from unittest.mock import Mock

import pytest

from hugegraph_mcp.tools import query_graph_data as query_module


class Vertex:
    id = "1:alice"
    label = "person"
    type = "vertex"
    properties: ClassVar[dict[str, str]] = {"name": "Alice"}


class Edge:
    id = "edge-1"
    label = "knows"
    type = "edge"
    outV = "1:alice"
    outVLabel = "person"
    inV = "1:bob"
    inVLabel = "person"
    properties: ClassVar[dict[str, int]] = {"since": 2024}


class FakeGraphManager:
    def __init__(self):
        self.calls = []

    def getVertexById(self, vertex_id):
        self.calls.append(("getVertexById", vertex_id))
        return Vertex()

    def getVerticesById(self, vertex_ids):
        self.calls.append(("getVerticesById", vertex_ids))
        return [Vertex()]

    def getVertexByPage(self, label, limit, page=None, properties=None):
        self.calls.append(("getVertexByPage", label, limit, page, properties))
        return [Vertex()], "next-page"

    def getVertexByCondition(self, label="", limit=0, page=None, properties=None):
        self.calls.append(("getVertexByCondition", label, limit, page, properties))
        return [Vertex()]

    def getVertexByConditionWithPage(
        self, label="", limit=0, page=None, properties=None
    ):
        self.calls.append(
            ("getVertexByConditionWithPage", label, limit, page, properties)
        )
        return [Vertex()], "condition-next"

    def getEdgeById(self, edge_id):
        self.calls.append(("getEdgeById", edge_id))
        return Edge()

    def getEdgesById(self, edge_ids):
        self.calls.append(("getEdgesById", edge_ids))
        return [Edge()]

    def getEdgeByPage(
        self,
        label=None,
        vertex_id=None,
        direction=None,
        limit=0,
        page=None,
        properties=None,
    ):
        self.calls.append(
            ("getEdgeByPage", label, vertex_id, direction, limit, page, properties)
        )
        return [Edge()], "edge-next"


def test_query_vertex_by_id(monkeypatch):
    manager = FakeGraphManager()
    monkeypatch.setattr(query_module, "_graph_manager", lambda: manager)

    result = query_module.query_graph_data(
        target="vertex",
        operation="get_by_id",
        id="1:alice",
    )

    assert result["ok"] is True
    assert result["data"]["count"] == 1
    assert result["data"]["items"][0]["id"] == "1:alice"
    assert manager.calls == [("getVertexById", "1:alice")]


def test_query_get_by_ids_deduplicates(monkeypatch):
    manager = FakeGraphManager()
    monkeypatch.setattr(query_module, "_graph_manager", lambda: manager)

    result = query_module.query_graph_data(
        target="edge",
        operation="get_by_ids",
        ids=["edge-1", "edge-1"],
    )

    assert result["ok"] is True
    assert result["warnings"] == ["Ignored 1 duplicate id value(s)."]
    assert manager.calls == [("getEdgesById", ["edge-1"])]


def test_get_by_ids_with_mixed_key_type_dict_returns_validation_error():
    result = query_module.query_graph_data(
        target="vertex",
        operation="get_by_ids",
        ids=[{1: "a", "1": "b"}],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"]["field"] == "ids[0]"


def test_get_by_ids_dedupe_still_works_for_normal_inputs(monkeypatch):
    manager = FakeGraphManager()
    monkeypatch.setattr(query_module, "_graph_manager", lambda: manager)

    result = query_module.query_graph_data(
        target="vertex",
        operation="get_by_ids",
        ids=["1", "1", 1, 1, "2", "2"],
    )

    assert result["ok"] is True
    assert result["warnings"] == ["Ignored 3 duplicate id value(s)."]
    assert manager.calls == [("getVerticesById", ["1", 1, "2"])]


def test_query_get_by_ids_keeps_type_distinct_vertex_ids(monkeypatch):
    manager = FakeGraphManager()
    monkeypatch.setattr(query_module, "_graph_manager", lambda: manager)

    result = query_module.query_graph_data(
        target="vertex",
        operation="get_by_ids",
        ids=[1, "1", 1],
    )

    assert result["ok"] is True
    assert result["warnings"] == ["Ignored 1 duplicate id value(s)."]
    assert manager.calls == [("getVerticesById", [1, "1"])]


def test_query_vertex_page_requires_label():
    result = query_module.query_graph_data(target="vertex", operation="page")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "label is required" in result["error"]["message"]


@pytest.mark.parametrize(
    "vertex_id",
    [True, ["1"], {"id": "1"}, 1.5, 2**63, -(2**63) - 1],
)
def test_query_vertex_by_id_rejects_invalid_vertex_id_types(vertex_id):
    result = query_module.query_graph_data(
        target="vertex",
        operation="get_by_id",
        id=vertex_id,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"]["field"] == "id"


@pytest.mark.parametrize(
    "vertex_id",
    [False, ["1"], {"id": "1"}, 1.5, 2**63, -(2**63) - 1],
)
def test_query_vertex_get_by_ids_rejects_each_invalid_vertex_id(vertex_id):
    result = query_module.query_graph_data(
        target="vertex",
        operation="get_by_ids",
        ids=["1", vertex_id],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"]["field"] == "ids[1]"


def test_query_edge_id_is_not_validated_as_vertex_id(monkeypatch):
    manager = FakeGraphManager()
    monkeypatch.setattr(query_module, "_graph_manager", lambda: manager)
    edge_id = "S1:alice>11>knows>S2:bob"

    result = query_module.query_graph_data(
        target="edge",
        operation="get_by_id",
        id=edge_id,
    )

    assert result["ok"] is True
    assert manager.calls == [("getEdgeById", edge_id)]


def test_query_rejects_limit_over_500():
    result = query_module.query_graph_data(
        target="vertex",
        operation="condition",
        properties={"name": "Alice"},
        limit=501,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "limit exceeds" in result["error"]["message"]


@pytest.mark.parametrize(
    ("operation", "operation_args"),
    [
        ("get_by_id", {"id": "1:alice"}),
        ("get_by_ids", {"ids": ["1:alice"]}),
    ],
)
@pytest.mark.parametrize("limit", ["abc", 0, -1, query_module.MAX_LIMIT + 1])
def test_query_by_id_operations_reject_invalid_limit_before_manager_call(
    monkeypatch, operation, operation_args, limit
):
    manager = FakeGraphManager()
    manager_factory = Mock(return_value=manager)
    monkeypatch.setattr(query_module, "_graph_manager", manager_factory)

    result = query_module.query_graph_data(
        target="vertex",
        operation=operation,
        limit=limit,
        **operation_args,
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["retryable"] is False
    manager_factory.assert_not_called()
    assert manager.calls == []


def test_query_condition_requires_properties():
    result = query_module.query_graph_data(target="vertex", operation="condition")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "properties is required" in result["error"]["message"]


def test_query_edge_page_requires_direction_with_vertex_id():
    result = query_module.query_graph_data(
        target="edge",
        operation="page",
        vertex_id="1:alice",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "direction is required" in result["error"]["message"]


def test_query_edge_page_rejects_vertex_id_with_nonempty_page(monkeypatch):
    manager = FakeGraphManager()
    monkeypatch.setattr(query_module, "_graph_manager", lambda: manager)

    result = query_module.query_graph_data(
        target="edge",
        operation="page",
        label="knows",
        vertex_id="1:alice",
        direction="out",
        limit=5,
        page="p1",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "vertex_id" in result["error"]["suggestion"]
    assert "page" in result["error"]["suggestion"]
    assert manager.calls == []


def test_query_edge_page_by_vertex_without_page(monkeypatch):
    manager = FakeGraphManager()
    monkeypatch.setattr(query_module, "_graph_manager", lambda: manager)

    result = query_module.query_graph_data(
        target="edge",
        operation="page",
        label="knows",
        vertex_id="1:alice",
        direction="out",
        limit=5,
    )

    assert result["ok"] is True
    assert result["data"]["next_page"] == "edge-next"
    assert manager.calls == [
        ("getEdgeByPage", "knows", "1:alice", "OUT", 5, None, None)
    ]


def test_query_edge_page_by_vertex_allows_empty_page(monkeypatch):
    manager = FakeGraphManager()
    monkeypatch.setattr(query_module, "_graph_manager", lambda: manager)

    result = query_module.query_graph_data(
        target="edge",
        operation="page",
        vertex_id="1:alice",
        direction="both",
        page="",
    )

    assert result["ok"] is True
    assert manager.calls == [("getEdgeByPage", None, "1:alice", "BOTH", 100, "", None)]


def test_query_edge_page_cursor_without_vertex_id(monkeypatch):
    manager = FakeGraphManager()
    monkeypatch.setattr(query_module, "_graph_manager", lambda: manager)

    result = query_module.query_graph_data(
        target="edge",
        operation="page",
        label="knows",
        limit=5,
        page="p1",
    )

    assert result["ok"] is True
    assert result["data"]["next_page"] == "edge-next"
    assert manager.calls == [("getEdgeByPage", "knows", None, None, 5, "p1", None)]


def test_query_vertex_condition_returns_next_page(monkeypatch):
    manager = FakeGraphManager()
    monkeypatch.setattr(query_module, "_graph_manager", lambda: manager)

    result = query_module.query_graph_data(
        target="vertex",
        operation="condition",
        label="person",
        properties={"name": "Alice"},
        limit=5,
        page="p1",
    )

    assert result["ok"] is True
    assert result["data"]["next_page"] == "condition-next"
    assert manager.calls == [
        ("getVertexByConditionWithPage", "person", 5, "p1", {"name": "Alice"})
    ]


def test_query_vertex_condition_supports_legacy_client_without_page(monkeypatch):
    class LegacyManager:
        def getVertexByCondition(self, label="", limit=0, page=None, properties=None):
            return [Vertex()]

    monkeypatch.setattr(query_module, "_graph_manager", lambda: LegacyManager())

    result = query_module.query_graph_data(
        target="vertex",
        operation="condition",
        label="person",
        properties={"name": "Alice"},
        limit=5,
        page="p1",
    )

    assert result["ok"] is True
    assert result["data"]["count"] == 1
    assert result["data"]["next_page"] is None


def test_query_no_index_returns_no_index(monkeypatch):
    class BrokenManager:
        def getVertexByCondition(self, **kwargs):
            raise RuntimeError("NoIndexException: no index")

    monkeypatch.setattr(query_module, "_graph_manager", lambda: BrokenManager())

    result = query_module.query_graph_data(
        target="vertex",
        operation="condition",
        label="person",
        properties={"name": "Alice"},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "NO_INDEX"
    assert any("P0b" in action for action in result["next_actions"])


def test_query_not_indexed_message_returns_no_index(monkeypatch):
    class BrokenManager:
        def getVertexByCondition(self, **kwargs):
            raise RuntimeError(
                "The property key 'name' is not indexed and may not match secondary condition"
            )

    monkeypatch.setattr(query_module, "_graph_manager", lambda: BrokenManager())

    result = query_module.query_graph_data(
        target="vertex",
        operation="condition",
        label="person",
        properties={"name": "Alice"},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "NO_INDEX"
    assert result["error"]["retryable"] is False
    assert result["error"]["details"]["reason"] == "no_index"
