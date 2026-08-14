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


class FakeSchemaManager:
    def __init__(self, schema):
        self._schema = schema

    def getSchema(self, _format: str = "json"):
        return self._schema


class FakePyHugeClient:
    last_init_kwargs: dict | None = None
    schema_data: dict | None = None

    def __init__(
        self, url: str, graph: str, user: str, pwd: str, graphspace=None, timeout=None
    ):
        FakePyHugeClient.last_init_kwargs = {
            "url": url,
            "graph": graph,
            "user": user,
            "pwd": pwd,
            "graphspace": graphspace,
            "timeout": timeout,
        }
        self._schema = FakePyHugeClient.schema_data

    def schema(self):
        return FakeSchemaManager(self._schema)


def _make_full_schema():
    return {
        "vertexlabels": [
            {"id": 1, "name": "person", "properties": ["name", "age"]},
        ],
        "edgelabels": [
            {
                "name": "knows",
                "source_label": "person",
                "target_label": "person",
                "properties": ["since"],
            }
        ],
        "propertykeys": [
            {"name": "name", "data_type": "TEXT"},
            {"name": "age", "data_type": "INT"},
            {"name": "since", "data_type": "INT"},
        ],
    }


def test_get_live_schema_basic(monkeypatch):
    from hugegraph_mcp import schema_tools

    FakePyHugeClient.schema_data = _make_full_schema()
    monkeypatch.setattr(schema_tools, "PyHugeClient", FakePyHugeClient)

    result = schema_tools.get_live_schema()

    assert "schema" in result
    assert result["schema"] == FakePyHugeClient.schema_data
    assert "simple_schema" in result
    simple = result["simple_schema"]
    assert "vertexlabels" in simple
    assert "edgelabels" in simple
    assert simple["vertexlabels"][0]["name"] == "person"
    assert simple["edgelabels"][0]["name"] == "knows"


def test_get_live_schema_with_graphspace(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_GRAPH_PATH", "mcp_space/hugegraph")

    import hugegraph_mcp.schema_tools

    FakePyHugeClient.schema_data = _make_full_schema()
    monkeypatch.setattr(hugegraph_mcp.schema_tools, "PyHugeClient", FakePyHugeClient)

    result = hugegraph_mcp.schema_tools.get_live_schema()

    # Type checker: ensure last_init_kwargs is not None before accessing
    assert FakePyHugeClient.last_init_kwargs is not None
    assert FakePyHugeClient.last_init_kwargs["graphspace"] == "mcp_space"
    assert result.get("graphspace") == "mcp_space"


def test_get_live_schema_uses_current_env_without_reload(monkeypatch):
    from hugegraph_mcp import schema_tools

    FakePyHugeClient.schema_data = _make_full_schema()
    monkeypatch.setattr(schema_tools, "PyHugeClient", FakePyHugeClient)

    monkeypatch.setenv("HUGEGRAPH_GRAPH", "first_graph")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "first_space")
    schema_tools.get_live_schema()
    first_kwargs = dict(FakePyHugeClient.last_init_kwargs)

    monkeypatch.setenv("HUGEGRAPH_GRAPH", "second_graph")
    monkeypatch.setenv("HUGEGRAPH_GRAPHSPACE", "second_space")
    schema_tools.get_live_schema()
    second_kwargs = dict(FakePyHugeClient.last_init_kwargs)

    assert first_kwargs["graph"] == "first_graph"
    assert first_kwargs["graphspace"] == "first_space"
    assert second_kwargs["graph"] == "second_graph"
    assert second_kwargs["graphspace"] == "second_space"


def test_get_live_schema_respects_readonly_flag(monkeypatch):
    monkeypatch.setenv("HUGEGRAPH_MCP_READONLY", "true")

    from hugegraph_mcp import schema_tools

    FakePyHugeClient.schema_data = _make_full_schema()
    monkeypatch.setattr(schema_tools, "PyHugeClient", FakePyHugeClient)

    result = schema_tools.get_live_schema()

    assert result.get("readonly") is True


def test_current_live_schema_respects_explicit_empty_schema(monkeypatch):
    from hugegraph_mcp import schema_tools
    from hugegraph_mcp.tools.live_schema import current_live_schema

    def fail_fetch():
        raise AssertionError(
            "current_live_schema should not fetch when schema is provided"
        )

    empty_schema = {}
    monkeypatch.setattr(schema_tools, "get_live_schema", fail_fetch)

    assert current_live_schema(empty_schema) is empty_schema


def test_fetch_live_schema_or_none_logs_fetch_failures(monkeypatch, caplog):
    from hugegraph_mcp import schema_tools
    from hugegraph_mcp.tools.live_schema import fetch_live_schema_or_none

    def fail_fetch():
        raise RuntimeError("schema fetch failed")

    monkeypatch.setattr(schema_tools, "get_live_schema", fail_fetch)

    with caplog.at_level("WARNING", logger="hugegraph_mcp.live_schema"):
        result = fetch_live_schema_or_none()

    assert result is None
    assert "Failed to fetch live schema: schema fetch failed" in caplog.text
