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

from unittest.mock import Mock


def _schema_result(readonly: bool = False):
    raw_schema = {
        "vertexlabels": [
            {"id": 1, "name": "person", "properties": ["name"]},
        ],
        "edgelabels": [
            {
                "name": "knows",
                "source_label": "person",
                "target_label": "person",
                "properties": ["since"],
            }
        ],
        "indexlabels": [
            {"name": "personByName"},
            {"name": "knowsBySince"},
        ],
    }
    return {
        "schema": raw_schema,
        "simple_schema": {
            "vertexlabels": [{"id": 1, "name": "person", "properties": ["name"]}],
            "edgelabels": [
                {
                    "name": "knows",
                    "source_label": "person",
                    "target_label": "person",
                    "properties": ["since"],
                }
            ],
        },
        "readonly": readonly,
    }


def _patch_ai_available(monkeypatch, inspect_graph_module):
    monkeypatch.setattr(
        inspect_graph_module,
        "health_check",
        Mock(
            return_value={
                "ok": True,
                "data": {"status": "available", "vid_embedding": "ready"},
                "warnings": [],
            }
        ),
    )


def test_inspect_graph_basic(monkeypatch):
    from hugegraph_mcp.tools import inspect_graph as inspect_graph_module

    monkeypatch.setattr(
        inspect_graph_module, "get_live_schema", lambda: _schema_result()
    )
    execute_read = Mock(
        side_effect=[
            {"data": [3], "total": 1, "duration_ms": 1, "is_read": True},
            {"data": [2], "total": 1, "duration_ms": 1, "is_read": True},
        ]
    )
    monkeypatch.setattr(inspect_graph_module, "execute_gremlin_read", execute_read)
    _patch_ai_available(monkeypatch, inspect_graph_module)

    result = inspect_graph_module.inspect_graph()

    assert result["ok"] is True
    assert result["error"] is None
    assert result["data"]["hugegraph_server_status"] == "available"
    assert result["data"]["hugegraph_ai_status"] == "available"
    assert result["data"]["schema_summary"]["vertexlabels"][0]["name"] == "person"
    assert result["data"]["vertex_count"] == 3
    assert result["data"]["edge_count"] == 2
    assert result["data"]["index_status"] == {"total": 2}
    execute_read.assert_any_call("g.V().count()")
    execute_read.assert_any_call("g.E().count()")


def test_inspect_graph_ai_status_uses_unified_health_check_config(monkeypatch):
    from hugegraph_mcp.tools import inspect_graph as inspect_graph_module

    monkeypatch.setenv("HUGEGRAPH_USER", "alice")
    monkeypatch.setenv("HUGEGRAPH_PASSWORD", "secret")
    monkeypatch.setenv("HUGEGRAPH_AI_URL", "http://ai.example:18001")
    monkeypatch.setenv("HUGEGRAPH_MCP_TIMEOUT_SECONDS", "9")
    monkeypatch.setattr(
        inspect_graph_module, "get_live_schema", lambda: _schema_result()
    )
    monkeypatch.setattr(
        inspect_graph_module,
        "execute_gremlin_read",
        Mock(return_value={"data": [1], "total": 1, "duration_ms": 1, "is_read": True}),
    )
    captured = []

    def fake_health_check(*, cfg):
        captured.append(cfg)
        return {"ok": True, "data": {"status": "available"}, "warnings": []}

    monkeypatch.setattr(inspect_graph_module, "health_check", fake_health_check)

    result = inspect_graph_module.inspect_graph()

    assert result["data"]["hugegraph_ai_status"] == "available"
    assert captured[0].user == "alice"
    assert captured[0].password == "secret"
    assert captured[0].ai_url == "http://ai.example:18001"
    assert captured[0].timeout_seconds == 9


def test_inspect_graph_nested_count_result(monkeypatch):
    from hugegraph_mcp.tools import inspect_graph as inspect_graph_module

    monkeypatch.setattr(
        inspect_graph_module, "get_live_schema", lambda: _schema_result()
    )
    execute_read = Mock(
        side_effect=[
            {
                "data": {"data": [8], "meta": {}},
                "total": 2,
                "duration_ms": 1,
                "is_read": True,
            },
            {
                "data": {"data": [5], "meta": {}},
                "total": 2,
                "duration_ms": 1,
                "is_read": True,
            },
        ]
    )
    monkeypatch.setattr(inspect_graph_module, "execute_gremlin_read", execute_read)
    _patch_ai_available(monkeypatch, inspect_graph_module)

    result = inspect_graph_module.inspect_graph()

    assert result["ok"] is True
    assert result["data"]["vertex_count"] == 8
    assert result["data"]["edge_count"] == 5
    assert "Failed to fetch vertex count" not in result["warnings"]
    assert "Failed to fetch edge count" not in result["warnings"]


def test_inspect_graph_with_raw_schema(monkeypatch):
    from hugegraph_mcp.tools import inspect_graph as inspect_graph_module

    schema = _schema_result()
    monkeypatch.setattr(inspect_graph_module, "get_live_schema", lambda: schema)
    monkeypatch.setattr(
        inspect_graph_module,
        "execute_gremlin_read",
        Mock(return_value={"data": [0], "total": 1, "duration_ms": 1, "is_read": True}),
    )
    _patch_ai_available(monkeypatch, inspect_graph_module)

    result = inspect_graph_module.inspect_graph(include_raw_schema=True)

    assert result["ok"] is True
    assert result["error"] is None
    assert result["data"]["raw_schema"] == schema["schema"]
    assert result["data"]["simple_schema"] == schema["simple_schema"]


def test_inspect_graph_server_unavailable(monkeypatch):
    from hugegraph_mcp.tools import inspect_graph as inspect_graph_module

    monkeypatch.setattr(
        inspect_graph_module,
        "get_live_schema",
        Mock(side_effect=ConnectionError("cannot connect")),
    )
    execute_read = Mock()
    monkeypatch.setattr(inspect_graph_module, "execute_gremlin_read", execute_read)
    _patch_ai_available(monkeypatch, inspect_graph_module)

    result = inspect_graph_module.inspect_graph()

    assert result["ok"] is True
    assert result["data"]["hugegraph_server_status"] == "unavailable"
    assert result["data"]["schema_summary"] is None
    assert result["data"]["vertex_count"] is None
    assert result["data"]["edge_count"] is None
    assert any("HugeGraph Server is unavailable" in w for w in result["warnings"])
    execute_read.assert_not_called()


def test_inspect_graph_ai_unavailable(monkeypatch):
    from hugegraph_mcp.tools import inspect_graph as inspect_graph_module

    monkeypatch.setattr(
        inspect_graph_module, "get_live_schema", lambda: _schema_result()
    )
    monkeypatch.setattr(
        inspect_graph_module,
        "execute_gremlin_read",
        Mock(return_value={"data": [1], "total": 1, "duration_ms": 1, "is_read": True}),
    )
    monkeypatch.setattr(
        inspect_graph_module,
        "health_check",
        Mock(
            return_value={
                "ok": False,
                "error": {"message": "HugeGraph-AI is unavailable: ai down"},
                "warnings": [],
            }
        ),
    )

    result = inspect_graph_module.inspect_graph()

    assert result["ok"] is True
    assert result["data"]["hugegraph_server_status"] == "available"
    assert result["data"]["hugegraph_ai_status"] == "unavailable"
    assert result["data"]["vid_embedding_status"] == "unknown"
    assert any("HugeGraph-AI is unavailable" in w for w in result["warnings"])


def test_inspect_graph_ai_available_when_openapi_fallback_works(monkeypatch):
    from hugegraph_mcp.tools import inspect_graph as inspect_graph_module

    monkeypatch.setattr(
        inspect_graph_module, "get_live_schema", lambda: _schema_result()
    )
    monkeypatch.setattr(
        inspect_graph_module,
        "execute_gremlin_read",
        Mock(return_value={"data": [1], "total": 1, "duration_ms": 1, "is_read": True}),
    )

    monkeypatch.setattr(
        inspect_graph_module,
        "health_check",
        Mock(
            return_value={
                "ok": True,
                "data": {
                    "status": "available",
                    "health_endpoint": "/openapi.json",
                    "openapi": "3.1.0",
                },
                "warnings": [
                    "/graph-index-info: HugeGraph-AI graph index info is unavailable"
                ],
            }
        ),
    )

    result = inspect_graph_module.inspect_graph()

    assert result["ok"] is True
    assert result["data"]["hugegraph_ai_status"] == "available"
    assert result["data"]["vid_embedding_status"] == "unknown"
    assert any("graph index info is unavailable" in w for w in result["warnings"])


def test_inspect_graph_requires_explicit_vid_index_status(monkeypatch):
    from hugegraph_mcp.tools import inspect_graph as inspect_graph_module

    monkeypatch.setattr(
        inspect_graph_module, "get_live_schema", lambda: _schema_result()
    )
    monkeypatch.setattr(
        inspect_graph_module,
        "execute_gremlin_read",
        Mock(return_value={"data": [1], "total": 1, "duration_ms": 1, "is_read": True}),
    )
    monkeypatch.setattr(
        inspect_graph_module,
        "health_check",
        Mock(
            return_value={
                "ok": True,
                "data": {
                    "status": "available",
                    "health_endpoint": "/graph-index-info",
                },
                "warnings": [],
            }
        ),
    )

    result = inspect_graph_module.inspect_graph()

    assert result["ok"] is True
    assert result["data"]["hugegraph_ai_status"] == "available"
    assert result["data"]["vid_embedding_status"] == "unknown"


def test_inspect_graph_includes_next_actions(monkeypatch):
    from hugegraph_mcp.tools import inspect_graph as inspect_graph_module

    monkeypatch.setattr(
        inspect_graph_module, "get_live_schema", lambda: _schema_result()
    )
    monkeypatch.setattr(
        inspect_graph_module,
        "execute_gremlin_read",
        Mock(return_value={"data": [1], "total": 1, "duration_ms": 1, "is_read": True}),
    )
    _patch_ai_available(monkeypatch, inspect_graph_module)

    result = inspect_graph_module.inspect_graph()

    assert result["next_actions"]
    assert any(
        "inspect_graph_tool with include_raw_schema=true" in action
        for action in result["next_actions"]
    )
    assert any(
        "execute_gremlin_read_tool" in action for action in result["next_actions"]
    )
    assert not any("query_graph_tool" in action for action in result["next_actions"])


def test_inspect_graph_readonly_flag(monkeypatch):
    from hugegraph_mcp.tools import inspect_graph as inspect_graph_module

    monkeypatch.setattr(
        inspect_graph_module, "get_live_schema", lambda: _schema_result(readonly=True)
    )
    monkeypatch.setattr(
        inspect_graph_module,
        "execute_gremlin_read",
        Mock(return_value={"data": [1], "total": 1, "duration_ms": 1, "is_read": True}),
    )
    _patch_ai_available(monkeypatch, inspect_graph_module)

    result = inspect_graph_module.inspect_graph()

    assert result["data"]["readonly"] is True
    assert result["meta"]["readonly"] is True
