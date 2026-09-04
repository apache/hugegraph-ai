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

from hugegraph_mcp import gremlin_tools
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.tools import generate_gremlin as generate_gremlin_module


def _ai_ok(gremlin: str, **extra) -> dict:
    data = {
        "gremlin": gremlin,
        "template_gremlin": gremlin,
        "raw_gremlin": gremlin,
        "requires_index": False,
        "assumptions": None,
    }
    data.update(extra)
    return envelope_ok(data)


class FakeGremlinClient:
    def exec(self, query: str):
        return {"data": [{"query": query}], "meta": {}}


def test_generate_gremlin_default_no_execute(monkeypatch):
    post = Mock(return_value=_ai_ok("g.V().count()"))
    execute_read = Mock()
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin("count vertices")

    assert result["ok"] is True
    assert result["data"]["gremlin"] == "g.V().count()"
    assert result["data"]["template_gremlin"] == "g.V().count()"
    assert result["data"]["raw_gremlin"] == "g.V().count()"
    assert result["data"]["is_readonly"] is True
    assert result["data"]["risk_level"] == "low"
    assert result["data"]["requires_index"] is False
    assert result["data"]["assumptions"] is None
    assert result["data"]["executed"] is False
    assert result["data"]["execution_result"] is None
    post.assert_called_once_with(
        "/text2gremlin",
        json={
            "query": "count vertices",
            "client_config": {
                "graph": "hugegraph",
                "gs": "DEFAULT",
            },
        },
    )
    execute_read.assert_not_called()


def test_generate_gremlin_passes_generation_output_types(monkeypatch):
    post = Mock(return_value=_ai_ok("g.V().count()"))
    monkeypatch.setattr(generate_gremlin_module, "post", post)

    result = generate_gremlin_module.generate_gremlin(
        "count vertices",
        output_types=["match_result", "raw_gremlin"],
    )

    assert result["ok"] is True
    post.assert_called_once_with(
        "/text2gremlin",
        json={
            "query": "count vertices",
            "client_config": {
                "graph": "hugegraph",
                "gs": "DEFAULT",
            },
            "output_types": ["match_result", "raw_gremlin"],
        },
    )


def test_generate_gremlin_returns_match_result_without_requiring_gremlin(monkeypatch):
    post = Mock(
        return_value=envelope_ok(
            {
                "match_result": [{"query": "count", "gremlin": "g.V().count()"}],
                "template_gremlin": "",
                "raw_gremlin": "",
            }
        )
    )
    execute_read = Mock()
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin("count vertices", output_types=["match_result"])

    assert result["ok"] is True
    assert result["data"]["match_result"] == [{"query": "count", "gremlin": "g.V().count()"}]
    assert result["data"]["gremlin"] is None
    assert result["data"]["is_readonly"] is False
    assert result["data"]["executed"] is False
    execute_read.assert_not_called()


def test_generate_gremlin_passes_graph_and_graphspace_only(monkeypatch):
    post = Mock(return_value=_ai_ok("g.V().count()"))
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setenv("HUGEGRAPH_URL", "http://mcp-graph:8080")
    monkeypatch.setenv("HUGEGRAPH_AI_GRAPH_URL", "http://ai-visible-graph:8080")
    monkeypatch.setenv("HUGEGRAPH_GRAPH_PATH", "space_a/graph_a")

    result = generate_gremlin_module.generate_gremlin("count vertices")

    assert result["ok"] is True
    post.assert_called_once_with(
        "/text2gremlin",
        json={
            "query": "count vertices",
            "client_config": {
                "graph": "graph_a",
                "gs": "space_a",
            },
        },
    )


def test_generate_gremlin_rejects_execution_output_types_before_ai_call(monkeypatch):
    post = Mock()
    execute_read = Mock()
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin(
        "count vertices",
        execute=False,
        output_types=["raw_execution_result"],
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert result["error"]["details"]["invalid_output_types"] == ["raw_execution_result"]
    post.assert_not_called()
    execute_read.assert_not_called()


def test_generate_gremlin_rejects_non_string_output_type(monkeypatch):
    post = Mock()
    monkeypatch.setattr(generate_gremlin_module, "post", post)

    result = generate_gremlin_module.generate_gremlin("count vertices", output_types=[1])

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    post.assert_not_called()


def test_generate_gremlin_rejects_missing_gremlin(monkeypatch):
    post = Mock(return_value=envelope_ok({"requires_index": False, "assumptions": ["no query generated"]}))
    execute_read = Mock()
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin("count vertices", execute=True)

    assert result["ok"] is False
    assert result["error"]["type"] == "FLOW_EXECUTION_FAILED"
    assert result["error"]["message"] == "HugeGraph-AI did not return Gremlin."
    execute_read.assert_not_called()


def test_generate_gremlin_safe_execute(monkeypatch):
    post = Mock(return_value=_ai_ok("g.V().limit(2)"))
    execution_data = {
        "data": [{"id": 1}],
        "total": 1,
        "duration_ms": 1,
        "is_read": True,
    }
    execution_result = envelope_ok(execution_data, duration_ms=1)
    execute_read = Mock(return_value=execution_result)
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin("show two vertices", execute=True)

    assert result["ok"] is True
    assert result["data"]["is_readonly"] is True
    assert result["data"]["risk_level"] == "low"
    assert result["data"]["requires_index"] is False
    assert result["data"]["assumptions"] is None
    assert result["data"]["executed"] is True
    assert result["data"]["execution_result"] == execution_data
    assert result["data"]["execution_meta"] == execution_result["meta"]
    execute_read.assert_called_once_with("g.V().limit(2)", limit_policy="warn")


def test_generate_gremlin_unwraps_execution_envelope(monkeypatch):
    post = Mock(return_value=_ai_ok("g.V().limit(1)"))
    execution_result = envelope_ok(
        {"data": [{"id": 1}], "total": 1, "duration_ms": 1, "is_read": True},
        duration_ms=1,
    )
    execute_read = Mock(return_value=execution_result)
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin("show one vertex", execute=True)

    assert result["ok"] is True
    assert result["data"]["executed"] is True
    assert "ok" not in result["data"]["execution_result"]


def test_generate_gremlin_passes_limit_policy(monkeypatch):
    post = Mock(return_value=_ai_ok("g.V()"))
    execution_result = envelope_err(
        ErrorType.VALIDATION_ERROR,
        "unbounded",
    )
    execute_read = Mock(return_value=execution_result)
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin(
        "show vertices",
        execute=True,
        limit_policy="reject_unbounded",
    )

    assert result["ok"] is False
    execute_read.assert_called_once_with("g.V()", limit_policy="reject_unbounded")


def test_generate_gremlin_reject_unbounded_limit_policy(monkeypatch):
    post = Mock(return_value=_ai_ok("g.V()"))
    monkeypatch.setattr(generate_gremlin_module, "post", post)

    result = generate_gremlin_module.generate_gremlin(
        "show vertices",
        execute=True,
        limit_policy="reject_unbounded",
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "VALIDATION_ERROR"
    assert "unbounded" in result["error"]["message"]


def test_generate_gremlin_auto_append_limit_policy(monkeypatch):
    post = Mock(return_value=_ai_ok("g.V()"))
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(gremlin_tools, "_get_read_client", lambda: FakeGremlinClient())

    result = generate_gremlin_module.generate_gremlin(
        "show vertices",
        execute=True,
        limit_policy="auto_append",
    )

    assert result["ok"] is True
    execution = result["data"]["execution_result"]
    assert execution["original_gremlin"] == "g.V()"
    assert execution["executed_gremlin"] == "g.V().limit(100)"
    assert execution["rewrite_reason"]


def test_generate_gremlin_propagates_execute_failure(monkeypatch):
    post = Mock(return_value=_ai_ok("g.V().has('name','Alice')"))
    execution_error = envelope_err(
        ErrorType.NO_INDEX,
        "Query requires an index",
        suggestion="Create an index",
    )
    execute_read = Mock(return_value=execution_error)
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin("find Alice", execute=True)

    assert result["ok"] is False
    assert result["error"]["type"] == "NO_INDEX"
    assert result["error"]["details"]["gremlin"] == "g.V().has('name','Alice')"
    assert result["error"]["details"]["execution_error"]["message"] == ("Query requires an index")


def test_generate_gremlin_unsafe_no_execute(monkeypatch):
    post = Mock(return_value=_ai_ok("g.addV('person')"))
    execute_read = Mock()
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin("add a person", execute=True)

    assert result["ok"] is False
    assert result["error"]["type"] == "UNSAFE_GREMLIN"
    assert result["error"]["message"] == "Generated Gremlin is not safe to execute automatically"
    assert result["error"]["details"]["classification"] == "unsafe"
    execute_read.assert_not_called()


def test_generate_gremlin_ai_unavailable(monkeypatch):
    ai_error = envelope_err(
        ErrorType.HUGEGRAPH_AI_UNAVAILABLE,
        "HugeGraph-AI is unavailable",
        retryable=True,
    )
    post = Mock(return_value=ai_error)
    execute_read = Mock()
    monkeypatch.setattr(generate_gremlin_module, "post", post)
    monkeypatch.setattr(generate_gremlin_module, "execute_gremlin_read", execute_read)

    result = generate_gremlin_module.generate_gremlin("count vertices", execute=True)

    assert result == ai_error
    execute_read.assert_not_called()
