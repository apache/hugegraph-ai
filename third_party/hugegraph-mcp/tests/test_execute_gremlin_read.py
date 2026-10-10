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


class FakeGremlinClient:
    def __init__(self):
        self.last_query = None

    def exec(self, query: str):  # minimal interface for tests
        self.last_query = query
        # return a fake list result
        return ["alice", "bob"]


class FakeHugeGraphShapeClient:
    def __init__(self, data):
        self.data = data
        self.last_query = None

    def exec(self, query: str):
        self.last_query = query
        return self.data


class FakePyHugeClient:
    init_kwargs: ClassVar[list[dict]] = []

    def __init__(self, url: str, graph: str, user: str, pwd: str, graphspace=None, timeout=None):
        self.init_kwargs.append(
            {
                "url": url,
                "graph": graph,
                "user": user,
                "pwd": pwd,
                "graphspace": graphspace,
                "timeout": timeout,
            }
        )

    def gremlin(self):
        return FakeGremlinClient()


def test_execute_gremlin_read_basic(monkeypatch):
    """Basic happy path: query is executed with read client and returns data/total/duration/is_read."""

    from hugegraph_mcp import gremlin_tools  # to be implemented

    client = FakeGremlinClient()
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client, raising=False)

    result = gremlin_tools.execute_gremlin_read("g.V().limit(2)")

    assert client.last_query == "g.V().limit(2)"
    assert result["ok"] is True
    assert result["error"] is None
    assert result["data"]["is_read"] is True
    assert result["data"]["total"] == 2
    assert isinstance(result["data"]["duration_ms"], (int, float))
    assert result["meta"]["duration_ms"] == result["data"]["duration_ms"]


def test_execute_gremlin_read_counts_hugegraph_data_shape(monkeypatch):
    from hugegraph_mcp import gremlin_tools

    client = FakeHugeGraphShapeClient({"data": [{"id": "1:Alice"}], "meta": {}})
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client, raising=False)

    result = gremlin_tools.execute_gremlin_read("g.V().limit(1).elementMap()")

    assert result["ok"] is True
    assert result["data"]["total"] == 1
    assert result["data"]["data"] == {"data": [{"id": "1:Alice"}], "meta": {}}


def test_execute_gremlin_read_counts_empty_hugegraph_data_shape(monkeypatch):
    from hugegraph_mcp import gremlin_tools

    client = FakeHugeGraphShapeClient({"data": [], "meta": {}})
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client, raising=False)

    result = gremlin_tools.execute_gremlin_read("g.V().has('name','missing')")

    assert result["ok"] is True
    assert result["data"]["total"] == 0


def test_execute_gremlin_read_includes_unbounded_cost_warning(monkeypatch):
    from hugegraph_mcp import gremlin_tools

    client = FakeGremlinClient()
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client, raising=False)

    result = gremlin_tools.execute_gremlin_read("g.V()")

    assert result["ok"] is True
    assert result["warnings"]


def test_execute_gremlin_read_rejects_unbounded_without_execution(monkeypatch):
    from hugegraph_mcp import gremlin_tools

    client = FakeGremlinClient()
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client)

    result = gremlin_tools.execute_gremlin_read("g.V()", limit_policy="reject_unbounded")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert client.last_query is None


def test_execute_gremlin_read_has_no_cost_warning_for_limited_query(monkeypatch):
    from hugegraph_mcp import gremlin_tools

    client = FakeGremlinClient()
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client, raising=False)

    result = gremlin_tools.execute_gremlin_read("g.V().limit(2)")

    assert result["ok"] is True
    assert result["warnings"] == []


def test_execute_gremlin_read_counts_single_string_as_one(monkeypatch):
    from hugegraph_mcp import gremlin_tools

    client = FakeHugeGraphShapeClient({"data": "Alice", "meta": {}})
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client, raising=False)

    result = gremlin_tools.execute_gremlin_read("g.V().values('name').limit(1)")

    assert result["ok"] is True
    assert result["data"]["total"] == 1


def test_execute_gremlin_read_counts_single_map_as_one(monkeypatch):
    from hugegraph_mcp import gremlin_tools

    client = FakeHugeGraphShapeClient({"data": {"id": "1", "label": "person"}})
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client, raising=False)

    result = gremlin_tools.execute_gremlin_read("g.V().limit(1).elementMap()")

    assert result["ok"] is True
    assert result["data"]["total"] == 1


def test_execute_gremlin_read_rejects_obvious_writes(monkeypatch):
    """Queries with clear write keywords must be rejected even through read tool."""

    from hugegraph_mcp import gremlin_tools

    client = FakeGremlinClient()
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client, raising=False)

    result = gremlin_tools.execute_gremlin_read("g.addV('person')")

    assert result["ok"] is False
    assert result["error"]["type"] == "UNSAFE_GREMLIN"
    assert result["meta"]


def test_execute_gremlin_read_respects_readonly_env(monkeypatch):
    """When HUGEGRAPH_MCP_READONLY is true, execute_gremlin_read should still work (it's read)."""

    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    from hugegraph_mcp import gremlin_tools

    client = FakeGremlinClient()
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client, raising=False)

    result = gremlin_tools.execute_gremlin_read("g.V().count()")

    assert result["ok"] is True
    assert result["data"]["is_read"] is True
    assert "total" in result["data"]


def test_get_read_client_uses_current_env(monkeypatch):
    from hugegraph_mcp import gremlin_tools

    FakePyHugeClient.init_kwargs = []
    monkeypatch.setattr(gremlin_tools, "PyHugeClient", FakePyHugeClient)

    monkeypatch.setenv("HUGEGRAPH_GRAPH", "first_graph")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "first_space")
    monkeypatch.setenv("HUGEGRAPH_CONNECT_TIMEOUT_SECONDS", "1.25")
    monkeypatch.setenv("HUGEGRAPH_READ_TIMEOUT_SECONDS", "7")
    gremlin_tools._get_read_client()

    monkeypatch.setenv("HUGEGRAPH_GRAPH", "second_graph")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "second_space")
    gremlin_tools._get_read_client()

    assert FakePyHugeClient.init_kwargs[0]["graph"] == "first_graph"
    assert FakePyHugeClient.init_kwargs[0]["graphspace"] == "first_space"
    assert FakePyHugeClient.init_kwargs[0]["timeout"] == (1.25, 7.0)
    assert FakePyHugeClient.init_kwargs[1]["graph"] == "second_graph"
    assert FakePyHugeClient.init_kwargs[1]["graphspace"] == "second_space"


def test_execute_gremlin_read_rejects_result_over_item_budget(monkeypatch):
    from hugegraph_mcp import gremlin_tools

    client = FakeHugeGraphShapeClient({"data": ["secret-1", "secret-2"]})
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client)
    monkeypatch.setenv("HUGEGRAPH_MCP_MAX_RESULT_ITEMS", "1")

    result = gremlin_tools.execute_gremlin_read("g.V().limit(2)")

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["details"]["exceeded"] == ["max_result_items"]
    assert result["error"]["details"]["truncated"] is False
    assert result["error"]["details"]["guard_type"] == "post_materialization_output_guard"
    assert result["error"]["details"]["hard_budget"] is False
    assert "post-materialization output guard" in result["error"]["message"]
    assert "secret-1" not in str(result)


def test_execute_gremlin_read_rejects_result_over_byte_budget(monkeypatch):
    from hugegraph_mcp import gremlin_tools

    client = FakeHugeGraphShapeClient(["机密数据"])
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client)
    monkeypatch.setenv("HUGEGRAPH_MCP_MAX_RESULT_BYTES", "4")

    result = gremlin_tools.execute_gremlin_read("g.V().values('name').limit(1)")

    assert result["ok"] is False
    assert result["error"]["details"]["exceeded"] == ["max_result_bytes"]
    assert result["error"]["details"]["result_bytes"] > 4
    assert result["error"]["details"]["guard_type"] == "post_materialization_output_guard"
    assert result["error"]["details"]["hard_budget"] is False
    assert "机密数据" not in str(result)


def test_execute_gremlin_read_allows_result_at_budget(monkeypatch):
    from hugegraph_mcp import gremlin_tools

    client = FakeHugeGraphShapeClient([1])
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: client)
    monkeypatch.setenv("HUGEGRAPH_MCP_MAX_RESULT_ITEMS", "1")
    monkeypatch.setenv("HUGEGRAPH_MCP_MAX_RESULT_BYTES", "3")

    result = gremlin_tools.execute_gremlin_read("g.V().limit(1)")

    assert result["ok"] is True
    assert result["data"]["data"] == [1]
